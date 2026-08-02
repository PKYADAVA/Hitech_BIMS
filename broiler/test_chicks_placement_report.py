"""Chicks Placement Report — the warehouse filter, and who may read the rows.

The report's option lists were already narrowed to the signed-in user's scope,
but the register itself was not. A user limited to one branch only had to leave
the filters on "All" — the default — to read every branch's placements. The
existing scoping test rendered the page with no filters applied, so it saw the
dropdowns and never a single row, and the gap stayed invisible.
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


class ChicksPlacementReportTests(TestCase):
    def setUp(self):
        cache.clear()
        self.today = timezone.localdate()
        region = Region.objects.create(description="East")

        self.akbarpur = Branch.objects.create(branch_name="Akbarpur",
                                              region=region, prefix="AKB")
        self.bahraich = Branch.objects.create(branch_name="Bahraich",
                                              region=region, prefix="BHR")
        self.wh_akbarpur = Warehouse.objects.create(name="Akbarpur Store")
        self.wh_bahraich = Warehouse.objects.create(name="Bahraich Store")

        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.mine = self.farm("MineFarm", self.akbarpur, farmer, region)
        self.theirs = self.farm("TheirFarm", self.bahraich, farmer, region)

        self.chick = Item.objects.create(
            description="Day Old Chicks",
            category=ItemCategory.objects.create(name="Chicks"),
            valuation_method="Weighted Average", standard_cost_per_unit=40,
            usage="Produced", source="Purchased", type="Raw Material",
            item_account="Expense")

        self.place(self.mine, self.wh_akbarpur)
        self.place(self.theirs, self.wh_bahraich)

        User = get_user_model()
        self.user = User.objects.create_user("cpr_user", "c@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Akbarpur Team")
        self.user.groups.add(self.group)
        GroupTabPermission.objects.create(group=self.group,
                                          tab_code="chicks_placement_report",
                                          can_view=True)
        self.client.force_login(self.user)

    def farm(self, name, branch, farmer, region):
        return BroilerFarm.objects.create(
            branch=branch, farmer=farmer, region=region, line="L1",
            supervisor=Supervisor.objects.create(branch=branch, name=name[:8]),
            farm_name=name, farm_capacity=5000)

    def place(self, farm, warehouse, days_ago=3, quantity=1000):
        return StockTransfer.objects.create(
            item=self.chick, quantity=quantity,
            date=self.today - timedelta(days=days_ago),
            from_location_type="warehouse", from_warehouse=warehouse,
            to_location_type="farm", to_farm=farm)

    def limit_to_akbarpur(self):
        profile = GroupAccessProfile.objects.create(
            group=self.group, access_type="sub_admin",
            all_branches=False, all_sectors=False, all_farms=False)
        profile.branches.add(self.akbarpur)
        profile.sectors.add(self.wh_akbarpur)
        profile.farms.add(self.mine)
        return profile

    def report(self, **params):
        params.setdefault("submit", "1")
        return self.client.get(reverse("chicks_placement_report"),
                               params).content.decode()

    def register(self, **params):
        """Just the table body.

        The farm and supervisor dropdowns name every farm the *user* may pick,
        so searching the whole page for a farm name answers a question about
        the filter bar, not about which rows were returned.
        """
        html = self.report(**params)
        body = re.search(r"<tbody>(.*?)</tbody>", html, re.S)
        return body.group(1) if body else ""

    # ---- the warehouse filter ---------------------------------------------

    def test_the_filter_bar_offers_a_warehouse(self):
        html = self.client.get(reverse("chicks_placement_report")).content.decode()
        self.assertIn('name="warehouse"', html)
        self.assertIn("Akbarpur Store", html)

    def test_choosing_a_warehouse_narrows_the_register(self):
        rows = self.register(warehouse=str(self.wh_akbarpur.id))
        self.assertIn("MineFarm", rows)
        self.assertNotIn("TheirFarm", rows)

    def test_the_warehouse_options_are_scoped_to_the_user(self):
        self.limit_to_akbarpur()
        html = self.client.get(reverse("chicks_placement_report")).content.decode()
        self.assertIn("Akbarpur Store", html)
        self.assertNotIn("Bahraich Store", html)

    def test_no_warehouse_chosen_still_returns_every_row(self):
        """The filter is optional; adding it must not silently narrow the
        default view."""
        rows = self.register()
        self.assertIn("MineFarm", rows)
        self.assertIn("TheirFarm", rows)

    # ---- the rows, not just the dropdowns ----------------------------------

    def test_a_branch_limited_user_reading_all_sees_only_their_own(self):
        """The reported shape: leave every filter on "All" and the register
        used to answer with the whole company."""
        self.limit_to_akbarpur()
        rows = self.register()
        self.assertIn("MineFarm", rows)
        self.assertNotIn("TheirFarm", rows)

    def test_naming_another_branch_in_the_url_does_not_widen_it(self):
        """The dropdown will not offer Bahraich, but the query string is not a
        dropdown."""
        self.limit_to_akbarpur()
        self.assertNotIn("TheirFarm",
                         self.register(branch=str(self.bahraich.id)))

    def test_naming_another_warehouse_in_the_url_does_not_widen_it(self):
        self.limit_to_akbarpur()
        self.assertNotIn("TheirFarm",
                         self.register(warehouse=str(self.wh_bahraich.id)))

    def test_an_unscoped_user_still_reads_everything(self):
        """Fail-open: a group with no access profile is unrestricted, so adding
        scoping cannot break an account that worked yesterday."""
        rows = self.register()
        self.assertIn("MineFarm", rows)
        self.assertIn("TheirFarm", rows)

    def test_a_placement_out_of_the_users_warehouse_stays_visible(self):
        """A transfer has two ends. Chicks leaving the store this user is
        responsible for, bound for someone else's farm, is exactly the movement
        they need to see — hiding it would make their own stock read wrong
        rather than restricted.
        """
        self.limit_to_akbarpur()
        self.place(self.theirs, self.wh_akbarpur, days_ago=2)
        self.assertIn("TheirFarm", self.register())
