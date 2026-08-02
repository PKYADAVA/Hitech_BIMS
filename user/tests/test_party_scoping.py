"""Customers and suppliers are scoped too, not only branches and warehouses.

The branch/warehouse dimensions had been carried through most reports, but the
party dimensions had not: the debit/credit note registers (four pages sharing
two helpers) served every party's notes, the Supplier master listed everyone
while the Customer master beside it was already scoped, and party pickers
across broiler, hatchery, tracking and notification offered the full list.

A picker is not a cosmetic leak — the names themselves are the disclosure, and
an out-of-scope party that can be selected is one that can be transacted with.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from purchase.models import CreditNote, DebitNote, Supplier, VendorGroup
from sales.models import (Customer, CustomerCreditNote, CustomerDebitNote,
                          CustomerGroup)
from user.models import GroupAccessProfile, GroupTabPermission


class PartyScopingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.today = timezone.localdate()

        self.mine_cg = CustomerGroup.objects.create(code="CG1", description="Retail")
        self.their_cg = CustomerGroup.objects.create(code="CG2", description="Export")
        self.mine_vg = VendorGroup.objects.create(code="VG1", description="Feedmills")
        self.their_vg = VendorGroup.objects.create(code="VG2", description="Hauliers")

        self.mine_cust = self.customer("Mineglade Traders", self.mine_cg, "9000000001")
        self.their_cust = self.customer("Farville Exports", self.their_cg, "9000000002")
        self.mine_supp = self.supplier("Mineglade Feeds", "Feedmills")
        self.their_supp = self.supplier("Farville Hauling", "Hauliers")

        for model, customer in ((CustomerDebitNote, self.mine_cust),
                                (CustomerDebitNote, self.their_cust),
                                (CustomerCreditNote, self.mine_cust),
                                (CustomerCreditNote, self.their_cust)):
            model.objects.create(customer=customer, date=self.today, amount=100)
        for model, supplier in ((DebitNote, self.mine_supp),
                                (DebitNote, self.their_supp),
                                (CreditNote, self.mine_supp),
                                (CreditNote, self.their_supp)):
            model.objects.create(supplier=supplier, date=self.today, amount=100)

        User = get_user_model()
        self.user = User.objects.create_user("pty_user", "p@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Retail Team")
        self.user.groups.add(self.group)
        for tab in ("customer_debit_note_list", "customer_credit_note_list",
                    "debit_note_list", "credit_note_list", "supplier",
                    "customer"):
            GroupTabPermission.objects.get_or_create(
                group=self.group, tab_code=tab, defaults={"can_view": True})
        self.client.force_login(self.user)

    def customer(self, name, group, mobile):
        return Customer.objects.create(
            name=name, address="x", mobile=mobile, contact_type="Customer",
            party_category="Company", customer_group=group, credit_limit=0,
            state="Uttar Pradesh")

    def supplier(self, name, group):
        return Supplier.objects.create(name=name, party_category="Company",
                                       credit_limit=0, supplier_group=group)

    def limit_to_mine(self):
        """Scoped to one customer group and one vendor group."""
        profile = GroupAccessProfile.objects.create(
            group=self.group, access_type="sub_admin",
            all_customer_groups=False, all_supplier_groups=False)
        profile.customer_groups.add(self.mine_cg)
        profile.supplier_groups.add(self.mine_vg)
        return profile

    def json_at(self, url_name, **params):
        return self.client.get(reverse(url_name), params).json()

    # ---- the four note registers -------------------------------------------

    def test_the_customer_note_registers_are_scoped(self):
        self.limit_to_mine()
        for url_name in ("customer_debit_note_api_list",
                         "customer_credit_note_api_list"):
            with self.subTest(page=url_name):
                names = {row.get("customer_name") for row in self.json_at(url_name)}
                self.assertIn("Mineglade Traders", names)
                self.assertNotIn("Farville Exports", names)

    def test_the_supplier_note_registers_are_scoped(self):
        self.limit_to_mine()
        for url_name in ("debit_note_api_list", "credit_note_api_list"):
            with self.subTest(page=url_name):
                names = {row.get("supplier_name") for row in self.json_at(url_name)}
                self.assertIn("Mineglade Feeds", names)
                self.assertNotIn("Farville Hauling", names)

    def test_a_note_whose_party_has_no_group_is_kept(self):
        """An unfiled party is not evidence of a denial, and dropping its rows
        would change a register's totals rather than restrict access."""
        orphan = self.supplier("Unfiled Supplies", None)
        DebitNote.objects.create(supplier=orphan, date=self.today, amount=50)
        self.limit_to_mine()
        names = {row.get("supplier_name") for row in self.json_at("debit_note_api_list")}
        self.assertIn("Unfiled Supplies", names)

    def test_an_unscoped_user_still_reads_every_note(self):
        names = {row.get("customer_name")
                 for row in self.json_at("customer_debit_note_api_list")}
        self.assertIn("Mineglade Traders", names)
        self.assertIn("Farville Exports", names)

    # ---- the masters --------------------------------------------------------

    def test_the_supplier_master_is_scoped_like_the_customer_master(self):
        """The Customer master was already scoped; the Supplier master beside
        it listed everyone."""
        self.limit_to_mine()
        html = self.client.get(reverse("supplier")).content.decode()
        self.assertIn("Mineglade Feeds", html)
        self.assertNotIn("Farville Hauling", html)

    def test_the_customer_master_stays_scoped(self):
        self.limit_to_mine()
        html = self.client.get(reverse("customer")).content.decode()
        self.assertIn("Mineglade Traders", html)
        self.assertNotIn("Farville Exports", html)
