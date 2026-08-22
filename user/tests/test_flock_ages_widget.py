"""Age wise Available Birds: what is ready to lift, and what is behind it.

The Live Flock card says how many birds are on the farms. It does not say
whether they are a week old or going out on Friday, which is the question
behind every lifting plan — so this one bands them by week, with the farms in
each band.

Alive is the same definition the Live Flock card and report use — placed less
mortality, culls and birds already lifted — so the bands add up to the figure
printed beside them.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from broiler.models import (BirdSale, Branch, BroilerBatch, BroilerFarm,
                            DailyEntry, Farmer, Region, Supervisor)
from inventory.models import Item, ItemCategory, StockTransfer, Warehouse
from user.models import GroupTabPermission
from user.services.dashboard_widgets import dashboard_widgets


class FlockAgeWidgetTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = get_user_model().objects.create_superuser(
            "faadmin", "fa@x.com", "Str0ngPass!")
        self.today = timezone.localdate()

        self.region = Region.objects.create(description="East")
        self.branch = Branch.objects.create(branch_name="Akbarpur",
                                            region=self.region, prefix="AKB")
        self.sup = Supervisor.objects.create(branch=self.branch, name="R. Verma")
        self.farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.warehouse = Warehouse.objects.create(name="Akbarpur Store")
        self.chick = Item.objects.create(
            item_code="CHK-001", description="Day Old Chick",
            category=ItemCategory.objects.create(name="Day Old Chicks"),
            standard_cost_per_unit=0)
        self.farm = self.make_farm("Yadav Farm")

    # ---- fixtures -----------------------------------------------------------

    def make_farm(self, name):
        return BroilerFarm.objects.create(
            branch=self.branch, supervisor=self.sup, farmer=self.farmer,
            region=self.region, line="Line A", farm_name=name, farm_capacity=9000)

    def flock(self, name, chicks, age, farm=None, dated=True):
        """A flock `age` days old today, with `chicks` placed into it."""
        placed_on = self.today - timedelta(days=age)
        batch = BroilerBatch.objects.create(
            broiler_farm=farm or self.farm, batch_name=name,
            start_date=placed_on if dated else None)
        StockTransfer.objects.create(
            date=placed_on, item=self.chick, quantity=chicks,
            from_location_type="warehouse", from_warehouse=self.warehouse,
            to_location_type="farm", to_farm=farm or self.farm, to_batch=batch)
        return batch

    def card(self, user=None, filters=None):
        return next((w for w in dashboard_widgets(user or self.admin, filters,
                                                  use_cache=False)
                     if w["key"] == "flock_ages"), None)

    def bands(self, **kw):
        return {g["label"]: g["values"][0] for g in self.card(**kw)["chart"]["groups"]}

    def stat(self, label, **kw):
        return next(s for s in self.card(**kw)["stats"] if s["label"] == label)

    # ---- the bands ----------------------------------------------------------

    def test_every_band_is_drawn_even_when_empty(self):
        """A gap in the pipeline is the thing worth seeing."""
        self.flock("B-1", 1000, age=20)
        self.assertEqual(list(self.bands()),
                         ["0 - 7", "8 - 14", "15 - 21", "22 - 28", "29 - 35",
                          "36 - 41", "42+ Days"])

    def test_a_flock_lands_in_the_band_its_age_falls_in(self):
        self.flock("Chicks", 1000, age=3)
        self.flock("Growing", 2000, age=18)
        self.flock("Ready", 3000, age=44)
        b = self.bands()
        self.assertEqual((b["0 - 7"], b["15 - 21"], b["42+ Days"]), (1000, 2000, 3000))

    def test_the_band_edges_belong_to_the_band_the_label_names(self):
        """Forty-two days is in "42+", not in the band that ends before it."""
        self.flock("Edge-41", 500, age=41)
        self.flock("Edge-42", 700, age=42)
        b = self.bands()
        self.assertEqual((b["36 - 41"], b["42+ Days"]), (500, 700))

    def test_two_flocks_of_the_same_age_are_added_together(self):
        self.flock("A", 1000, age=10)
        self.flock("B", 1500, age=12, farm=self.make_farm("Second Farm"))
        self.assertEqual(self.bands()["8 - 14"], 2500)

    def test_a_band_says_how_many_farms_are_in_it(self):
        self.flock("A", 1000, age=10)
        self.flock("B", 1500, age=12, farm=self.make_farm("Second Farm"))
        group = next(g for g in self.card()["chart"]["groups"] if g["label"] == "8 - 14")
        self.assertEqual(group["meta"], "2 farms · 2,500")

    # ---- what "available" means ---------------------------------------------

    def test_the_dead_the_culled_and_the_lifted_are_not_available(self):
        batch = self.flock("B-1", 1000, age=30)
        DailyEntry.objects.create(farm=self.farm, batch=batch, supervisor=self.sup,
                                  date=self.today - timedelta(days=1),
                                  mortality=40, culls=10)
        BirdSale.objects.create(farm=self.farm, batch=batch,
                                date=self.today - timedelta(days=1), birds=200)
        self.assertEqual(self.bands()["29 - 35"], 750)
        self.assertEqual(self.stat("Available birds")["value"], "750")

    def test_a_flock_that_has_gone_out_entirely_is_not_a_band_of_zero(self):
        batch = self.flock("Sold", 1000, age=44)
        BirdSale.objects.create(farm=self.farm, batch=batch,
                                date=self.today - timedelta(days=1), birds=1000)
        self.assertEqual(self.bands()["42+ Days"], 0)
        self.assertEqual(self.stat("Available birds")["value"], "0")

    def test_the_total_is_the_bands_added_up(self):
        self.flock("A", 1000, age=3)
        self.flock("B", 2000, age=20)
        self.flock("C", 3000, age=44)
        self.assertEqual(self.stat("Available birds")["value"], "6,000")
        self.assertEqual(sum(self.bands().values()), 6000)

    def test_ready_to_lift_is_36_days_and_over(self):
        self.flock("Growing", 2000, age=20)
        self.flock("Ready", 3000, age=45)
        self.assertEqual(self.stat("Ready to lift")["value"], "3,000")
        self.assertEqual(self.stat("Ready to lift")["sub"], "36 days and over")

    def test_a_flock_in_its_thirty_sixth_day_already_counts_as_ready(self):
        """36-41 is its own weekly band on the chart, but it is old enough to
        lift — the stat is not the oldest band alone."""
        self.flock("Growing", 2000, age=20)
        self.flock("Almost There", 1500, age=38)
        self.flock("Ready", 3000, age=45)
        self.assertEqual(self.stat("Ready to lift")["value"], "4,500")

    # ---- flocks without a placement date ------------------------------------

    def test_a_flock_with_no_start_date_is_aged_from_its_placement(self):
        """Batches created from a chicks placement carry no start_date; the
        placement is the day they began."""
        self.flock("Undated", 1200, age=10, dated=False)
        self.assertEqual(self.bands()["8 - 14"], 1200)
        self.assertIsNone(self.card()["note"])

    # ---- filters and permission ---------------------------------------------

    def test_it_answers_the_farm_filter(self):
        other = self.make_farm("Second Farm")
        self.flock("Mine", 1000, age=10)
        self.flock("Theirs", 5000, age=10, farm=other)
        self.assertEqual(self.bands(filters={"farm": other.id})["8 - 14"], 5000)

    def test_it_says_so_when_no_flock_matches(self):
        card = self.card()
        self.assertEqual(card["note"], "No live flocks match this filter.")

    def test_it_is_gated_on_the_live_flock_report(self):
        User = get_user_model()
        clerk = User.objects.create_user("faclerk", "c@x.com", "Str0ngPass!")
        group = Group.objects.create(name="Flocks Only")
        clerk.groups.add(group)
        GroupTabPermission.objects.create(group=group,
                                          tab_code="live_flock_summary_report",
                                          can_view=True)
        self.assertIsNotNone(self.card(user=clerk))

        blind = User.objects.create_user("fablind", "b@x.com", "Str0ngPass!")
        other = Group.objects.create(name="Stock Only")
        blind.groups.add(other)
        GroupTabPermission.objects.create(group=other, tab_code="negative_stock_report",
                                          can_view=True)
        self.assertIsNone(self.card(user=blind))
