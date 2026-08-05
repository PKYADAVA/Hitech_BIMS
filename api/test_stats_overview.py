"""The dashboard payload behind the phone's Home screen.

The old payload gave counts only, which is why the Today's Overview panel could
not be built: a mortality *count* says nothing without the flock size behind
it, and there was no feed, placement or FCR figure at all.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from broiler.models import (Branch, BroilerBatch, BroilerFarm, DailyEntry,
                            Farmer, Region, Supervisor)
from inventory.models import Item, ItemCategory, StockTransfer, Warehouse

URL = "/api/v1/stats/overview"


class StatsOverviewTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region,
                                       prefix="AKB")
        self.supervisor = Supervisor.objects.create(branch=branch, name="R. Verma")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=self.supervisor, farmer=farmer,
            region=region, line="L1", farm_name="Yadav Farm", farm_capacity=5000)
        self.batch = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="B1",
            start_date=self.today - timedelta(days=20))
        Warehouse.objects.create(name="Main Warehouse")

        self.chick = Item.objects.create(
            description="Day Old Chicks",
            category=ItemCategory.objects.create(name="Chicks"),
            valuation_method="Weighted Average", standard_cost_per_unit=40,
            usage="Produced", source="Purchased", type="Raw Material",
            item_account="Expense")
        self.feed = Item.objects.create(
            description="Starter Feed",
            category=ItemCategory.objects.create(name="Feed"),
            valuation_method="Weighted Average", standard_cost_per_unit=30,
            usage="Produced", source="Purchased", type="Raw Material",
            item_account="Expense")

        User = get_user_model()
        self.user = User.objects.create_superuser("ov_user", "ov@x.com",
                                                  "Str0ngPass!")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def place(self, quantity, days_ago=0):
        return StockTransfer.objects.create(
            item=self.chick, quantity=quantity, to_batch=self.batch,
            to_farm=self.farm, to_location_type="farm",
            date=self.today - timedelta(days=days_ago))

    def entry(self, days_ago=0, mortality=0, culls=0, feed=0, weight=0):
        return DailyEntry.objects.create(
            farm=self.farm, batch=self.batch, supervisor=self.supervisor,
            date=self.today - timedelta(days=days_ago),
            mortality=mortality, culls=culls,
            feed_1=self.feed, feed_1_qty=feed, avg_weight_gms=weight)

    def overview(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        return response.json()["data"]

    # ---- Today's Overview ---------------------------------------------------

    def test_birds_placed_today_counts_only_today(self):
        self.place(5000, days_ago=0)
        self.place(3000, days_ago=4)
        self.assertEqual(self.overview()["broiler"]["birds_placed_today"], 5000)

    def test_feed_is_the_day_s_kilos_across_both_slots(self):
        self.entry(feed=120)
        self.entry(feed=80)
        self.assertEqual(self.overview()["broiler"]["feed_kg_today"], 200.0)

    def test_mortality_is_a_share_of_the_birds_alive_not_a_count(self):
        """100 deaths means one thing in 5,000 birds and another in 50,000 —
        the count alone is what the old payload offered."""
        self.place(5000, days_ago=10)
        self.entry(mortality=50)
        self.assertAlmostEqual(self.overview()["broiler"]["mortality_pct_today"],
                               1.01, places=1)

    def test_losses_already_booked_reduce_the_live_flock(self):
        self.place(1000, days_ago=10)
        self.entry(days_ago=5, mortality=100, culls=100)
        self.assertEqual(self.overview()["broiler"]["live_birds"], 800)

    def test_fcr_is_feed_against_live_weight(self):
        self.place(1000, days_ago=10)
        self.entry(days_ago=1, feed=400, weight=1000)   # 1000 birds x 1kg
        data = self.overview()["broiler"]
        self.assertEqual(data["fcr"], 0.4)

    def test_fcr_counts_weight_already_sold_as_the_erp_does(self):
        """The Live Flock Summary divides feed by the weight the flock is
        carrying *now* — sold weight plus live weight. A first cut of this
        counted only the live half, which overstates FCR on any batch that has
        started selling, and the phone would have disagreed with the report.
        """
        from broiler.models import BirdSale

        self.place(1000, days_ago=20)
        self.entry(days_ago=2, feed=1000, weight=1000)     # 1 kg birds
        BirdSale.objects.create(farm=self.farm, batch=self.batch,
                                date=self.today - timedelta(days=1),
                                birds=400, net_weight=800)

        # 600 alive x 1 kg = 600, plus 800 kg sold = 1400 kg carried.
        self.assertAlmostEqual(self.overview()["broiler"]["fcr"],
                               1000 / 1400, places=2)

    def test_nothing_divides_by_zero_on_an_empty_system(self):
        data = self.overview()["broiler"]
        self.assertEqual(data["mortality_pct_today"], 0.0)
        self.assertEqual(data["live_birds"], 0)

    def test_fcr_is_absent_rather_than_huge_when_nothing_is_weighed(self):
        """Feed over a near-zero live weight gave an FCR of 23 on a farm whose
        birds simply had not been weighed — that reads as a catastrophe, not as
        missing data. The panel shows a dash instead."""
        self.place(1000, days_ago=10)
        self.entry(days_ago=1, feed=400)          # fed, never weighed
        self.assertIsNone(self.overview()["broiler"]["fcr"])

    # ---- visits -------------------------------------------------------------

    def test_visits_report_today_s_and_which_are_finished(self):
        from hr.models import Employee, SupervisorTrip, SupervisorTripVisit

        employee = Employee.objects.create(full_name="R. Verma")
        trip = SupervisorTrip.objects.create(employee=employee, date=self.today)
        now = timezone.now()
        SupervisorTripVisit.objects.create(trip=trip, farm=self.farm,
                                           checked_in_at=now, checked_out_at=now)
        SupervisorTripVisit.objects.create(trip=trip, farm=self.farm,
                                           checked_in_at=now)

        visits = self.overview()["visits"]
        self.assertEqual(visits["today"], 2)
        self.assertEqual(visits["completed"], 1)
        self.assertEqual(len(visits["rows"]), 2)

    # ---- alerts -------------------------------------------------------------

    def test_alerts_come_from_the_erp_s_alert_system(self):
        """alerthub, not the audit trail. alerts.Alert records every model
        change — tokens, permission rows — and had 1,690 unread, none of it
        anything a supervisor would act on. alerthub is what the ERP's bell and
        notification centre read, and it addresses each notification to
        particular users.
        """
        from alerthub.models import Notification, NotificationRecipient

        note = Notification.objects.create(
            rule_key="feed_low", module="broiler", priority="high",
            title="Feed low in Main Store")
        NotificationRecipient.objects.create(notification=note, user=self.user)

        alerts = self.overview()["alerts"]
        self.assertEqual(alerts["pending"], 1)
        self.assertEqual(alerts["high"], 1)
        self.assertEqual(alerts["rows"][0]["title"], "Feed low in Main Store")

    def test_another_user_s_alerts_are_not_shown(self):
        """Notifications are addressed; the dashboard is not a shared inbox."""
        from alerthub.models import Notification, NotificationRecipient

        other = get_user_model().objects.create_user("someone_else", "x@x.com",
                                                     "Str0ngPass!")
        note = Notification.objects.create(
            rule_key="feed_low", module="broiler", priority="high",
            title="Not for you")
        NotificationRecipient.objects.create(notification=note, user=other)

        self.assertEqual(self.overview()["alerts"]["pending"], 0)

    def test_a_read_alert_stops_counting(self):
        from alerthub.models import Notification, NotificationRecipient

        note = Notification.objects.create(
            rule_key="feed_low", module="broiler", priority="high", title="Seen")
        NotificationRecipient.objects.create(notification=note, user=self.user,
                                             is_read=True)
        self.assertEqual(self.overview()["alerts"]["pending"], 0)

    # ---- system summary -----------------------------------------------------

    def test_the_system_summary_counts_what_the_strip_shows(self):
        system = self.overview()["system"]
        for key in ("users", "farms", "stores", "items", "batches"):
            with self.subTest(field=key):
                self.assertIn(key, system)
        self.assertEqual(system["farms"], 1)
        self.assertEqual(system["stores"], 1)
        self.assertEqual(system["batches"], 1)

    def test_the_older_keys_are_still_there(self):
        """The Home carousel reads these; adding fields must not move them."""
        data = self.overview()
        for key in ("entries_today", "mortality_today", "active_batches",
                    "farms", "mortality_7d"):
            with self.subTest(field=key):
                self.assertIn(key, data["broiler"])


class StatsOverviewScopingTests(TestCase):
    """The dashboard shows the signed-in user's numbers, not the company's.

    A supervisor limited to one branch was being given the whole business's
    placements, feed, flock counts and visits — the same leak the web reports
    had, one layer further out. The KPIs are the first thing anyone sees, so
    it is the most visible place for it to be wrong.
    """

    def setUp(self):
        from django.contrib.auth.models import Group

        from user.models import GroupAccessProfile, GroupTabPermission

        self.today = timezone.localdate()
        region = Region.objects.create(description="East")
        self.mine_branch = Branch.objects.create(branch_name="Akbarpur",
                                                 region=region, prefix="AKB")
        other_branch = Branch.objects.create(branch_name="Bahraich",
                                             region=region, prefix="BHR")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")

        # The item first: the farm helper below places chicks with it.
        self.chick = Item.objects.create(
            description="Day Old Chicks",
            category=ItemCategory.objects.create(name="Chicks"),
            valuation_method="Weighted Average", standard_cost_per_unit=40,
            usage="Produced", source="Purchased", type="Raw Material",
            item_account="Expense")

        self.mine = self.farm("Mineglade", self.mine_branch, farmer, region)
        self.theirs = self.farm("Farville", other_branch, farmer, region)

        User = get_user_model()
        self.user = User.objects.create_user("scoped_ov", "s@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Akbarpur Team")
        self.user.groups.add(self.group)
        GroupTabPermission.objects.create(group=self.group, tab_code="items",
                                          can_view=True)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def farm(self, name, branch, farmer, region):
        supervisor = Supervisor.objects.create(branch=branch, name="%s Sup" % name)
        farm = BroilerFarm.objects.create(
            branch=branch, supervisor=supervisor, farmer=farmer, region=region,
            line="L1", farm_name=name, farm_capacity=5000)
        batch = BroilerBatch.objects.create(
            broiler_farm=farm, batch_name="%s-B1" % name,
            start_date=self.today - timedelta(days=10))
        DailyEntry.objects.create(farm=farm, batch=batch, supervisor=supervisor,
                                  date=self.today, mortality=5)
        StockTransfer.objects.create(item=self.chick, quantity=1000,
                                     to_batch=batch, to_farm=farm,
                                     to_location_type="farm", date=self.today)
        return farm

    def limit_to_akbarpur(self):
        from user.models import GroupAccessProfile

        profile = GroupAccessProfile.objects.create(
            group=self.group, access_type="sub_admin",
            all_branches=False, all_farms=False)
        profile.branches.add(self.mine_branch)
        profile.farms.add(self.mine)

    def overview(self):
        return self.client.get(URL).json()["data"]

    def test_an_unscoped_user_sees_the_whole_business(self):
        """Fail-open, as everywhere else: no access profile means no limit."""
        data = self.overview()
        self.assertEqual(data["broiler"]["farms"], 2)
        self.assertEqual(data["broiler"]["birds_placed_today"], 2000)

    def test_a_branch_limited_user_sees_only_their_own(self):
        self.limit_to_akbarpur()
        data = self.overview()
        self.assertEqual(data["broiler"]["farms"], 1)
        self.assertEqual(data["broiler"]["birds_placed_today"], 1000)
        self.assertEqual(data["broiler"]["active_batches"], 1)

    def test_the_mortality_figure_is_their_own_flock_s(self):
        self.limit_to_akbarpur()
        self.assertEqual(self.overview()["broiler"]["mortality_today"], 5)

    def test_the_system_summary_counts_only_what_they_may_see(self):
        self.limit_to_akbarpur()
        system = self.overview()["system"]
        self.assertEqual(system["farms"], 1)
        self.assertEqual(system["batches"], 1)


class StatsOverviewFilterTests(TestCase):
    """The dashboard's two filters: which farm, and how wide a window.

    The farm one is intersected with the user's scope rather than trusted. The
    picker only offers their own farms, but a query string is not a picker.
    """

    def setUp(self):
        self.today = timezone.localdate()
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region,
                                       prefix="AKB")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.chick = Item.objects.create(
            description="Day Old Chicks",
            category=ItemCategory.objects.create(name="Chicks"),
            valuation_method="Weighted Average", standard_cost_per_unit=40,
            usage="Produced", source="Purchased", type="Raw Material",
            item_account="Expense")

        self.a = self.farm("Alpha", branch, farmer, region, placed=1000)
        self.b = self.farm("Beta", branch, farmer, region, placed=400)

        User = get_user_model()
        self.user = User.objects.create_superuser("filt_user", "f@x.com",
                                                  "Str0ngPass!")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def farm(self, name, branch, farmer, region, placed):
        supervisor = Supervisor.objects.create(branch=branch, name="%s Sup" % name)
        farm = BroilerFarm.objects.create(
            branch=branch, supervisor=supervisor, farmer=farmer, region=region,
            line="L1", farm_name=name, farm_capacity=5000)
        batch = BroilerBatch.objects.create(
            broiler_farm=farm, batch_name="%s-B1" % name,
            start_date=self.today - timedelta(days=10))
        StockTransfer.objects.create(item=self.chick, quantity=placed,
                                     to_batch=batch, to_farm=farm,
                                     to_location_type="farm", date=self.today)
        # An older placement, outside "today" but inside a week.
        StockTransfer.objects.create(item=self.chick, quantity=50,
                                     to_batch=batch, to_farm=farm,
                                     to_location_type="farm",
                                     date=self.today - timedelta(days=3))
        return farm

    def overview(self, **params):
        return self.client.get(URL, params).json()["data"]

    def test_no_filter_covers_every_farm_and_today_only(self):
        data = self.overview()
        self.assertEqual(data["broiler"]["birds_placed_today"], 1400)
        self.assertEqual(data["filters"]["period"], "today")

    def test_choosing_a_farm_narrows_the_figures(self):
        self.assertEqual(
            self.overview(farm=str(self.a.id))["broiler"]["birds_placed_today"],
            1000)

    def test_widening_to_a_week_takes_in_the_earlier_days(self):
        data = self.overview(period="week")
        self.assertEqual(data["broiler"]["birds_placed_today"], 1500)
        self.assertEqual(data["filters"]["period"], "week")

    def test_the_two_filters_combine(self):
        self.assertEqual(
            self.overview(farm=str(self.a.id), period="week")
            ["broiler"]["birds_placed_today"], 1050)

    def test_the_picker_offers_the_user_s_farms(self):
        names = {f["name"] for f in self.overview()["farm_options"]}
        self.assertEqual(names, {"Alpha", "Beta"})

    def test_a_nonsense_period_falls_back_to_today(self):
        data = self.overview(period="decade")
        self.assertEqual(data["filters"]["period"], "today")
        self.assertEqual(data["broiler"]["birds_placed_today"], 1400)

    def test_a_farm_outside_the_scope_is_ignored_not_obeyed(self):
        """The query string is not the picker."""
        from django.contrib.auth.models import Group

        from user.models import GroupAccessProfile, GroupTabPermission

        limited = get_user_model().objects.create_user("limited_ov", "l@x.com",
                                                       "Str0ngPass!")
        group = Group.objects.create(name="Alpha Only")
        limited.groups.add(group)
        GroupTabPermission.objects.create(group=group, tab_code="items",
                                          can_view=True)
        profile = GroupAccessProfile.objects.create(
            group=group, access_type="sub_admin", all_farms=False)
        profile.farms.add(self.a)

        client = APIClient()
        client.force_authenticate(limited)
        data = client.get(URL, {"farm": str(self.b.id)}).json()["data"]
        # Beta is not theirs, so the filter is dropped and they still see only
        # Alpha — never Beta's numbers.
        self.assertEqual(data["broiler"]["birds_placed_today"], 1000)
