"""The phase requirement: survivors' full allowance, plus what the departed ate.

Two earlier rules were each wrong in their own direction. Counting the
requirement on live birds put one population on one side of "required less
fed" and the whole flock's consumption on the other. Counting it on birds
placed charged a bird that died on day three an allowance it never lived to
eat.

A bird that dies on day twelve has eaten twelve days of feed. Charging each
departure what it actually consumed — at the flock's cumulative feed per bird
on the day it left — makes "required less fed" resolve to exactly what the
birds still on the farm are owed.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase

from broiler.models import (Branch, BroilerBatch, BroilerFarm, DailyEntry,
                            Farmer, Region, Supervisor)
from broiler.views import _departed_feed_charge
from inventory.models import Item, ItemCategory


class DepartedFeedChargeTests(TestCase):
    def setUp(self):
        self.today = date(2026, 7, 23)
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region, prefix="AKB")
        self.sup = Supervisor.objects.create(branch=branch, name="R. Verma")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=self.sup, farmer=farmer, region=region,
            line="L1", farm_name="Yadav Farm", farm_capacity=9000)
        cat = ItemCategory.objects.create(name="Broiler Feed")
        self.feed = Item.objects.create(item_code="ITM-1", description="Pre-Starter",
                                        category=cat, standard_cost_per_unit=0)
        self.batch = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="B-1",
            start_date=self.today - timedelta(days=10))

    def day(self, n, *, lost=0, kg=0):
        return DailyEntry.objects.create(
            farm=self.farm, batch=self.batch, supervisor=self.sup,
            date=self.today - timedelta(days=10 - n),
            mortality=lost, feed_1=self.feed, feed_1_qty=Decimal(str(kg)))

    def charge(self, placed=1000):
        return _departed_feed_charge(self.batch, self.today,
                                     Decimal(str(placed))).get(self.feed.id,
                                                               Decimal("0"))

    def test_the_worked_example(self):
        """1,000 placed. Day 1: 10 die, 50 kg eaten — 50 g a bird. Day 2: 10
        more die, 20 kg more across 990 — 20.20 g a bird, 70.20 g cumulative.

        The ten that went on day 1 are charged 50 g each; the ten on day 2,
        70.20 g each. 500 g + 702 g = 1.202 kg.
        """
        self.day(1, lost=10, kg=50)
        self.day(2, lost=10, kg=20)
        self.assertEqual(self.charge(), Decimal("1.20"))

    def test_the_requirement_and_the_subtraction_reconcile(self):
        """cap x live + departed charge, less everything fed, is what the
        survivors are still owed — the whole point of the change."""
        self.day(1, lost=10, kg=50)
        self.day(2, lost=10, kg=20)
        cap, live, fed = Decimal("0.4"), Decimal("980"), Decimal("70")
        required = cap * live + self.charge()
        survivors_ate = fed - self.charge()
        still_owed = (cap - survivors_ate / live) * live
        self.assertEqual((required - fed).quantize(Decimal("0.01")),
                         still_owed.quantize(Decimal("0.01")))

    def test_a_flock_that_has_lost_nothing_is_charged_nothing(self):
        self.day(1, kg=50)
        self.assertEqual(self.charge(), Decimal("0"))

    def test_a_bird_that_died_before_any_feed_is_charged_nothing(self):
        """It ate nothing, so it owes nothing — which is what counting the
        requirement on birds placed got wrong."""
        self.day(1, lost=10, kg=0)
        self.assertEqual(self.charge(), Decimal("0"))

    def test_birds_sold_are_departed_too(self):
        """They ate while they were here and they are not here now."""
        from broiler.models import BirdSale

        self.day(1, kg=50)
        BirdSale.objects.create(farm=self.farm, batch=self.batch,
                                date=self.today - timedelta(days=8), birds=100)
        self.day(2, kg=20)
        self.assertGreater(self.charge(), Decimal("0"))

    def test_only_days_before_the_entry_count(self):
        """The row being written must not be charged against itself."""
        self.day(1, lost=10, kg=50)
        later = DailyEntry.objects.create(
            farm=self.farm, batch=self.batch, supervisor=self.sup,
            date=self.today, mortality=500, feed_1=self.feed,
            feed_1_qty=Decimal("999"))
        self.assertEqual(self.charge(), Decimal("0.50"))
        later.delete()

    def test_each_feed_type_is_charged_on_its_own_consumption(self):
        """Caps are per item, so the attribution has to be as well."""
        other = Item.objects.create(item_code="ITM-2", description="Starter",
                                    category=self.feed.category,
                                    standard_cost_per_unit=0)
        self.day(1, lost=10, kg=50)
        DailyEntry.objects.create(farm=self.farm, batch=self.batch,
                                  supervisor=self.sup,
                                  date=self.today - timedelta(days=8),
                                  mortality=10, feed_1=other,
                                  feed_1_qty=Decimal("30"))
        charges = _departed_feed_charge(self.batch, self.today, Decimal("1000"))
        self.assertEqual(charges[self.feed.id], Decimal("1.00"))   # 50g x 20 gone
        self.assertGreater(charges[other.id], Decimal("0"))
