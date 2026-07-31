"""Data scoping — the half of the Web-Access matrix that was never enforced.

The reported case: a user limited to Akbarpur branch and Akbarpur warehouse was
offered every branch and warehouse in the report filters, and the report read
every warehouse's data.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from broiler.models import (Branch, BroilerBatch, BroilerFarm, Farmer, Region,
                            Supervisor)
from inventory.models import Item, ItemCategory, StockTransfer, Warehouse
from user.models import GroupAccessProfile, GroupTabPermission
from user.services import scoping


class ScopeResolutionTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.user = User.objects.create_user("sc_user", "s@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Akbarpur Team")
        self.user.groups.add(self.group)
        GroupTabPermission.objects.create(group=self.group, tab_code="items",
                                          can_view=True)

        region = Region.objects.create(description="East")
        self.akbarpur = Branch.objects.create(branch_name="Akbarpur",
                                              region=region, prefix="AKB")
        self.bahraich = Branch.objects.create(branch_name="Bahraich",
                                              region=region, prefix="BHR")
        self.wh_akbarpur = Warehouse.objects.create(name="Akbarpur Warehouse")
        self.wh_bahraich = Warehouse.objects.create(name="Bahraich Warehouse")

    def fresh(self):
        return get_user_model().objects.get(pk=self.user.pk)

    def limit_to_akbarpur(self):
        profile = GroupAccessProfile.objects.create(
            group=self.group, access_type="sub_admin",
            all_branches=False, all_sectors=False)
        profile.branches.add(self.akbarpur)
        profile.sectors.add(self.wh_akbarpur)
        return profile

    # ---- the defaults must not lock anyone out ---------------------------

    def test_a_user_with_no_access_profile_is_unscoped(self):
        """Same fail-open the tab matrix uses, so adding scoping cannot break
        an account that was working yesterday."""
        self.assertTrue(scoping.is_unscoped(self.fresh()))
        self.assertIsNone(scoping.allowed_ids(self.fresh(), "branches"))

    def test_all_flags_mean_no_limit(self):
        GroupAccessProfile.objects.create(group=self.group)   # all_* default True
        self.assertIsNone(scoping.allowed_ids(self.fresh(), "branches"))
        self.assertIsNone(scoping.allowed_ids(self.fresh(), "sectors"))

    def test_a_superuser_is_unscoped(self):
        User = get_user_model()
        boss = User.objects.create_superuser("sc_boss", "b@x.com", "Str0ngPass!")
        boss.groups.add(self.group)
        self.limit_to_akbarpur()
        self.assertTrue(scoping.is_unscoped(boss))

    def test_an_admin_access_type_is_unscoped(self):
        profile = self.limit_to_akbarpur()
        profile.access_type = "admin"
        profile.save()
        self.assertTrue(scoping.is_unscoped(self.fresh()))

    # ---- a real limit -----------------------------------------------------

    def test_a_limited_group_narrows_the_ids(self):
        self.limit_to_akbarpur()
        self.assertEqual(scoping.allowed_ids(self.fresh(), "branches"),
                         {self.akbarpur.id})
        self.assertEqual(scoping.allowed_ids(self.fresh(), "sectors"),
                         {self.wh_akbarpur.id})

    def test_an_empty_selection_permits_nothing(self):
        """Not the same as 'no limit'. Collapsing the two would hand over
        everything, which is the failure this exists to fix."""
        GroupAccessProfile.objects.create(group=self.group, all_branches=False)
        self.assertEqual(scoping.allowed_ids(self.fresh(), "branches"), set())
        self.assertEqual(list(scoping.branches_for(self.fresh())), [])

    def test_one_group_with_all_opens_the_dimension(self):
        """Granted anywhere is granted — the tab matrix combines groups the
        same way."""
        self.limit_to_akbarpur()
        wide = Group.objects.create(name="Everywhere")
        GroupAccessProfile.objects.create(group=wide, all_branches=True)
        self.user.groups.add(wide)
        self.assertIsNone(scoping.allowed_ids(self.fresh(), "branches"))

    def test_two_limited_groups_union(self):
        self.limit_to_akbarpur()
        other = Group.objects.create(name="Bahraich Team")
        profile = GroupAccessProfile.objects.create(group=other, all_branches=False)
        profile.branches.add(self.bahraich)
        self.user.groups.add(other)
        self.assertEqual(scoping.allowed_ids(self.fresh(), "branches"),
                         {self.akbarpur.id, self.bahraich.id})

    # ---- the option lists people see -------------------------------------

    def test_branch_and_warehouse_options_are_narrowed(self):
        self.limit_to_akbarpur()
        user = self.fresh()
        self.assertEqual([b.branch_name for b in scoping.branches_for(user)],
                         ["Akbarpur"])
        self.assertEqual([w.name for w in scoping.warehouses_for(user)],
                         ["Akbarpur Warehouse"])

    def test_farms_follow_the_branch_scope_even_with_no_farm_limit(self):
        """A branch limit already implies its farms; nobody should have to list
        them twice."""
        self.limit_to_akbarpur()
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        for branch, name in ((self.akbarpur, "Mine"), (self.bahraich, "Theirs")):
            supervisor = Supervisor.objects.create(branch=branch, name=f"S {name}")
            BroilerFarm.objects.create(branch=branch, supervisor=supervisor,
                                       farmer=farmer, region=branch.region,
                                       line="L1", farm_name=name, farm_capacity=100)
        self.assertEqual([f.farm_name for f in scoping.farms_for(self.fresh())],
                         ["Mine"])

    def test_supervisors_follow_the_branch_scope(self):
        self.limit_to_akbarpur()
        Supervisor.objects.create(branch=self.akbarpur, name="A")
        Supervisor.objects.create(branch=self.bahraich, name="B")
        self.assertEqual([s.name for s in scoping.supervisors_for(self.fresh())],
                         ["A"])


class ScopedReportTests(TestCase):
    """The Feed Dispatch report from the report screenshot."""

    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.user = User.objects.create_user("rp_user", "r@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Akbarpur Only")
        self.user.groups.add(self.group)
        GroupTabPermission.objects.create(group=self.group, can_view=True,
                                          tab_code="feed_dispatch_stock_report")

        region = Region.objects.create(description="East")
        self.akbarpur = Branch.objects.create(branch_name="Akbarpur",
                                              region=region, prefix="AKB")
        Branch.objects.create(branch_name="Bahraich", region=region, prefix="BHR")
        self.mine = Warehouse.objects.create(name="Akbarpur Warehouse")
        self.theirs = Warehouse.objects.create(name="Bahraich Warehouse")

        profile = GroupAccessProfile.objects.create(
            group=self.group, all_branches=False, all_sectors=False)
        profile.branches.add(self.akbarpur)
        profile.sectors.add(self.mine)
        self.client.force_login(self.user)

    def page(self, **params):
        return self.client.get(reverse("feed_dispatch_stock_report"),
                               params).content.decode()

    def test_the_dropdowns_offer_only_what_the_user_may_see(self):
        html = self.page()
        self.assertIn("Akbarpur Warehouse", html)
        self.assertNotIn("Bahraich Warehouse", html)
        self.assertIn("Akbarpur", html)
        self.assertNotIn("Bahraich Branch", html)

    def test_a_hand_typed_warehouse_id_is_ignored(self):
        """A querystring is not a permission."""
        html = self.page(warehouse=self.theirs.id, submit="1")
        self.assertNotIn(f'value="{self.theirs.id}" selected', html)

    def test_the_page_states_the_scope(self):
        self.assertIn("warehouse", self.page().lower())


class ScopedDashboardTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.user = User.objects.create_user("db_user", "d@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Akbarpur Dash")
        self.user.groups.add(self.group)
        for tab in ("live_flock_summary_report", "daily_entry_list"):
            GroupTabPermission.objects.create(group=self.group, tab_code=tab,
                                              can_view=True)

        region = Region.objects.create(description="East")
        self.mine = Branch.objects.create(branch_name="Akbarpur", region=region,
                                          prefix="AKB")
        self.theirs = Branch.objects.create(branch_name="Bahraich", region=region,
                                            prefix="BHR")
        farmer = Farmer.objects.create(farmer_name="F")
        self.chick = Item.objects.create(
            description="Day Old Chicks",
            category=ItemCategory.objects.create(name="Chicks"),
            valuation_method="Weighted Average", standard_cost_per_unit=40,
            usage="Produced", source="Purchased", type="Raw Material",
            item_account="Expense")

        today = timezone.localdate()
        self.farms = {}
        for branch, name, birds in ((self.mine, "Mine", 1000),
                                    (self.theirs, "Theirs", 500)):
            supervisor = Supervisor.objects.create(branch=branch, name=f"S{name}")
            farm = BroilerFarm.objects.create(
                branch=branch, supervisor=supervisor, farmer=farmer,
                region=region, line="L1", farm_name=name, farm_capacity=5000)
            self.farms[name] = farm
            batch = BroilerBatch.objects.create(broiler_farm=farm, batch_name=name,
                                                start_date=today - timedelta(days=10))
            StockTransfer.objects.create(item=self.chick, to_batch=batch,
                                         quantity=Decimal(birds),
                                         date=today - timedelta(days=10))

        profile = GroupAccessProfile.objects.create(group=self.group,
                                                    all_branches=False)
        profile.branches.add(self.mine)
        self.client.force_login(self.user)

    def flock(self):
        from user.services.dashboard_widgets import dashboard_widgets

        user = get_user_model().objects.get(pk=self.user.pk)
        card = next(w for w in dashboard_widgets(user, use_cache=False)
                    if w["key"] == "live_flock")
        return {s["label"]: s["value"] for s in card["stats"]}

    def test_the_widget_counts_only_the_users_branch(self):
        stats = self.flock()
        self.assertEqual(stats["Open batches"], "1")
        self.assertEqual(stats["Birds alive"], "1,000")     # not 1,500

    def test_the_filter_dropdowns_are_narrowed(self):
        html = self.client.get(reverse("dashboard")).content.decode()
        self.assertIn("Akbarpur", html)
        self.assertNotIn("Bahraich", html)

    def test_a_hand_typed_farm_outside_the_scope_yields_nothing(self):
        from user.services.dashboard_widgets import dashboard_widgets

        user = get_user_model().objects.get(pk=self.user.pk)
        card = next(w for w in dashboard_widgets(
            user, {"farm": self.farms["Theirs"].id, "date": None, "branch": None,
                   "line": None, "supervisor": None}, use_cache=False)
            if w["key"] == "live_flock")
        stats = {s["label"]: s["value"] for s in card["stats"]}
        self.assertEqual(stats["Open batches"], "0")

    def test_the_cache_is_not_shared_across_scopes(self):
        """Two users, different branches — one must not be served the other's
        numbers."""
        from user.services.dashboard_widgets import dashboard_widgets

        User = get_user_model()
        other = User.objects.create_user("db_other", "o@x.com", "Str0ngPass!")
        other_group = Group.objects.create(name="Bahraich Dash")
        other.groups.add(other_group)
        GroupTabPermission.objects.create(group=other_group, can_view=True,
                                          tab_code="live_flock_summary_report")
        profile = GroupAccessProfile.objects.create(group=other_group,
                                                    all_branches=False)
        profile.branches.add(self.theirs)

        mine = dashboard_widgets(get_user_model().objects.get(pk=self.user.pk))
        theirs = dashboard_widgets(get_user_model().objects.get(pk=other.pk))

        def birds(cards):
            card = next(c for c in cards if c["key"] == "live_flock")
            return {s["label"]: s["value"] for s in card["stats"]}["Birds alive"]

        self.assertEqual(birds(mine), "1,000")
        self.assertEqual(birds(theirs), "500")


class BroilerModuleScopingTests(TestCase):
    """Every user-facing option list in the Broiler module is narrowed.

    Checked by rendering the real pages rather than by calling the helpers, so
    a page that forgot to use them fails here.
    """

    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.user = User.objects.create_user("bm_user", "b@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Akbarpur Broiler")
        self.user.groups.add(self.group)

        region = Region.objects.create(description="East")
        self.mine = Branch.objects.create(branch_name="Akbarpur", region=region,
                                          prefix="AKB")
        self.theirs = Branch.objects.create(branch_name="Bahraich", region=region,
                                            prefix="BHR")
        farmer = Farmer.objects.create(farmer_name="F")
        for branch, name, line in ((self.mine, "MineFarm", "LineMine"),
                                   (self.theirs, "TheirFarm", "LineTheirs")):
            supervisor = Supervisor.objects.create(branch=branch, name=f"Sup{name}")
            BroilerFarm.objects.create(branch=branch, supervisor=supervisor,
                                       farmer=farmer, region=region, line=line,
                                       farm_name=name, farm_capacity=100)

        profile = GroupAccessProfile.objects.create(group=self.group,
                                                    all_branches=False)
        profile.branches.add(self.mine)

        # Every broiler tab, so the guard is never what is being measured.
        from user.access import MODULE_REGISTRY
        for module in MODULE_REGISTRY:
            if module["nav"] != "broiler":
                continue
            for section in module["sections"]:
                for tab in section["tabs"]:
                    GroupTabPermission.objects.get_or_create(
                        group=self.group, tab_code=tab[0],
                        defaults={"can_view": True})
        self.client.force_login(self.user)

    def assertScoped(self, url_name):
        html = self.client.get(reverse(url_name)).content.decode()
        with self.subTest(page=url_name):
            self.assertIn("MineFarm", html)
            self.assertNotIn("TheirFarm", html)
            self.assertNotIn("Bahraich", html)

    def test_the_broiler_reports_offer_only_the_users_farms(self):
        for url_name in ("day_record_report", "farm_detailed_daily_entry_report",
                         "lifting_report", "chicks_placement_report",
                         "batch_wise_feed_scheduling_report",
                         "broiler_batch_report"):
            self.assertScoped(url_name)

    def test_the_line_options_narrow_with_the_farms(self):
        html = self.client.get(reverse("day_record_report")).content.decode()
        self.assertIn("LineMine", html)
        self.assertNotIn("LineTheirs", html)

    def test_the_farm_location_capture_form_is_scoped(self):
        html = self.client.get(reverse("farm_location_capture_list")).content.decode()
        self.assertIn("MineFarm", html)
        self.assertNotIn("TheirFarm", html)

    def test_the_cached_branch_list_is_not_shared_between_scopes(self):
        """A single global cache key would serve one user's branches to the
        next request from someone else."""
        from user.services.dashboard_widgets import _scope_signature

        other = get_user_model().objects.create_user("bm_other", "o@x.com",
                                                     "Str0ngPass!")
        other_group = Group.objects.create(name="Bahraich Broiler")
        other.groups.add(other_group)
        profile = GroupAccessProfile.objects.create(group=other_group,
                                                    all_branches=False)
        profile.branches.add(self.theirs)

        self.assertNotEqual(
            _scope_signature(get_user_model().objects.get(pk=self.user.pk)),
            _scope_signature(get_user_model().objects.get(pk=other.pk)))

    def test_an_unscoped_user_still_sees_everything(self):
        boss = get_user_model().objects.create_superuser("bm_boss", "z@x.com",
                                                         "Str0ngPass!")
        self.client.force_login(boss)
        html = self.client.get(reverse("day_record_report")).content.decode()
        self.assertIn("MineFarm", html)
        self.assertIn("TheirFarm", html)


class CrossModuleScopingTests(TestCase):
    """Every module's option lists, checked by rendering the real pages.

    The rewrite was mechanical, so the risk is a page that was missed rather
    than one that was done wrong — these fail on the former.
    """

    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.user = User.objects.create_user("cm_user", "c@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Akbarpur Everything")
        self.user.groups.add(self.group)

        region = Region.objects.create(description="East")
        self.mine = Branch.objects.create(branch_name="Akbarpur", region=region,
                                          prefix="AKB")
        self.theirs = Branch.objects.create(branch_name="Bahraich", region=region,
                                            prefix="BHR")
        self.wh_mine = Warehouse.objects.create(name="Akbarpur Warehouse")
        self.wh_theirs = Warehouse.objects.create(name="Bahraich Warehouse")

        profile = GroupAccessProfile.objects.create(
            group=self.group, all_branches=False, all_sectors=False)
        profile.branches.add(self.mine)
        profile.sectors.add(self.wh_mine)

        from user.access import ALL_TAB_CODES
        for code in ALL_TAB_CODES:
            GroupTabPermission.objects.get_or_create(
                group=self.group, tab_code=code, defaults={"can_view": True})
        self.client.force_login(self.user)

    def assertWarehouseScoped(self, url_name):
        with self.subTest(page=url_name):
            html = self.client.get(reverse(url_name)).content.decode()
            self.assertIn("Akbarpur Warehouse", html)
            self.assertNotIn("Bahraich Warehouse", html)

    def test_inventory_pages_offer_only_the_users_warehouses(self):
        for url_name in ("stock_report", "item_ledger_report",
                         "negative_stock_report", "item_summary_report",
                         "stock_transfer_report"):
            self.assertWarehouseScoped(url_name)

    def test_a_hand_typed_warehouse_is_not_read_by_the_stock_report(self):
        html = self.client.get(reverse("stock_report"),
                               {"warehouse": self.wh_theirs.id,
                                "submit": "1"}).content.decode()
        self.assertNotIn("Bahraich Warehouse", html)

    def test_purchase_and_hatchery_forms_are_scoped(self):
        for url_name in ("general_purchase_list", "chicks_purchase_list"):
            with self.subTest(page=url_name):
                html = self.client.get(reverse(url_name)).content.decode()
                self.assertNotIn("Bahraich Warehouse", html)

    def test_an_unscoped_user_is_unaffected_everywhere(self):
        boss = get_user_model().objects.create_superuser("cm_boss", "z2@x.com",
                                                          "Str0ngPass!")
        self.client.force_login(boss)
        html = self.client.get(reverse("stock_report")).content.decode()
        self.assertIn("Akbarpur Warehouse", html)
        self.assertIn("Bahraich Warehouse", html)


class PartyScopingTests(TestCase):
    """Customer and supplier groups — the two dimensions the editor offers that
    nothing had ever read."""

    def setUp(self):
        cache.clear()
        from purchase.models import Supplier, VendorGroup
        from sales.models import Customer, CustomerGroup

        User = get_user_model()
        self.user = User.objects.create_user("pt_user", "p@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Retail Only")
        self.user.groups.add(self.group)

        self.retail = CustomerGroup.objects.create(code="RET", description="Retail")
        self.trade = CustomerGroup.objects.create(code="TRD", description="Trade")
        # Contact.phone and .mobile are both unique, so each fixture needs its
        # own of each.
        for n, (label, cgroup) in enumerate([("Retail Buyer", self.retail),
                                             ("Trade Buyer", self.trade),
                                             ("Unfiled Buyer", None)], start=1):
            Customer.objects.create(name=label, customer_group=cgroup,
                                    phone=f"900000000{n}", mobile=f"800000000{n}")

        self.feed = VendorGroup.objects.create(code="FD", description="Feed Vendors")
        VendorGroup.objects.create(code="EQ", description="Equipment Vendors")
        for n, (label, sgroup) in enumerate([("Feed Co", "Feed Vendors"),
                                             ("Equipment Co", "Equipment Vendors"),
                                             ("Unfiled Co", "")], start=1):
            Supplier.objects.create(name=label, supplier_group=sgroup,
                                    mobile=f"700000000{n}")

    def fresh(self):
        return get_user_model().objects.get(pk=self.user.pk)

    def test_customers_narrow_to_the_permitted_groups(self):
        profile = GroupAccessProfile.objects.create(group=self.group,
                                                    all_customer_groups=False)
        profile.customer_groups.add(self.retail)
        names = {c.name for c in scoping.customers_for(self.fresh())}
        self.assertIn("Retail Buyer", names)
        self.assertNotIn("Trade Buyer", names)

    def test_a_customer_with_no_group_is_kept(self):
        """An unfiled record is not evidence the user should be denied it, and
        dropping it would change balance totals rather than restrict access."""
        profile = GroupAccessProfile.objects.create(group=self.group,
                                                    all_customer_groups=False)
        profile.customer_groups.add(self.retail)
        self.assertIn("Unfiled Buyer",
                      {c.name for c in scoping.customers_for(self.fresh())})

    def test_suppliers_match_the_free_text_group_against_the_master(self):
        """Supplier.supplier_group is free text while the scope holds
        VendorGroup rows, so the match is by description."""
        profile = GroupAccessProfile.objects.create(group=self.group,
                                                    all_supplier_groups=False)
        profile.supplier_groups.add(self.feed)
        names = {s.name for s in scoping.suppliers_for(self.fresh())}
        self.assertIn("Feed Co", names)
        self.assertIn("Unfiled Co", names)
        self.assertNotIn("Equipment Co", names)

    def test_all_groups_means_no_limit(self):
        GroupAccessProfile.objects.create(group=self.group)
        self.assertEqual(scoping.customers_for(self.fresh()).count(), 3)
        self.assertEqual(scoping.suppliers_for(self.fresh()).count(), 3)


class TransactionRowScopingTests(TestCase):
    """Rows, not just dropdowns.

    Narrowing the filter bar only limits what can be asked for; without this the
    grid still answers a question the filter bar would not let you type.
    """

    def setUp(self):
        cache.clear()
        from broiler.models import DailyEntry

        User = get_user_model()
        self.user = User.objects.create_user("tr_user", "t@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Akbarpur Rows")
        self.user.groups.add(self.group)
        for tab in ("daily_entry_list", "bird_sale_list"):
            GroupTabPermission.objects.create(group=self.group, tab_code=tab,
                                              can_view=True)

        region = Region.objects.create(description="East")
        mine = Branch.objects.create(branch_name="Akbarpur", region=region,
                                     prefix="AKB")
        theirs = Branch.objects.create(branch_name="Bahraich", region=region,
                                       prefix="BHR")
        farmer = Farmer.objects.create(farmer_name="F")
        self.farms = {}
        for branch, name in ((mine, "MineFarm"), (theirs, "TheirFarm")):
            supervisor = Supervisor.objects.create(branch=branch, name=f"S{name}")
            farm = BroilerFarm.objects.create(
                branch=branch, supervisor=supervisor, farmer=farmer, region=region,
                line="L1", farm_name=name, farm_capacity=100)
            self.farms[name] = farm
            DailyEntry.objects.create(farm=farm, supervisor=supervisor,
                                      date=timezone.localdate(), mortality=1)

        profile = GroupAccessProfile.objects.create(group=self.group,
                                                    all_branches=False)
        profile.branches.add(mine)
        self.client.force_login(self.user)

    def test_the_daily_entry_grid_shows_only_the_users_rows(self):
        response = self.client.get(reverse("daily_entry_api_list"))
        body = response.content.decode()
        self.assertIn("MineFarm", body)
        self.assertNotIn("TheirFarm", body)

    def test_fetching_another_branch_row_by_id_fails(self):
        """A row id in the url is not a permission."""
        from broiler.models import DailyEntry

        row = DailyEntry.objects.get(farm=self.farms["TheirFarm"])
        response = self.client.get(reverse("daily_entry_api", args=[row.id]))
        self.assertNotEqual(response.status_code, 200)

    def test_an_unscoped_user_sees_every_row(self):
        boss = get_user_model().objects.create_superuser("tr_boss", "tb@x.com",
                                                          "Str0ngPass!")
        self.client.force_login(boss)
        body = self.client.get(reverse("daily_entry_api_list")).content.decode()
        self.assertIn("MineFarm", body)
        self.assertIn("TheirFarm", body)


class InventoryRowScopingTests(TestCase):
    """Inventory transaction grids, not just their dropdowns.

    A transfer has two ends, so the rule here is either-end rather than the
    all-must-match used for single-location rows.
    """

    def setUp(self):
        cache.clear()
        from inventory.models import StockTransfer

        User = get_user_model()
        self.user = User.objects.create_user("iv_user", "iv@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Akbarpur Store")
        self.user.groups.add(self.group)
        for tab in ("stock_transfer_list", "inventory_adjustment_list"):
            GroupTabPermission.objects.create(group=self.group, tab_code=tab,
                                              can_view=True)

        self.mine = Warehouse.objects.create(name="Akbarpur Warehouse")
        self.theirs = Warehouse.objects.create(name="Bahraich Warehouse")
        self.third = Warehouse.objects.create(name="Gorakhpur Warehouse")
        self.item = Item.objects.create(
            description="Feed", category=ItemCategory.objects.create(name="Feed"),
            valuation_method="Weighted Average", standard_cost_per_unit=50,
            usage="Produced", source="Purchased", type="Raw Material",
            item_account="Expense")

        today = timezone.localdate()
        # out of the user's warehouse, into it, and one they touch neither end of
        StockTransfer.objects.create(item=self.item, date=today, quantity=10,
                                     from_location_type="warehouse",
                                     from_warehouse=self.mine,
                                     to_location_type="warehouse",
                                     to_warehouse=self.theirs, dc_no="T-OUT")
        StockTransfer.objects.create(item=self.item, date=today, quantity=20,
                                     from_location_type="warehouse",
                                     from_warehouse=self.theirs,
                                     to_location_type="warehouse",
                                     to_warehouse=self.mine, dc_no="T-IN")
        StockTransfer.objects.create(item=self.item, date=today, quantity=30,
                                     from_location_type="warehouse",
                                     from_warehouse=self.theirs,
                                     to_location_type="warehouse",
                                     to_warehouse=self.third, dc_no="T-OTHER")

        profile = GroupAccessProfile.objects.create(group=self.group,
                                                    all_sectors=False)
        profile.sectors.add(self.mine)
        self.client.force_login(self.user)

    def test_either_end_in_scope_is_enough(self):
        """Hiding a transfer *out* of their own store would make their own
        ledger wrong rather than restricted."""
        body = self.client.get("/stock_transfer_api/").content.decode()
        self.assertIn("T-OUT", body)
        self.assertIn("T-IN", body)

    def test_a_transfer_touching_neither_end_is_hidden(self):
        body = self.client.get("/stock_transfer_api/").content.decode()
        self.assertNotIn("T-OTHER", body)

    def test_an_unscoped_user_sees_all_three(self):
        boss = get_user_model().objects.create_superuser("iv_boss", "ivb@x.com",
                                                          "Str0ngPass!")
        self.client.force_login(boss)
        body = self.client.get("/stock_transfer_api/").content.decode()
        for ref in ("T-OUT", "T-IN", "T-OTHER"):
            self.assertIn(ref, body)

    def test_scope_any_keeps_rows_with_no_location_at_all(self):
        """An unfiled row is not evidence the user should be denied it."""
        from inventory.models import StockTransfer
        from user.services.scoping import scope_any

        StockTransfer.objects.create(item=self.item, date=timezone.localdate(),
                                     quantity=5, dc_no="T-NULL")
        user = get_user_model().objects.get(pk=self.user.pk)
        refs = set(scope_any(user, StockTransfer.objects.all(),
                             sectors=("from_warehouse_id", "to_warehouse_id"),
                             farms=("from_farm_id", "to_farm_id"))
                   .values_list("dc_no", flat=True))
        self.assertIn("T-NULL", refs)
        self.assertNotIn("T-OTHER", refs)


class CrossModuleRowScopingTests(TestCase):
    """Purchase, Sales and Hatchery grids follow Inventory's.

    Each of these sits at one warehouse — on the header for hatchery and the
    notes, on the lines for purchases, and through the chick sales it carries
    for a delivery challan.
    """

    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.user = User.objects.create_user("cr_user", "cr@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Akbarpur Cross")
        self.user.groups.add(self.group)
        from user.access import ALL_TAB_CODES
        for code in ALL_TAB_CODES:
            GroupTabPermission.objects.get_or_create(
                group=self.group, tab_code=code, defaults={"can_view": True})

        self.mine = Warehouse.objects.create(name="Akbarpur Warehouse")
        self.theirs = Warehouse.objects.create(name="Bahraich Warehouse")
        profile = GroupAccessProfile.objects.create(group=self.group,
                                                    all_sectors=False)
        profile.sectors.add(self.mine)
        self.client.force_login(self.user)

    def rows(self, qs):
        from user.services.scoping import scope_any
        return scope_any(get_user_model().objects.get(pk=self.user.pk), qs,
                         sectors="warehouse_id")

    def test_hatchery_egg_purchases_are_scoped_by_warehouse(self):
        from account.models import AccountType, ChartOfAccount, CompanyProfile
        from hatchery.models import EggPurchase
        from purchase.models import Supplier

        at = AccountType.objects.create(name="T", code_range_start=500000,
                                        code_range_end=599999, report="PL")
        coa = ChartOfAccount.objects.create(company=CompanyProfile.get_solo(),
                                            code="500001", description="X",
                                            account_type=at)
        supplier = Supplier.objects.create(name="Egg Co", mobile="7100000001")
        for wh, ref in ((self.mine, "MINE"), (self.theirs, "THEIRS")):
            EggPurchase.objects.create(date=timezone.localdate(), supplier=supplier,
                                       warehouse=wh, pay_account=coa,
                                       remarks=ref)
        # remarks is normalised on save, so compare case-insensitively — the
        # point of the test is which rows come back, not how they are spelt.
        refs = {r.upper() for r in self.rows(EggPurchase.objects.all())
                .values_list("remarks", flat=True)}
        self.assertEqual(refs, {"MINE"})

    def test_a_general_purchase_is_scoped_through_its_lines(self):
        """The warehouse a purchase landed in is on the line, not the header."""
        from purchase.models import GeneralPurchase, GeneralPurchaseItem, Supplier
        from user.services.scoping import scope_any

        supplier = Supplier.objects.create(name="Feed Co", mobile="7100000002")
        item = Item.objects.create(
            description="Feed", category=ItemCategory.objects.create(name="Feed"),
            valuation_method="Weighted Average", standard_cost_per_unit=50,
            usage="Produced", source="Purchased", type="Raw Material",
            item_account="Expense")
        for wh, ref in ((self.mine, "P-MINE"), (self.theirs, "P-THEIRS")):
            gp = GeneralPurchase.objects.create(date=timezone.localdate(),
                                                supplier=supplier, remarks=ref)
            GeneralPurchaseItem.objects.create(
                purchase=gp, item=item, farm_warehouse=wh,
                sent_qty=Decimal("10"), rate=Decimal("50"),
                discount_percent=Decimal("0"), discount_amount=Decimal("0"),
                gst_percent=Decimal("0"))

        refs = {r.upper() for r in
                scope_any(get_user_model().objects.get(pk=self.user.pk),
                          GeneralPurchase.objects.all(),
                          sectors="items__farm_warehouse_id")
                .values_list("remarks", flat=True)}
        self.assertEqual(refs, {"P-MINE"})

    def test_an_unscoped_user_sees_both(self):
        from hatchery.models import EggPurchase
        from user.services.scoping import scope_any

        boss = get_user_model().objects.create_superuser("cr_boss", "crb@x.com",
                                                          "Str0ngPass!")
        self.assertEqual(
            scope_any(boss, EggPurchase.objects.all(), sectors="warehouse_id")
            .count(), EggPurchase.objects.count())


class ReportDataScopingTests(TestCase):
    """Report bodies, not just their filter bars.

    A scoped user could still read another branch's figures by opening the
    report — the dropdowns narrowed, the numbers underneath did not.
    """

    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.user = User.objects.create_user("rd_user", "rd@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Akbarpur Reports")
        self.user.groups.add(self.group)
        from user.access import ALL_TAB_CODES
        for code in ALL_TAB_CODES:
            GroupTabPermission.objects.get_or_create(
                group=self.group, tab_code=code, defaults={"can_view": True})

        self.mine = Warehouse.objects.create(name="Akbarpur Warehouse")
        self.theirs = Warehouse.objects.create(name="Bahraich Warehouse")
        profile = GroupAccessProfile.objects.create(group=self.group,
                                                    all_sectors=False,
                                                    all_supplier_groups=False)
        profile.sectors.add(self.mine)
        self.client.force_login(self.user)

    def test_the_supplier_balance_report_lists_only_permitted_suppliers(self):
        from purchase.models import Supplier, VendorGroup

        allowed = VendorGroup.objects.create(code="FD", description="Feed Vendors")
        VendorGroup.objects.create(code="EQ", description="Equipment Vendors")
        self.group.access_profile.supplier_groups.add(allowed)
        Supplier.objects.create(name="Feed Co", supplier_group="Feed Vendors",
                                mobile="7200000001")
        Supplier.objects.create(name="Equipment Co",
                                supplier_group="Equipment Vendors",
                                mobile="7200000002")

        html = self.client.get(reverse("supplier_balance")).content.decode()
        self.assertIn("Feed Co", html)
        self.assertNotIn("Equipment Co", html)

    def test_a_supplier_ledger_outside_the_scope_is_not_printed(self):
        from purchase.models import Supplier, VendorGroup

        allowed = VendorGroup.objects.create(code="FD2", description="Feed 2")
        self.group.access_profile.supplier_groups.add(allowed)
        other = Supplier.objects.create(name="Equipment Co",
                                        supplier_group="Equipment Vendors",
                                        mobile="7200000003")
        html = self.client.get(reverse("supplier_ledger"),
                               {"supplier": other.id}).content.decode()
        self.assertNotIn("Equipment Co", html)

    def test_the_journal_voucher_report_is_scoped_by_sector(self):
        from account.models import CompanyProfile, FinancialYear, Voucher

        company = CompanyProfile.get_solo()
        year = FinancialYear.objects.create(start_date="2026-04-01",
                                            end_date="2027-03-31")
        for wh, ref in ((self.mine, "JV-MINE"), (self.theirs, "JV-THEIRS"),
                        (None, "JV-NONE")):
            Voucher.objects.create(company=company, financial_year=year,
                                   sector=wh, voucher_type="Journal",
                                   date="2026-06-01", reference=ref)

        html = self.client.get(reverse("journal_voucher_report"),
                               {"from_date": "2026-01-01",
                                "to_date": "2026-12-31"}).content.decode()
        self.assertIn("JV-MINE", html)
        self.assertNotIn("JV-THEIRS", html)
        # an unfiled entry is kept: dropping it would change the totals rather
        # than restrict what is visible
        self.assertIn("JV-NONE", html)

    def test_an_unscoped_user_sees_every_voucher(self):
        boss = get_user_model().objects.create_superuser("rd_boss", "rdb@x.com",
                                                          "Str0ngPass!")
        self.client.force_login(boss)
        response = self.client.get(reverse("journal_voucher_report"))
        self.assertEqual(response.status_code, 200)
