"""Dashboard widgets: correct figures, and never one the user may not see."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TestCase
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from broiler.models import (BirdSale, Branch, BroilerBatch, BroilerFarm, DailyEntry,
                            Farmer, Region, Supervisor)
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
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=supervisor, farmer=farmer, region=region,
            line="Line A", farm_name="Yadav Farm", farm_capacity=5000)
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

    def widget(self, user, key, filters=None):
        from user.services.dashboard_widgets import FILTER_KEYS

        full = dict.fromkeys(FILTER_KEYS)
        full.update(filters or {})
        return next((w for w in dashboard_widgets(user, full, use_cache=False)
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

    # ---- the filter bar ---------------------------------------------------

    def other_farm(self):
        """A second farm under its own branch / line / supervisor."""
        region = Region.objects.create(description="West")
        branch = Branch.objects.create(branch_name="Bahraich", region=region, prefix="BHR")
        supervisor = Supervisor.objects.create(branch=branch, name="K. Singh")
        farmer = Farmer.objects.create(farmer_name="M. Kumar")
        return BroilerFarm.objects.create(
            branch=branch, supervisor=supervisor, farmer=farmer, region=region,
            line="Line B", farm_name="Kumar Farm", farm_capacity=4000)

    def test_farm_filter_narrows_the_flock(self):
        self.batch("Mine", placed=1000)
        other = self.other_farm()
        BroilerBatch.objects.create(broiler_farm=other, batch_name="Theirs",
                                    start_date=self.today - timedelta(days=10))

        w = self.widget(self.admin, "live_flock", {"farm": self.farm.id})
        self.assertEqual(self.stat(w, "Open batches")["value"], "1")
        self.assertEqual(self.stat(w, "Birds alive")["value"], "1,000")

    def test_branch_line_and_supervisor_all_narrow_the_flock(self):
        self.batch("Mine", placed=500)
        other = self.other_farm()
        BroilerBatch.objects.create(broiler_farm=other, batch_name="Theirs",
                                    start_date=self.today - timedelta(days=10))

        for key, value in (("branch", self.farm.branch_id),
                           ("line", self.farm.line),
                           ("supervisor", self.farm.supervisor_id)):
            with self.subTest(filter=key):
                w = self.widget(self.admin, "live_flock", {key: value})
                self.assertEqual(self.stat(w, "Open batches")["value"], "1")

    def test_filters_combine_rather_than_override(self):
        """Branch of farm A with the farm of B must match nothing, not fall
        back to whichever filter was applied last."""
        self.batch("Mine", placed=500)
        other = self.other_farm()
        BroilerBatch.objects.create(broiler_farm=other, batch_name="Theirs",
                                    start_date=self.today - timedelta(days=10))

        w = self.widget(self.admin, "live_flock",
                        {"branch": self.farm.branch_id, "farm": other.id})
        self.assertEqual(self.stat(w, "Open batches")["value"], "0")

    def test_the_date_filter_rewinds_the_flock(self):
        b = self.batch("B-1", placed=1000, age=30)
        DailyEntry.objects.create(batch=b, farm=self.farm, supervisor=self.supervisor,
                                  date=self.today - timedelta(days=20), mortality=10)
        DailyEntry.objects.create(batch=b, farm=self.farm, supervisor=self.supervisor,
                                  date=self.today, mortality=50)

        back = self.widget(self.admin, "live_flock",
                           {"date": self.today - timedelta(days=10)})
        # only the older loss counts as at that date
        self.assertEqual(self.stat(back, "Birds alive")["value"], "990")
        self.assertEqual(self.stat(back, "Avg age")["value"], "20 d")
        # and today still sees both
        self.assertEqual(self.stat(self.widget(self.admin, "live_flock"),
                                   "Birds alive")["value"], "940")

    def test_a_batch_that_ended_before_the_date_is_not_live_then(self):
        b = self.batch("Ended", placed=500, age=40)
        b.end_date = self.today - timedelta(days=5)
        b.is_closed = True
        b.save()
        recent = self.widget(self.admin, "live_flock",
                             {"date": self.today - timedelta(days=1)})
        self.assertEqual(self.stat(recent, "Open batches")["value"], "0")
        # but it was live a fortnight ago
        older = self.widget(self.admin, "live_flock",
                            {"date": self.today - timedelta(days=14)})
        self.assertEqual(self.stat(older, "Open batches")["value"], "1")

    def test_daily_entries_follows_the_chosen_day(self):
        b = self.batch("B-1", placed=500, age=30)
        yesterday = self.today - timedelta(days=1)
        DailyEntry.objects.create(batch=b, farm=self.farm, supervisor=self.supervisor,
                                  date=yesterday, mortality=1)

        self.assertEqual(self.stat(self.widget(self.admin, "daily_entries"),
                                   "Not yet in")["value"], "1")
        w = self.widget(self.admin, "daily_entries", {"date": yesterday})
        self.assertEqual(self.stat(w, "Reported")["value"], "1 of 1")

    def test_a_widget_says_which_filters_it_could_not_apply(self):
        """Receivables has no farm dimension; the card must admit that rather
        than show an unfiltered figure under a filter."""
        w = self.widget(self.admin, "receivables",
                        {"branch": self.farm.branch_id, "farm": self.farm.id})
        self.assertIn("Branch", w["ignored"])
        self.assertIn("Farm", w["ignored"])

    def test_no_note_when_every_active_filter_applied(self):
        w = self.widget(self.admin, "live_flock", {"farm": self.farm.id})
        self.assertIsNone(w["ignored"])
        # and none at all when nothing is filtered
        self.assertIsNone(self.widget(self.admin, "receivables")["ignored"])

    def test_stock_alerts_takes_the_farm_but_not_the_supervisor(self):
        w = self.widget(self.admin, "stock_alerts",
                        {"farm": self.farm.id, "supervisor": self.supervisor.id})
        self.assertIn("Supervisor", w["ignored"])
        self.assertNotIn("Farm", w["ignored"])

    def test_a_filtered_dashboard_is_not_served_from_cache(self):
        """The unfiltered payload must never be handed back for a filter."""
        self.batch("Mine", placed=1000)
        unfiltered = dashboard_widgets(self.admin)          # caching on, warms it
        self.assertEqual(self.stat(
            next(w for w in unfiltered if w["key"] == "live_flock"),
            "Birds alive")["value"], "1,000")

        other = self.other_farm()
        filtered = dashboard_widgets(self.admin, {"farm": other.id})
        self.assertEqual(self.stat(
            next(w for w in filtered if w["key"] == "live_flock"),
            "Open batches")["value"], "0")

    def test_parse_filters_ignores_rubbish(self):
        from user.services.dashboard_widgets import parse_filters

        parsed = parse_filters({"date": "not-a-date", "branch": "abc",
                                "farm": "", "supervisor": "7", "line": " Line A "})
        self.assertIsNone(parsed["date"])
        self.assertIsNone(parsed["branch"])
        self.assertIsNone(parsed["farm"])
        self.assertEqual(parsed["supervisor"], 7)
        # Line is free text on the farm, not an id, so it stays a string
        self.assertEqual(parsed["line"], "Line A")
        self.assertIsNone(parse_filters({"line": "   "})["line"])

    def test_the_endpoint_accepts_the_filter_querystring(self):
        self.batch("Mine", placed=1000)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard_widgets_api"),
                                   {"farm": self.other_farm().id})
        self.assertEqual(response.status_code, 200)
        flock = next(w for w in response.json()["widgets"]
                     if w["key"] == "live_flock")
        self.assertEqual(self.stat(flock, "Open batches")["value"], "0")

    def test_the_broiler_report_link_carries_the_filter(self):
        w = self.widget(self.admin, "live_flock",
                        {"farm": self.farm.id, "date": self.today})
        self.assertIn(f"farm={self.farm.id}", w["url"])
        self.assertIn(f"date={self.today.isoformat()}", w["url"])

    def test_a_non_broiler_report_link_is_left_clean(self):
        """Sending branch=3 to the Customer Balance report is just noise."""
        w = self.widget(self.admin, "receivables", {"farm": self.farm.id})
        self.assertNotIn("?", w["url"])

    def test_the_dashboard_renders_the_filter_bar(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse("dashboard")).content.decode()
        for field in ("dwf-date", "dwf-branch", "dwf-line", "dwf-supervisor",
                      "dwf-farm", "dwf-submit"):
            self.assertIn(f'id="{field}"', html)
        self.assertIn("Yadav Farm", html)          # options are populated

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

    def test_receivables_and_payables_are_each_gated_on_their_own_tab(self):
        User = get_user_model()
        clerk = User.objects.create_user("aronly", "r@x.com", "Str0ngPass!")
        group = Group.objects.create(name="Receivables Only")
        clerk.groups.add(group)
        GroupTabPermission.objects.create(group=group, tab_code="customer_balance",
                                          can_view=True)

        w = self.widget(clerk, "receivables")
        self.assertEqual([s["label"] for s in w["stats"]],
                         ["Total receivable", "Overdue ≤ 1 month",
                          "Overdue ≤ 1 week", "Overdue ≤ 2 days"])
        # And nothing of the supplier side reaches them at all — the two are
        # separate widgets now, not two halves of one card.
        self.assertIsNone(self.widget(clerk, "payables"))

    def test_a_widget_is_absent_when_its_report_is_off_limits(self):
        """Someone with only the supplier balance gets Payables and no
        Receivables — where the combined card used to appear with a link they
        could not follow."""
        User = get_user_model()
        clerk = User.objects.create_user("aponly", "p@x.com", "Str0ngPass!")
        group = Group.objects.create(name="Payables Only")
        clerk.groups.add(group)
        GroupTabPermission.objects.create(group=group, tab_code="supplier_balance",
                                          can_view=True)
        self.assertIsNone(self.widget(clerk, "receivables"))
        self.assertEqual([s["label"] for s in self.widget(clerk, "payables")["stats"]],
                         ["Total payable", "Overdue", "Due today"])

    def test_the_cache_does_not_share_a_body_between_different_permissions(self):
        """The two see different widgets entirely — one Receivables, one
        Payables — and a cache keyed on the user alone would serve one the
        other's card."""
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
        self.assertEqual(first["key"], "receivables")
        self.assertEqual(second["key"], "payables")

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

    def test_a_superuser_gets_them_all(self):
        self.assertEqual([w["key"] for w in dashboard_widgets(self.admin, use_cache=False)],
                         ["live_flock", "daily_entries", "liftings", "receivables",
                          "payables", "stock_alerts"])

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
