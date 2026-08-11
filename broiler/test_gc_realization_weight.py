"""Avg Live Weight per Bird, before a flock has been lifted.

The figure came from ``sold_weight / sold_birds``, which is nothing until a
sale exists — so every live flock, which is the filter this report opens on,
showed 0.000 kg on both realization rows, and every ratio hanging off it read
as though the birds weighed nothing.

Until a real sale happens the honest figure is the last weighing taken on the
flock: what a supervisor would quote if asked what the birds weigh. A sale
supersedes it the moment one exists — a sale is a weighbridge, a weighing is
a sample.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from broiler.models import (Branch, BroilerBatch, BroilerFarm, DailyEntry,
                            Farmer, Region, Supervisor)


class AvgLiveWeightFallbackTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region,
                                       prefix="AKB")
        self.sup = Supervisor.objects.create(branch=branch, name="R. Verma")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=self.sup, farmer=farmer, region=region,
            line="L1", farm_name="Yadav Farm", farm_capacity=5000)
        self.batch = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="B-1",
            start_date=self.today - timedelta(days=30))

    def weigh(self, days_ago, grams):
        return DailyEntry.objects.create(
            farm=self.farm, batch=self.batch, supervisor=self.sup,
            date=self.today - timedelta(days=days_ago),
            avg_weight_gms=Decimal(str(grams)))

    def rows(self, **costing):
        """Build the realization rows over a stubbed batch costing, so the
        fallback is exercised without staging a whole flock's transactions."""
        from broiler.services.gc_realization import build_gc_realization

        bc = {"chicks_placed": Decimal("1000"), "sold_birds": Decimal("0"),
              "sold_weight": Decimal("0"), "avg_body_weight": Decimal("0"),
              "feed_consumed": Decimal("0"), "total_mort_pct": Decimal("0"),
              "mortality": Decimal("0"), "med_cost": Decimal("0"),
              "placement_date": self.today - timedelta(days=30)}
        bc.update(costing)
        report = {"batch_costing": bc}
        built = build_gc_realization(self.batch, report, report, None)
        return {r["key"]: r for r in built["scenarios"]}

    def weight_of(self, rows, key):
        return rows[key]["values"]["avg_live_weight"]

    def test_an_unlifted_flock_shows_its_last_weighing(self):
        self.weigh(2, 1800)
        rows = self.rows()
        self.assertEqual(self.weight_of(rows, "farmer"), Decimal("1.8000"))
        self.assertEqual(self.weight_of(rows, "management"), Decimal("1.8000"))

    def test_the_latest_weighing_wins(self):
        self.weigh(10, 900)
        self.weigh(2, 1800)
        self.assertEqual(self.weight_of(self.rows(), "farmer"), Decimal("1.8000"))

    def test_days_with_no_weighing_are_skipped(self):
        """A weight is taken every few days; the days between carry only
        mortality and feed, and must not report the flock at nothing."""
        self.weigh(6, 1500)
        DailyEntry.objects.create(farm=self.farm, batch=self.batch,
                                  supervisor=self.sup,
                                  date=self.today - timedelta(days=1),
                                  mortality=3)
        self.assertEqual(self.weight_of(self.rows(), "farmer"), Decimal("1.5000"))

    def test_a_real_sale_supersedes_the_weighing(self):
        """A sale is a weighbridge; a weighing is a sample."""
        self.weigh(2, 1800)
        rows = self.rows(sold_birds=Decimal("900"), sold_weight=Decimal("1980"),
                         avg_body_weight=Decimal("2.20"))
        self.assertEqual(self.weight_of(rows, "farmer"), Decimal("2.20"))

    def test_a_flock_never_weighed_still_reports_nothing(self):
        """No sale and no weighing is genuinely no figure — not invented."""
        self.assertEqual(self.weight_of(self.rows(), "farmer"), Decimal("0"))

    def test_another_flock_s_weighing_is_not_borrowed(self):
        other = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="B-2",
            start_date=self.today - timedelta(days=5))
        DailyEntry.objects.create(farm=self.farm, batch=other, supervisor=self.sup,
                                  date=self.today - timedelta(days=1),
                                  avg_weight_gms=Decimal("2500"))
        self.assertEqual(self.weight_of(self.rows(), "farmer"), Decimal("0"))

    def test_the_standard_row_is_left_alone(self):
        """Standard is the scheme's own target weight, not this flock's."""
        self.weigh(2, 1800)
        rows = self.rows()
        self.assertNotEqual(self.weight_of(rows, "standard"), Decimal("1.8000"))
