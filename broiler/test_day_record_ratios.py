"""FCR and CFCR on the Detailed Daily Entry register.

Both are feed over weight; the row is a position on a day, so both readings it
needs are taken as at that day.

Two things were wrong. A row read the body weight off its own entry, so a day
nobody weighed the birds on valued the whole standing flock at nothing and took
every ratio down with it. And the mortality weight charged every bird that had
ever died at *today's* weight — a chick lost in week one billed as a finished
carcass — which put this register's CFCR at 1.55 where the costing engine, the
Live Flock Summary and the Production Cost report all say 1.66 for the same
flock on the same day.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from broiler.models import (BirdSale, Branch, BroilerBatch, BroilerFarm,
                            DailyEntry, Farmer, Region, Supervisor)
from broiler.views import (_day_record_row, chick_items, feed_items,
                           _flock_weight_readings)
from inventory.models import Item, ItemCategory, StockTransfer, Warehouse


class DayRecordRatioTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region,
                                       prefix="AKB")
        self.sup = Supervisor.objects.create(branch=branch, name="R. Verma")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=self.sup, farmer=farmer, region=region,
            line="L1", farm_name="Yadav Farm", farm_capacity=9000)
        self.batch = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="B-1",
            start_date=self.today - timedelta(days=40))

        feed_cat = ItemCategory.objects.create(name="Broiler Feed")
        self.feed = Item.objects.create(item_code="FD-1", description="Starter Feed",
                                        category=feed_cat, standard_cost_per_unit=0)
        chick_cat = ItemCategory.objects.create(name="Day Old Chicks")
        self.chick = Item.objects.create(item_code="CHK-1", description="Day Old Chick",
                                         category=chick_cat, standard_cost_per_unit=0)
        self.store = Warehouse.objects.create(name="Store")
        StockTransfer.objects.create(
            date=self.batch.start_date, item=self.chick, quantity=1000,
            from_location_type="warehouse", from_warehouse=self.store,
            to_location_type="farm", to_farm=self.farm, to_batch=self.batch)

        self.feed_ids = list(feed_items().values_list("id", flat=True))
        self.chick_ids = list(chick_items().values_list("id", flat=True))

    # ---- fixtures -----------------------------------------------------------

    def day(self, days_ago, feed=0, mortality=0, grams=None):
        return DailyEntry.objects.create(
            farm=self.farm, batch=self.batch, supervisor=self.sup,
            date=self.today - timedelta(days=days_ago),
            feed_1=self.feed if feed else None, feed_1_qty=Decimal(str(feed)),
            mortality=mortality,
            avg_weight_gms=Decimal(str(grams)) if grams is not None else Decimal("0"))

    def sell(self, days_ago, birds, weight):
        return BirdSale.objects.create(
            farm=self.farm, batch=self.batch,
            date=self.today - timedelta(days=days_ago),
            birds=birds, net_weight=Decimal(weight))

    def row(self, entry):
        return _day_record_row(entry, entry.date, self.feed_ids, self.chick_ids,
                               {}, StockTransfer, BirdSale, {}, {})

    # ---- the body weight a row reads ---------------------------------------

    def test_a_day_with_no_weighing_carries_the_last_one_forward(self):
        """Read off the row alone, an unweighed day valued the flock at nothing
        and printed a ratio to match."""
        self.day(5, feed=100, grams=1000)
        blank = self.day(4, feed=100)
        r = self.row(blank)
        # 1,000 birds still at a kilo apiece; 200 kg of feed against 1,000 kg.
        self.assertEqual(r["fcr"], Decimal("0.200"))

    def test_a_weighing_of_its_own_wins_over_the_one_before(self):
        self.day(5, feed=100, grams=1000)
        today = self.day(4, feed=100, grams=1200)
        self.assertEqual(self.row(today)["fcr"], Decimal("0.167"))   # 200 / 1200

    def test_a_lifting_since_the_last_weighing_values_the_rest(self):
        """Same rule as the summary and the cost report: the later reading."""
        self.day(9, feed=1000, grams=1000)
        self.sell(3, 200, "440.00")                     # 2.20 kg a bird
        after = self.day(1, feed=100)
        r = self.row(after)
        # 800 standing at 2.20 = 1,760, plus 440 sold = 2,200 kg.
        self.assertEqual(r["fcr"], Decimal("0.500"))    # 1,100 / 2,200

    def test_a_weighing_after_a_lifting_takes_over_again(self):
        self.day(9, feed=1000, grams=1000)
        self.sell(5, 200, "440.00")
        after = self.day(1, feed=100, grams=2400)
        # 800 at 2.40 = 1,920 plus 440 sold = 2,360.
        self.assertEqual(self.row(after)["fcr"],
                         (Decimal("1100") / Decimal("2360")).quantize(Decimal("0.001")))

    # ---- what the birds that died weighed -----------------------------------

    def test_each_day_s_deaths_are_charged_at_that_day_s_weight(self):
        """A chick lost in week one is not a finished carcass."""
        self.day(30, feed=100, mortality=100, grams=100)      # 10 kg of chicks
        last = self.day(2, feed=900, mortality=0, grams=2000)
        _per_bird, mort = _flock_weight_readings(self.batch, {})
        self.assertEqual(mort[-1][1], Decimal("10.0"))

        r = self.row(last)
        # 900 birds at 2 kg = 1,800; feed 1,000; mortality weight 10.
        self.assertEqual(r["fcr"], Decimal("0.556"))
        self.assertEqual(r["cfcr"], Decimal("0.552"))

    def test_the_correction_never_makes_the_ratio_worse(self):
        self.day(20, feed=500, mortality=30, grams=800)
        last = self.day(1, feed=500, mortality=5, grams=1900)
        r = self.row(last)
        self.assertLess(r["cfcr"], r["fcr"])

    def test_both_ratios_are_read_to_three_places(self):
        self.day(3, feed=100, grams=1000)
        r = self.row(self.day(1, feed=100, grams=1000))
        self.assertEqual(r["fcr"].as_tuple().exponent, -3)
        self.assertEqual(r["cfcr"].as_tuple().exponent, -3)

    # ---- and the register agrees with the rest of the ERP --------------------

    def test_the_last_row_matches_the_costing_engine(self):
        """The register, the summary and the cost report are three views of one
        flock and cannot hold three opinions about its feed conversion."""
        from broiler.views import _build_batch_report

        self.day(30, feed=400, mortality=100, grams=100)
        self.day(10, feed=600, mortality=20, grams=1500)
        last = self.day(1, feed=0, grams=2000)
        self.sell(1, 880, "1760.00")

        row = self.row(last)
        bc = (_build_batch_report(self.batch) or {}).get("batch_costing") or {}
        # The engine keeps two places and the register three, so they are
        # compared where they both speak: 0.556 against 0.56.
        self.assertEqual(row["cfcr"].quantize(Decimal("0.01")),
                         Decimal(str(bc["cfcr"])))
        self.assertEqual(row["fcr"].quantize(Decimal("0.01")),
                         Decimal(str(bc["fcr"])))
