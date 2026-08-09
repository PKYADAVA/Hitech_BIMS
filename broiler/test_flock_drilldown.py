"""From the Live Flock Summary into one flock's own register.

The summary says a flock is behind — a gap in the entries, an FCR drifting,
a body weight under standard. The next question is always which day it went
that way, and answering it meant leaving the report, opening the Detailed
Daily Entry Report, and setting the farm and the dates by hand. Worse, that
report had no batch filter at all, so a farm on its second flock of the year
returned both runs mixed together.

The batch name is now the way in, and the report can be read down to a single
flock.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from broiler.models import (Branch, BroilerBatch, BroilerFarm, DailyEntry,
                            Farmer, Region, Supervisor)


class BatchDrilldownTests(TestCase):
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
        # Two flocks on the one farm: the report used to mix their days.
        self.first = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="B-OLD",
            start_date=self.today - timedelta(days=60), is_closed=True,
            end_date=self.today - timedelta(days=20))
        self.second = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="B-NEW",
            start_date=self.today - timedelta(days=10))
        self.old_day = self.entry(self.first, 55, mortality=9)
        self.new_day = self.entry(self.second, 5, mortality=4)

        User = get_user_model()
        self.user = User.objects.create_superuser("drill", "d@x.com", "Str0ngPass!")
        self.client.force_login(self.user)

    def entry(self, batch, days_ago, **kw):
        return DailyEntry.objects.create(
            farm=self.farm, batch=batch, supervisor=self.sup,
            date=self.today - timedelta(days=days_ago), **kw)

    def report(self, **params):
        params.setdefault("from_date", (self.today - timedelta(days=365)).isoformat())
        params.setdefault("to_date", self.today.isoformat())
        return self.client.get(
            reverse("farm_detailed_daily_entry_report"), params)

    # ---- the register can be read down to one flock -------------------------

    def test_a_batch_narrows_the_register_to_that_flock(self):
        res = self.report(farm=self.farm.id, batch=self.second.id)
        dates = [r["entry_date"] for r in res.context["rows"]]
        self.assertEqual(dates, [self.new_day.date])

    def test_without_a_batch_the_farm_still_reports_every_flock(self):
        res = self.report(farm=self.farm.id)
        self.assertEqual(len(res.context["rows"]), 2)

    def test_a_closed_flock_can_still_be_read(self):
        """The link is offered on live flocks, but the filter must not refuse
        a batch that has since been closed — a report is read after the fact."""
        res = self.report(farm=self.farm.id, batch=self.first.id)
        self.assertEqual([r["entry_date"] for r in res.context["rows"]],
                         [self.old_day.date])

    def test_the_batch_choices_are_the_chosen_farm_s_own(self):
        res = self.report(farm=self.farm.id)
        self.assertEqual({b.id for b in res.context["batches"]},
                         {self.first.id, self.second.id})

    def test_no_batch_list_is_offered_before_a_farm_is_chosen(self):
        """The unfiltered list runs to thousands and nothing in it would be
        a valid choice on its own."""
        self.assertEqual(list(self.report().context["batches"]), [])

    def test_a_batch_from_another_farm_yields_nothing_rather_than_leaking(self):
        other_farm = BroilerFarm.objects.create(
            branch=self.farm.branch, supervisor=self.sup, farmer=self.farm.farmer,
            region=self.farm.region, line="L1", farm_name="Other Farm",
            farm_capacity=5000)
        res = self.report(farm=other_farm.id, batch=self.second.id)
        self.assertEqual(res.context["rows"], [])

    # ---- the way in ---------------------------------------------------------

    def test_the_summary_links_each_flock_to_its_register(self):
        res = self.client.get(reverse("live_flock_summary_report"))
        html = res.content.decode()
        self.assertIn(f"farm={self.farm.id}&amp;batch={self.second.id}", html)

    def test_the_link_opens_a_new_tab(self):
        """The summary is read across the fleet and a flock is checked out of
        it — losing the scroll and the filters to come back would cost more
        than the drill-down."""
        html = self.client.get(reverse("live_flock_summary_report")).content.decode()
        self.assertIn('target="_blank"', html)
        self.assertIn('rel="noopener"', html)

    def test_the_link_is_dated_from_placement_so_the_whole_run_shows(self):
        res = self.client.get(reverse("live_flock_summary_report"))
        html = res.content.decode()
        self.assertIn(f"from_date={self.second.start_date:%Y-%m-%d}", html)
        self.assertIn(f"to_date={self.today:%Y-%m-%d}", html)

    def test_the_row_carries_the_ids_the_link_needs(self):
        res = self.client.get(reverse("live_flock_summary_report"))
        row = next(r for r in res.context["rows"] if r["batch"] == "B-NEW")
        self.assertEqual(row["batch_id"], self.second.id)
        self.assertEqual(row["farm_id"], self.farm.id)
