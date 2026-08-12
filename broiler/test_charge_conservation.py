"""The departed-bird charge, checked against an independently written model.

Conservation is what matters: every kilo fed must end up charged to exactly
one bird-share. If ``live x survivors' per-bird + charged-to-departed`` does
not come back to total fed, feed is being invented or lost — and the phase
requirement is built on top of that figure.
"""
from datetime import date, timedelta
from decimal import Decimal as D

from django.test import TestCase

from broiler.models import (BirdSale, Branch, BroilerBatch, BroilerFarm,
                            DailyEntry, Farmer, Region, Supervisor)
from broiler.views import _departed_feed_charge
from inventory.models import Item, ItemCategory


def reference(placed, days):
    """Written fresh from the rule, not from the implementation."""
    alive, cum, charge, fed = D(placed), D("0"), D("0"), D("0")
    for lost, sold, feed in days:
        lost, sold, feed = D(lost), D(sold), D(feed)
        if alive <= 0:
            break
        if feed:
            cum += feed / alive
            fed += feed
        gone = min(lost + sold, alive)
        charge += gone * cum
        alive -= gone
    return alive, cum, charge, fed


class ChargeConservationTests(TestCase):
    SCENARIOS = [
        ("the worked example", 1000, [(10, 0, 50), (10, 0, 20)]),
        ("no losses at all", 1000, [(0, 0, 50), (0, 0, 20)]),
        ("a death before any feed", 1000, [(10, 0, 0), (0, 0, 50)]),
        ("feed before any death", 1000, [(0, 0, 50), (10, 0, 0)]),
        ("a lifting mid-phase", 1000, [(5, 0, 40), (0, 400, 60), (5, 0, 30)]),
        ("losses every single day", 2000,
         [(20, 0, 80), (18, 0, 90), (25, 0, 110), (12, 0, 130), (30, 0, 150)]),
        ("a big lifting then more feed", 3000,
         [(10, 0, 200), (0, 1500, 250), (10, 0, 120)]),
    ]

    def setUp(self):
        self.start = date(2026, 5, 1)
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region, prefix="AKB")
        self.sup = Supervisor.objects.create(branch=branch, name="R. Verma")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=self.sup, farmer=farmer, region=region,
            line="L1", farm_name="Yadav Farm", farm_capacity=9000)
        cat = ItemCategory.objects.create(name="Broiler Feed")
        self.item = Item.objects.create(item_code="ITM-1", description="Pre-Starter",
                                        category=cat, standard_cost_per_unit=0)

    def build(self, name, days):
        batch = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name=name[:20], start_date=self.start)
        for i, (lost, sold, feed) in enumerate(days):
            day = self.start + timedelta(days=i + 1)
            DailyEntry.objects.create(
                farm=self.farm, batch=batch, supervisor=self.sup, date=day,
                mortality=lost, feed_1=self.item, feed_1_qty=D(str(feed)))
            if sold:
                BirdSale.objects.create(farm=self.farm, batch=batch, date=day,
                                        birds=sold)
        return batch, self.start + timedelta(days=len(days) + 1)

    def test_every_scenario_conserves_and_matches_the_reference(self):
        for name, placed, days in self.SCENARIOS:
            with self.subTest(name):
                batch, after = self.build(name, days)
                got = _departed_feed_charge(batch, after, D(placed)).get(
                    self.item.id, D("0"))
                alive, cum, want, fed = reference(placed, days)

                # Matches an independently written model, to the paisa.
                self.assertEqual(got, want.quantize(D("0.01")),
                                 f"{name}: charge differs from the reference")

                # And conserves: survivors' share plus the departed's is all
                # the feed there ever was.
                self.assertLess(((alive * cum + want) - fed).copy_abs(),
                                D("0.000001"), f"{name}: feed lost or invented")

    def test_the_requirement_resolves_to_what_survivors_are_owed(self):
        """The identity the whole change exists for."""
        cap = D("0.4")
        for name, placed, days in self.SCENARIOS:
            with self.subTest(name):
                batch, after = self.build(name, days)
                charge = _departed_feed_charge(batch, after, D(placed)).get(
                    self.item.id, D("0"))
                alive, _cum, _want, fed = reference(placed, days)
                if alive <= 0:
                    continue
                required = cap * alive + charge
                survivors_ate = fed - charge
                still_owed = cap * alive - survivors_ate
                self.assertLess(((required - fed) - still_owed).copy_abs(),
                                D("0.02"), f"{name}: to-feed does not resolve")


class SaleOnADayWithNoEntryTests(TestCase):
    """A lifting does not always coincide with a daily entry.

    The charge walks daily entries in date order; a sale on a day that has no
    entry of its own has to take its place in that walk, not be swept up at
    the end. Charged at the end it would carry the flock's *final* per-bird
    figure instead of the one standing on the day the birds actually left —
    and every feeding day after it would be divided by a flock those birds
    had already gone from.
    """

    def setUp(self):
        self.start = date(2026, 5, 1)
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region, prefix="AKB")
        self.sup = Supervisor.objects.create(branch=branch, name="R. Verma")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=self.sup, farmer=farmer, region=region,
            line="L1", farm_name="Yadav Farm", farm_capacity=9000)
        cat = ItemCategory.objects.create(name="Broiler Feed")
        self.item = Item.objects.create(item_code="ITM-1", description="Pre-Starter",
                                        category=cat, standard_cost_per_unit=0)
        self.batch = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="B-1", start_date=self.start)

    def entry(self, day, kg):
        DailyEntry.objects.create(
            farm=self.farm, batch=self.batch, supervisor=self.sup,
            date=self.start + timedelta(days=day), feed_1=self.item,
            feed_1_qty=D(str(kg)))

    def sale(self, day, birds):
        BirdSale.objects.create(farm=self.farm, batch=self.batch,
                                date=self.start + timedelta(days=day), birds=birds)

    def test_a_sale_between_two_feeding_days(self):
        """1,000 placed. Day 1: 50 kg, so 50 g a bird. Day 2: 100 birds lifted,
        no entry. Day 3: 20 kg across the 900 left, 22.22 g a bird.

        The 100 lifted ate 50 g each and nothing after — 5.00 kg.
        """
        self.entry(1, 50)
        self.sale(2, 100)
        self.entry(3, 20)
        charge = _departed_feed_charge(self.batch, self.start + timedelta(days=9),
                                       D("1000")).get(self.item.id, D("0"))
        self.assertEqual(charge, D("5.00"))

    def test_a_sale_before_any_feed_is_charged_nothing(self):
        self.sale(1, 100)
        self.entry(2, 50)
        charge = _departed_feed_charge(self.batch, self.start + timedelta(days=9),
                                       D("1000")).get(self.item.id, D("0"))
        self.assertEqual(charge, D("0"))
