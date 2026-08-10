"""What the Feed Scheduling report says when it cannot schedule.

Run against real data the report was blank across every live flock: each one
carried "No feed programme", and the By Feed Type panel — the sheet a buyer
orders from — reported "Still To Send: -3008.08 Kg", which reads as three
tonnes over-delivered. Neither was true. A programme existed and matched the
breed exactly; its effective window had ended nine days earlier, and with no
requirement to subtract from, deliveries turned into a confident negative.

So: name the cause, and withhold every figure derived from a requirement
nobody has worked out.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from broiler.models import (Branch, Breed, BroilerBatch, BroilerFarm, Farmer,
                            FeedPhaseMaster, Region, Supervisor)
from broiler.views import _feed_programme_gap


class ProgrammeGapTests(TestCase):
    """The sentence that says what to go and fix."""

    def setUp(self):
        self.today = date(2026, 8, 10)
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region, prefix="AKB")
        sup = Supervisor.objects.create(branch=branch, name="R. Verma")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=sup, farmer=farmer, region=region,
            line="L1", farm_name="Yadav Farm", farm_capacity=5000)
        self.breed = Breed.objects.create(description="Broiler COBB 430")
        self.batch = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="B-1", breed=self.breed,
            start_date=self.today - timedelta(days=10))

    def master(self, **over):
        row = dict(breed=self.breed, status="active")
        row.update(over)
        return FeedPhaseMaster.objects.create(**row)

    def test_an_expired_window_is_named_with_its_date(self):
        """The one that sent people hunting for a master that already existed."""
        self.master(effective_from=date(2026, 4, 1), effective_to=date(2026, 7, 31))
        gap = _feed_programme_gap(self.batch, self.today, list(FeedPhaseMaster.objects.all()))
        self.assertIn("expired", gap)
        self.assertIn("31.07.2026", gap)

    def test_a_window_not_yet_open_says_when_it_starts(self):
        self.master(effective_from=date(2026, 9, 1))
        gap = _feed_programme_gap(self.batch, self.today, list(FeedPhaseMaster.objects.all()))
        self.assertIn("starts", gap)
        self.assertIn("01.09.2026", gap)

    def test_no_master_for_the_breed_names_the_breed(self):
        other = Breed.objects.create(description="Layer Brown")
        self.master(breed=other)
        gap = _feed_programme_gap(self.batch, self.today, list(FeedPhaseMaster.objects.all()))
        self.assertIn("Broiler COBB 430", gap)

    def test_a_batch_with_no_breed_says_so(self):
        self.batch.breed = None
        gap = _feed_programme_gap(self.batch, self.today, [])
        self.assertIn("no breed", gap)

    def test_the_three_causes_do_not_share_a_sentence(self):
        """Each needs a different record fixed by a different person."""
        self.master(effective_from=date(2026, 4, 1), effective_to=date(2026, 7, 31))
        masters = list(FeedPhaseMaster.objects.all())
        expired = _feed_programme_gap(self.batch, self.today, masters)
        no_breed_batch = BroilerBatch(broiler_farm=self.farm, batch_name="B-2")
        none_set = _feed_programme_gap(no_breed_batch, self.today, masters)
        self.assertNotEqual(expired, none_set)


class UnknownRequirementTests(TestCase):
    """A requirement nobody worked out is not a requirement of zero."""

    def setUp(self):
        self.today = timezone.localdate()
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region, prefix="AKB")
        sup = Supervisor.objects.create(branch=branch, name="R. Verma")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=sup, farmer=farmer, region=region,
            line="L1", farm_name="Yadav Farm", farm_capacity=5000)
        breed = Breed.objects.create(description="Broiler COBB 430")
        self.batch = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="B-1", breed=breed,
            start_date=self.today - timedelta(days=10))

        User = get_user_model()
        self.user = User.objects.create_superuser("fs", "fs@x.com", "Str0ngPass!")
        self.client.force_login(self.user)

    def report(self, **params):
        params.setdefault("submit", "1")
        params.setdefault("status", "live")
        return self.client.get(reverse("batch_wise_feed_scheduling_report"), params)

    def test_still_to_send_is_withheld_rather_than_guessed(self):
        res = self.report()
        for feed in res.context["feed_summary"]:
            self.assertFalse(feed["has_req"])
            self.assertIsNone(feed["to_send"],
                              "a requirement of zero must not become a negative to-send")
            self.assertIsNone(feed["short_by"])

    def test_the_grand_total_says_unknown_not_nothing_needed(self):
        totals = self.report().context["totals"]
        self.assertFalse(totals["has_req"])
        self.assertIsNone(totals["req_qty"])

    def test_the_page_prints_a_dash_not_a_negative(self):
        html = self.report().content.decode()
        self.assertNotIn("-3008", html)
        self.assertIn("No feed programme applies", html)


class HorizonTests(TestCase):
    """Three days answers "what is urgent"; a buyer orders for the week."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_superuser("fs2", "fs2@x.com", "Str0ngPass!")
        self.client.force_login(self.user)

    def report(self, **params):
        params.setdefault("submit", "1")
        return self.client.get(reverse("batch_wise_feed_scheduling_report"), params)

    def test_it_defaults_to_three_days(self):
        self.assertEqual(self.report().context["horizon"], 3)

    def test_it_takes_the_week_and_the_fortnight(self):
        self.assertEqual(self.report(horizon=7).context["horizon"], 7)
        self.assertEqual(self.report(horizon=14).context["horizon"], 14)

    def test_a_value_nobody_offers_falls_back_rather_than_erroring(self):
        """The horizon reaches arithmetic, so it cannot be taken on trust."""
        self.assertEqual(self.report(horizon=999).context["horizon"], 3)
        self.assertEqual(self.report(horizon="week").context["horizon"], 3)
        self.assertEqual(self.report(horizon="").context["horizon"], 3)

    def test_the_heading_names_the_period_it_was_run_for(self):
        self.assertIn("Next 7 Days", self.report(horizon=7).content.decode())

    def test_the_export_heading_names_it_too(self):
        """The sheet outlives the screen; a quantity with no stated period is
        one nobody can order against."""
        res = self.report(horizon=14, export="csv")
        header = res.content.decode().splitlines()[0]
        self.assertIn("Next 14 Days", header)
        self.assertNotIn("Next N Days", header)
