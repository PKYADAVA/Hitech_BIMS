"""What the advisory says when the breed standard cannot answer.

A breed's standards are rows at particular ages. Asked about an age the curve
does not cover, the lookup used to hand back its nearest row anyway — beyond
the top it was already guarded, but below the bottom it silently returned the
*first* row. A flock on day 12, against a breed whose standards start at day
20, was therefore measured against a 20-day-old bird and read as badly behind.

This is the real BRE-0003 shape: two rows, at ages 20 and 35.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from broiler.models import (Branch, BreedStandard, Breed, BroilerBatch,
                            BroilerFarm, Farmer, Region, Supervisor)
from broiler.views import _breed_standard_at, daily_entry_lookup_payload


class BreedStandardGapTests(TestCase):
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
        self.breed = Breed.objects.create(description="COBB 430")
        # The sparse curve that prompted this: nothing before day 20.
        for age, weight in ((20, 900), (35, 2200)):
            BreedStandard.objects.create(breed=self.breed, age=age,
                                         body_weight=weight, feed_intake=100,
                                         cum_feed=1000, fcr=1.5)

    def batch_aged(self, days):
        """A flock placed `days` ago, and the date on which it is that age."""
        BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="B%d" % days, breed=self.breed,
            start_date=self.today - timedelta(days=days))
        return self.today.isoformat()

    # ---- the lookup itself --------------------------------------------------

    def test_an_age_below_the_curve_has_no_standard(self):
        self.assertIsNone(_breed_standard_at(self.breed.id, 12))

    def test_an_age_on_the_curve_reads_its_row(self):
        self.assertEqual(_breed_standard_at(self.breed.id, 20).age, 20)

    def test_an_age_between_rows_carries_the_lower_one_forward(self):
        self.assertEqual(_breed_standard_at(self.breed.id, 30).age, 20)

    def test_an_age_above_the_curve_carries_the_last_row(self):
        self.assertEqual(_breed_standard_at(self.breed.id, 60).age, 35)

    # ---- what the form is told ----------------------------------------------

    def test_the_form_is_told_why_the_standard_is_blank(self):
        on = self.batch_aged(12)
        payload = daily_entry_lookup_payload(str(self.farm.id), on)
        self.assertIsNone(payload["std_weight_g"])
        self.assertIn("below age 20", payload["std_note"])

    def test_a_flock_inside_the_curve_gets_its_figures(self):
        on = self.batch_aged(25)
        payload = daily_entry_lookup_payload(str(self.farm.id), on)
        self.assertIsNone(payload["std_note"])
        self.assertIsNotNone(payload["std_weight_g"])

    def test_beyond_the_curve_is_still_flagged(self):
        on = self.batch_aged(60)
        self.assertIn("beyond age 35",
                      daily_entry_lookup_payload(str(self.farm.id), on)["std_note"])

    def test_a_breed_with_no_rows_at_all_says_so(self):
        bare = Breed.objects.create(description="Unmeasured")
        BroilerBatch.objects.create(broiler_farm=self.farm, batch_name="Bare",
                                    breed=bare,
                                    start_date=self.today - timedelta(days=5))
        self.assertIn("No breed standard for this breed",
                      daily_entry_lookup_payload(str(self.farm.id))["std_note"])
