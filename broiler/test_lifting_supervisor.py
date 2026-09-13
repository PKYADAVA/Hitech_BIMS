"""A lifting supervised by somebody the employee register does not have.

The column was a foreign key to hr.Employee and nothing else, so a lifting
watched over by a contractor's man, a stand-in, or anyone not yet on the HR
register had nowhere to be recorded — and the sale still happened. `driver` and
`vehicle` beside it have always been free text for exactly that reason.

The rule these hold to is that a row has one answer to "who supervised it":
picking from the list clears anything typed, so nothing reading the register
has to choose between two columns.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.test import TestCase

from broiler.models import (BirdSale, Branch, BroilerFarm, Farmer, Region,
                            Supervisor)
from broiler.views import _bird_sale_to_dict
from hr.models import Employee
from sales.models import Customer


class LiftingSupervisorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region, prefix="AKB")
        supervisor = Supervisor.objects.create(branch=branch, name="R. Verma")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        cls.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=supervisor, farmer=farmer, region=region,
            line="Line A", farm_name="Yadav Farm", farm_capacity=5000)
        cls.customer = Customer.objects.create(code="C1", name="Ramesh Traders")
        cls.employee = Employee.objects.create(full_name="Akhilesh Kumar Pal")

    def sale(self, **kwargs):
        return BirdSale.objects.create(
            date=date(2026, 9, 13), sale_type="customer", customer=self.customer,
            farm=self.farm, birds=10, net_weight=Decimal("20"),
            rate=Decimal("100"), **kwargs)

    def test_a_name_can_be_written_where_no_employee_fits(self):
        sale = self.sale(lifting_supervisor_other="Ramesh (contractor)")
        self.assertIsNone(sale.lifting_supervisor_id)
        self.assertEqual(sale.lifting_supervisor_other, "Ramesh (contractor)")

    def test_the_register_shows_a_written_name_like_any_other(self):
        """Nothing reading this should need to know there are two columns."""
        sale = self.sale(lifting_supervisor_other="Ramesh (contractor)")
        self.assertEqual(_bird_sale_to_dict(sale)["lifting_supervisor_name"],
                         "Ramesh (contractor)")

    def test_the_register_still_shows_a_picked_employee(self):
        sale = self.sale(lifting_supervisor=self.employee)
        self.assertEqual(_bird_sale_to_dict(sale)["lifting_supervisor_name"],
                         str(self.employee))

    def test_a_sale_may_still_name_nobody(self):
        sale = self.sale()
        self.assertEqual(_bird_sale_to_dict(sale)["lifting_supervisor_name"], "")

    def test_the_form_offers_a_dropdown_and_a_way_off_it(self):
        """A dropdown, because the column is a list of employees and a name
        picked from it is not something to be typed over — plus the entry that
        reveals a box for a name the list does not have."""
        from django.contrib.auth import get_user_model
        from django.urls import reverse

        User = get_user_model()
        User.objects.create_superuser("ls_admin", "l@x.com", "Str0ngPass!")
        self.client.login(username="ls_admin", password="Str0ngPass!")
        html = self.client.get(reverse("bird_sale_add")).content.decode()
        self.assertIn('class="form-select form-select-sm lifting-supervisor"', html)
        self.assertIn("SUPERVISOR_OTHER", html)
        self.assertIn("lifting-supervisor-other", html)
