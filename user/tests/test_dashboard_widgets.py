"""Dashboard widgets: correct figures, and never one the user may not see."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TestCase
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from broiler.models import (BirdSale, Branch, BroilerBatch, BroilerFarm, BroilerLine,
                            DailyEntry, Farmer, Region, Supervisor)
from inventory.models import Item, ItemCategory, StockTransfer
from user.models import GroupTabPermission
from user.services.dashboard_widgets import WIDGETS, dashboard_widgets


class DashboardWidgetTests(TestCase):
    def setUp(self):
        cache.clear()          # the builders cache; each test starts cold
        User = get_user_model()
        self.admin = User.objects.create_superuser("dwadmin", "d@x.com", "Str0ngPass!")
        self.today = timezone.localdate()

        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region, prefix="AKB")
        supervisor = Supervisor.objects.create(branch=branch, name="R. Verma")
        line = BroilerLine.objects.create(description="Line 1", region=region, branch=branch)
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=supervisor, farmer=farmer, region=region,
            line=line, farm_name="Yadav Farm", farm_capacity=5000)
        self.supervisor = supervisor

        self.chick = Item.objects.create(
            description="Day Old Chicks",
            category=ItemCategory.objects.create(name="Chicks"),
            valuation_method="Weighted Average", standard_cost_per_unit=40,
            usage="Produced", source="Purchased", type="Raw Material",
            item_account="Expense")

    def batch(self, name, placed=0, age=20, closed=False):
        b = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name=name,
            start_date=self.today - timedelta(days=age),
            is_closed=closed, end_date=self.today if closed else None)
        if placed:
            StockTransfer.objects.create(
                item=self.chick, to_batch=b, quantity=Decimal(placed),
                date=self.today - timedelta(days=age))
        return b

    def widget(self, user, key):
        return next((w for w in dashboard_widgets(user, use_cache=False)
                     if w["key"] == key), None)

    def stat(self, widget, label):
        return next(s for s in widget["stats"] if s["label"] == label)

    # ---- Live Flock -------------------------------------------------------

    def test_live_flock_counts_birds_alive(self):
        b = self.batch("B-1", placed=1000)
        DailyEntry.objects.create(batch=b, farm=self.farm, supervisor=self.supervisor,
                                  date=self.today, mortality=30, culls=10)
        BirdSale.objects.create(batch=b, farm=self.farm, date=self.today, birds=200)

        w = self.widget(self.admin, "live_flock")
        self.assertEqual(self.stat(w, "Open batches")["value"], "1")
        self.assertEqual(self.stat(w, "Birds alive")["value"], "760")   # 1000-30-10-200
        self.assertEqual(self.stat(w, "Mortality")["value"], "4.00%")   # (30+10)/1000

    def test_live_flock_ignores_closed_batches(self):
        self.batch("Open", placed=500)
        self.batch("Closed", placed=900, closed=True)
        w = self.widget(self.admin, "live_flock")
        self.assertEqual(self.stat(w, "Open batches")["value"], "1")
        self.assertEqual(self.stat(w, "Birds alive")["value"], "500")

    def test_live_flock_with_no_open_batches(self):
        w = self.widget(self.admin, "live_flock")
        self.assertEqual(self.stat(w, "Open batches")["value"], "0")
        self.assertTrue(w["note"])

    def test_live_flock_says_so_when_no_placement_is_recorded(self):
        """Zero birds alive is meaningless without a placement; the card must
        say why rather than show a confident 0."""
        self.batch("B-1", placed=0)
        self.assertIn("placement", self.widget(self.admin, "live_flock")["note"].lower())

    def test_high_mortality_is_toned_bad(self):
        b = self.batch("B-1", placed=1000)
        DailyEntry.objects.create(batch=b, farm=self.farm, supervisor=self.supervisor,
                                  date=self.today, mortality=100, culls=0)
        self.assertEqual(self.stat(self.widget(self.admin, "live_flock"),
                                   "Mortality")["tone"], "bad")

    # ---- Today's Daily Entries -------------------------------------------

    def test_daily_entries_splits_reported_from_missing(self):
        done = self.batch("Reported", placed=500)
        self.batch("Missing", placed=500)
        DailyEntry.objects.create(batch=done, farm=self.farm, supervisor=self.supervisor,
                                  date=self.today, mortality=1)

        w = self.widget(self.admin, "daily_entries")
        self.assertEqual(self.stat(w, "Reported")["value"], "1 of 2")
        self.assertEqual(self.stat(w, "Not yet in")["value"], "1")
        self.assertEqual([r["meta"] for r in w["rows"]], ["Missing"])

    def test_yesterdays_entry_does_not_count_as_today(self):
        b = self.batch("B-1", placed=500)
        DailyEntry.objects.create(batch=b, farm=self.farm, supervisor=self.supervisor,
                                  date=self.today - timedelta(days=1), mortality=1)
        self.assertEqual(self.stat(self.widget(self.admin, "daily_entries"),
                                   "Not yet in")["value"], "1")

    def test_all_reported_is_toned_good(self):
        b = self.batch("B-1", placed=500)
        DailyEntry.objects.create(batch=b, farm=self.farm, supervisor=self.supervisor,
                                  date=self.today, mortality=1)
        w = self.widget(self.admin, "daily_entries")
        self.assertEqual(self.stat(w, "Not yet in")["tone"], "good")
        self.assertEqual(w["rows"], [])

    # ---- permissions ------------------------------------------------------

    def test_a_user_only_gets_widgets_for_reports_they_may_open(self):
        User = get_user_model()
        clerk = User.objects.create_user("dwclerk", "c@x.com", "Str0ngPass!")
        group = Group.objects.create(name="Stock Only")
        clerk.groups.add(group)
        GroupTabPermission.objects.create(group=group, tab_code="negative_stock_report",
                                          can_view=True)

        keys = [w["key"] for w in dashboard_widgets(clerk, use_cache=False)]
        self.assertEqual(keys, ["stock_alerts"])

    def test_each_half_of_receivables_and_payables_is_gated_on_its_own_tab(self):
        User = get_user_model()
        clerk = User.objects.create_user("aronly", "r@x.com", "Str0ngPass!")
        group = Group.objects.create(name="Receivables Only")
        clerk.groups.add(group)
        GroupTabPermission.objects.create(group=group, tab_code="customer_balance",
                                          can_view=True)

        w = self.widget(clerk, "balances")
        labels = [s["label"] for s in w["stats"]]
        self.assertEqual(labels, ["Receivable"], "the payables half leaked")

    def test_a_widget_links_nowhere_when_its_report_is_off_limits(self):
        """The balances widget links to the Customer Balance report; someone
        with only the supplier half must not be handed that link."""
        User = get_user_model()
        clerk = User.objects.create_user("aponly", "p@x.com", "Str0ngPass!")
        group = Group.objects.create(name="Payables Only")
        clerk.groups.add(group)
        GroupTabPermission.objects.create(group=group, tab_code="supplier_balance",
                                          can_view=True)
        self.assertEqual(self.widget(clerk, "balances")["url"], "")

    def test_the_cache_does_not_share_a_body_between_different_permissions(self):
        """Both users see the 'balances' widget, but not the same halves - a
        cache keyed on the widget alone would serve one to the other."""
        User = get_user_model()
        users = []
        for name, tab in (("cacheA", "customer_balance"), ("cacheB", "supplier_balance")):
            u = User.objects.create_user(name, f"{name}@x.com", "Str0ngPass!")
            g = Group.objects.create(name=name)
            u.groups.add(g)
            GroupTabPermission.objects.create(group=g, tab_code=tab, can_view=True)
            users.append(u)

        first = dashboard_widgets(users[0])[0]        # caching on
        second = dashboard_widgets(users[1])[0]
        self.assertEqual([s["label"] for s in first["stats"]], ["Receivable"])
        self.assertEqual([s["label"] for s in second["stats"]], ["Payable"])

    # ---- robustness -------------------------------------------------------

    def test_one_broken_widget_does_not_take_the_dashboard_down(self):
        from unittest.mock import patch
        import user.services.dashboard_widgets as mod

        def boom(viewable):
            raise ValueError("engine exploded")

        broken = [(k, t, tabs, u, i, c, boom if k == "live_flock" else b)
                  for k, t, tabs, u, i, c, b in WIDGETS]
        with patch.object(mod, "WIDGETS", broken):
            with self.assertLogs("user.services.dashboard_widgets", "ERROR"):
                cards = dashboard_widgets(self.admin, use_cache=False)

        live = next(w for w in cards if w["key"] == "live_flock")
        self.assertTrue(live["error"])
        self.assertTrue(live["note"])
        # and the rest still rendered
        self.assertEqual(len(cards), len(WIDGETS))

    # ---- registry stays honest -------------------------------------------

    def test_every_widget_points_at_a_real_tab_and_a_routable_page(self):
        """Tab codes drift (the balance reports are 'supplier_balance', not
        'supplier_balance_report'); a wrong one silently hides the widget."""
        from user.access import ALL_TAB_CODES

        for key, _title, tabs, url_name, _icon, _colour, _build in WIDGETS:
            with self.subTest(widget=key):
                for tab in tabs:
                    self.assertIn(tab, ALL_TAB_CODES, f"{key}: unknown tab {tab!r}")
                self.assertIn(url_name, tabs, f"{key}: links outside its own gate")
                try:
                    reverse(url_name)
                except NoReverseMatch:
                    self.fail(f"{key}: '{url_name}' is not routable")

    def test_a_superuser_gets_all_four(self):
        self.assertEqual([w["key"] for w in dashboard_widgets(self.admin, use_cache=False)],
                         ["live_flock", "daily_entries", "balances", "stock_alerts"])

    # ---- the endpoint and the page ---------------------------------------

    def test_endpoint_requires_a_login(self):
        response = self.client.get(reverse("dashboard_widgets_api"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response["Location"])

    def test_endpoint_returns_the_widgets(self):
        self.batch("B-1", placed=1000)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard_widgets_api"))
        self.assertEqual(response.status_code, 200)
        keys = [w["key"] for w in response.json()["widgets"]]
        self.assertIn("live_flock", keys)

    def test_the_dashboard_renders_the_widget_grid(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse("dashboard")).content.decode()
        self.assertIn('id="dash-widgets"', html)
        self.assertIn(reverse("dashboard_widgets_api"), html)
        # the static filler it replaced is gone
        self.assertNotIn("Getting started", html)
