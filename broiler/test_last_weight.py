"""The previous weighing, reported beside the box asking for today's.

A bird is weighed every few days rather than daily, and the box on its own
asks for a figure with nothing to weigh it against: "40 g" says nothing
without knowing the flock was 38 g four days ago, which is the growth the
entry is really recording. The supervisor standing at the shed has no other
way to recall it.

Both clients read this from the same lookup, so the phone and the web form
cannot disagree about what the last weight was.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from broiler.models import (Branch, BroilerBatch, BroilerFarm, DailyEntry,
                            Farmer, Region, Supervisor)
from broiler.views import daily_entry_lookup_payload


class LastWeightTests(TestCase):
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
            start_date=self.today - timedelta(days=20))

    def weigh(self, days_ago, grams):
        return DailyEntry.objects.create(
            farm=self.farm, batch=self.batch, supervisor=self.sup,
            date=self.today - timedelta(days=days_ago),
            avg_weight_gms=Decimal(str(grams)))

    def lookup(self, on=None):
        return daily_entry_lookup_payload(
            str(self.farm.id), (on or self.today).isoformat())

    def test_the_last_weighing_is_reported_with_its_date(self):
        self.weigh(4, 380)
        payload = self.lookup()
        self.assertEqual(payload["last_weight_g"], "380.00")
        self.assertEqual(payload["last_weight_date"],
                         (self.today - timedelta(days=4)).isoformat())

    def test_the_most_recent_of_several_wins(self):
        self.weigh(10, 150)
        self.weigh(6, 260)
        self.weigh(2, 410)
        self.assertEqual(self.lookup()["last_weight_g"], "410.00")

    def test_days_with_no_weighing_are_skipped(self):
        """A weight is taken every few days; the days between carry only
        mortality and feed, and must not report a last weight of zero."""
        self.weigh(8, 300)
        DailyEntry.objects.create(farm=self.farm, batch=self.batch,
                                  supervisor=self.sup,
                                  date=self.today - timedelta(days=1),
                                  mortality=5)
        self.assertEqual(self.lookup()["last_weight_g"], "300.00")

    def test_a_later_weighing_is_not_reported(self):
        """Backfilling an older day must not show a weight from the future."""
        self.weigh(1, 500)
        payload = self.lookup(on=self.today - timedelta(days=5))
        self.assertIsNone(payload["last_weight_g"])

    def test_the_row_being_written_is_not_its_own_last_weight(self):
        self.weigh(0, 420)
        self.assertIsNone(self.lookup()["last_weight_g"])

    def test_a_never_weighed_flock_reports_nothing(self):
        payload = self.lookup()
        self.assertIsNone(payload["last_weight_g"])
        self.assertIsNone(payload["last_weight_date"])

    def test_another_flock_on_the_same_farm_does_not_leak_in(self):
        """A farm running two sheds weighs each separately, and a 40 g chick
        must not be shown the 1.8 kg of the flock next door."""
        other = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="B-2",
            start_date=self.today - timedelta(days=3))
        DailyEntry.objects.create(farm=self.farm, batch=other,
                                  supervisor=self.sup,
                                  date=self.today - timedelta(days=1),
                                  avg_weight_gms=Decimal("1800"))
        self.weigh(2, 420)
        payload = daily_entry_lookup_payload(
            str(self.farm.id), self.today.isoformat(), str(self.batch.id))
        self.assertEqual(payload["last_weight_g"], "420.00")
