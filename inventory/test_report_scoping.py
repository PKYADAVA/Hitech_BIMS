"""Inventory reports read only the warehouses and farms the user is scoped to.

Two of the four were already right — Item Ledger and Stock Report resolve their
warehouse through ``warehouses_for``, so a warehouse named in the query string
that is outside the user's scope comes back as None. The other two were not:

* Stock Transfer Report ran an unscoped queryset.
* Item Summary Report asked the service for *every* storage location whenever
  no location was chosen, which is the page's default view.
"""
import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from broiler.models import Branch, BroilerFarm, Farmer, Region, Supervisor
from inventory.models import Item, ItemCategory, StockTransfer, Warehouse
from user.models import GroupAccessProfile, GroupTabPermission

MINE, THEIRS = "minestore", "farstore"


class InventoryReportScopingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.today = timezone.localdate()
        region = Region.objects.create(description="East")
        self.akbarpur = Branch.objects.create(branch_name="Akbarpur",
                                              region=region, prefix="AKB")
        self.bahraich = Branch.objects.create(branch_name="Bahraich",
                                              region=region, prefix="BHR")
        self.mine_wh = Warehouse.objects.create(name="Minestore")
        self.their_wh = Warehouse.objects.create(name="Farstore")

        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.mine_farm = self.farm("Mineglade", self.akbarpur, farmer, region)
        self.their_farm = self.farm("Farville", self.bahraich, farmer, region)

        self.item = Item.objects.create(
            description="Starter Feed",
            category=ItemCategory.objects.create(name="Feed"),
            valuation_method="Weighted Average", standard_cost_per_unit=30,
            usage="Produced", source="Purchased", type="Raw Material",
            item_account="Expense")

        # One movement into each warehouse, and one on out to each farm, so
        # both warehouses and both farms appear as storage locations.
        self.receive(self.mine_wh)
        self.receive(self.their_wh)
        self.issue(self.mine_wh, self.mine_farm)
        self.issue(self.their_wh, self.their_farm)

        User = get_user_model()
        self.user = User.objects.create_user("inv_user", "i@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Akbarpur Team")
        self.user.groups.add(self.group)
        for tab in ("stock_transfer_report", "item_summary_report",
                    "stock_report", "item_ledger_report"):
            GroupTabPermission.objects.create(group=self.group, tab_code=tab,
                                              can_view=True)
        self.client.force_login(self.user)

    def farm(self, name, branch, farmer, region):
        return BroilerFarm.objects.create(
            branch=branch, farmer=farmer, region=region, line="L1",
            supervisor=Supervisor.objects.create(branch=branch,
                                                 name="%s Sup" % name),
            farm_name=name, farm_capacity=5000)

    def receive(self, warehouse, quantity=500):
        return StockTransfer.objects.create(
            item=self.item, quantity=quantity, rate=30,
            date=self.today - timedelta(days=5),
            from_location_type="warehouse", to_location_type="warehouse",
            to_warehouse=warehouse)

    def issue(self, warehouse, farm, quantity=100):
        return StockTransfer.objects.create(
            item=self.item, quantity=quantity, rate=30,
            date=self.today - timedelta(days=2),
            from_location_type="warehouse", from_warehouse=warehouse,
            to_location_type="farm", to_farm=farm)

    def limit_to_akbarpur(self):
        profile = GroupAccessProfile.objects.create(
            group=self.group, access_type="sub_admin",
            all_branches=False, all_sectors=False, all_farms=False)
        profile.branches.add(self.akbarpur)
        profile.sectors.add(self.mine_wh)
        profile.farms.add(self.mine_farm)
        return profile

    def page(self, url_name, **params):
        return self.client.get(reverse(url_name), params).content.decode().lower()

    def rows(self, url_name, **params):
        html = self.page(url_name, **params)
        return "\n".join(re.findall(r"<tbody[^>]*>(.*?)</tbody>", html, re.S))

    # ---- stock transfer report ---------------------------------------------

    def test_the_transfer_register_is_scoped(self):
        self.limit_to_akbarpur()
        rows = self.rows("stock_transfer_report", submit="1")
        self.assertIn(MINE, rows)
        self.assertNotIn(THEIRS, rows)

    def test_naming_another_warehouse_does_not_widen_the_register(self):
        self.limit_to_akbarpur()
        rows = self.rows("stock_transfer_report", submit="1",
                         from_warehouse=str(self.their_wh.id))
        self.assertNotIn(THEIRS, rows)

    def test_a_transfer_out_of_the_users_warehouse_stays_visible(self):
        """Both ends count: stock leaving the store this user is responsible
        for, bound elsewhere, is the movement they most need to see."""
        self.limit_to_akbarpur()
        self.issue(self.mine_wh, self.their_farm)
        self.assertIn(MINE, self.rows("stock_transfer_report", submit="1"))

    def test_an_unscoped_user_still_reads_every_transfer(self):
        rows = self.rows("stock_transfer_report", submit="1")
        self.assertIn(MINE, rows)
        self.assertIn(THEIRS, rows)

    # ---- item summary report ------------------------------------------------

    def test_the_summary_defaults_to_only_the_users_locations(self):
        """No location chosen is the page's default, and it used to mean every
        warehouse and farm in the company."""
        self.limit_to_akbarpur()
        rows = self.rows("item_summary_report", submit="1")
        self.assertIn(MINE, rows)
        self.assertNotIn(THEIRS, rows)

    def test_the_summary_hides_farms_outside_the_scope(self):
        self.limit_to_akbarpur()
        self.assertNotIn("farville", self.rows("item_summary_report", submit="1"))

    def test_naming_another_location_does_not_widen_the_summary(self):
        self.limit_to_akbarpur()
        rows = self.rows("item_summary_report", submit="1",
                         location="warehouse:%d" % self.their_wh.id)
        self.assertNotIn(THEIRS, rows)

    def test_an_unscoped_user_still_sees_every_location(self):
        rows = self.rows("item_summary_report", submit="1")
        self.assertIn(MINE, rows)
        self.assertIn(THEIRS, rows)

    # ---- the two that were already right ------------------------------------

    def test_the_stock_report_refuses_a_warehouse_outside_the_scope(self):
        self.limit_to_akbarpur()
        self.assertNotIn(THEIRS, self.page("stock_report",
                                           warehouse=str(self.their_wh.id)))

    def test_the_item_ledger_refuses_a_warehouse_outside_the_scope(self):
        self.limit_to_akbarpur()
        self.assertNotIn(THEIRS, self.page("item_ledger_report",
                                           item=str(self.item.id),
                                           warehouse=str(self.their_wh.id)))
