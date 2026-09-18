"""Growing Charges list: the Branch filter and the Year options.

The list filtered by date alone, so one branch's settlements in a busy month
meant reading past every other branch's. The page now sends ?branch= like the
other registers, and offers years from the first settlement to this one.
"""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from broiler.models import (Branch, BroilerBatch, BroilerFarm, Farmer,
                            GrowingChargeSettlement, Region, Supervisor)


class GCListFilterTests(TestCase):

    def setUp(self):
        region = Region.objects.create(description="East")
        self.akbarpur = Branch.objects.create(branch_name="Akbarpur", region=region, prefix="AKB")
        self.basti = Branch.objects.create(branch_name="Basti", region=region, prefix="BST")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.gc_date = date(2024, 3, 15)
        for branch, name in ((self.akbarpur, "Green Valley Farm"), (self.basti, "Maa Durga Farm")):
            farm = BroilerFarm.objects.create(
                branch=branch, supervisor=Supervisor.objects.create(branch=branch, name="R. Verma"),
                farmer=farmer, region="East", line="L1", farm_name=name, farm_capacity=9000)
            batch = BroilerBatch.objects.create(broiler_farm=farm,
                                                start_date=self.gc_date - timedelta(days=40))
            GrowingChargeSettlement.objects.create(batch=batch, farm=farm, gc_date=self.gc_date)
        self.client.force_login(get_user_model().objects.create_superuser(
            "gcadmin", "g@x.com", "Str0ngPass!"))

    def farms(self, **params):
        rows = self.client.get("/gc_settlement_list/", params).json()
        return sorted(r["farm_name"] for r in rows)

    def test_no_branch_lists_every_branch(self):
        self.assertEqual(self.farms(), ["Green Valley Farm", "Maa Durga Farm"])

    def test_a_branch_lists_only_its_own_settlements(self):
        self.assertEqual(self.farms(branch=self.basti.id), ["Maa Durga Farm"])

    def test_branch_combines_with_the_dates(self):
        self.assertEqual(self.farms(branch=self.akbarpur.id,
                                    from_date="2024-03-01", to_date="2024-03-31"),
                         ["Green Valley Farm"])
        self.assertEqual(self.farms(branch=self.akbarpur.id,
                                    from_date="2024-04-01", to_date="2024-04-30"), [])

    def test_the_page_offers_branches_and_years_from_the_first_settlement(self):
        html = self.client.get("/gc-settlement/").content.decode()
        self.assertIn('id="flt-branch"', html)
        self.assertIn(">Basti</option>", html)
        this_year = timezone.localdate().year
        for year in range(2024, this_year + 1):
            self.assertIn('<option value="%d">%d</option>' % (year, year), html)
        self.assertNotIn('<option value="2023">', html)
