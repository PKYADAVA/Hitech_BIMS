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
from decimal import Decimal

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


class SummaryOrderTests(TestCase):
    """The oldest flock leads the summary, as it leads the cost report.

    It ran branch-alphabetical, which is an order about names rather than
    birds: a flock placed last week sat above one going out on Friday because
    its branch began with an earlier letter.
    """

    def setUp(self):
        self.today = timezone.localdate()
        region = Region.objects.create(description="East")
        self.zed = Branch.objects.create(branch_name="Zzz Branch", region=region,
                                         prefix="ZZZ")
        self.acme = Branch.objects.create(branch_name="Acme Branch", region=region,
                                          prefix="ACM")
        self.farmer = Farmer.objects.create(farmer_name="S. Yadav")
        User = get_user_model()
        self.user = User.objects.create_superuser("lfs", "lfs@x.com", "Str0ngPass!")
        self.client.force_login(self.user)

    def flock(self, branch, name, age):
        sup = Supervisor.objects.create(branch=branch, name=f"S {name}")
        farm = BroilerFarm.objects.create(
            branch=branch, supervisor=sup, farmer=self.farmer,
            region=branch.region, line="L1", farm_name=f"Farm {name}",
            farm_capacity=5000)
        return BroilerBatch.objects.create(
            broiler_farm=farm, batch_name=name,
            start_date=self.today - timedelta(days=age) if age is not None else None)

    def rows(self):
        return self.client.get(reverse("live_flock_summary_report")).context["rows"]

    def test_the_oldest_flock_leads_whatever_its_branch_is_called(self):
        self.flock(self.acme, "young", age=5)
        self.flock(self.zed, "old", age=80)
        self.assertEqual([r["batch"] for r in self.rows()], ["old", "young"])

    def test_ages_read_down_the_page(self):
        for name, age in (("a", 12), ("b", 40), ("c", 3)):
            self.flock(self.acme, name, age)
        ages = [r["actual_age"] for r in self.rows()]
        self.assertEqual(ages, sorted(ages, reverse=True))

    def test_a_flock_with_no_placement_goes_last(self):
        self.flock(self.acme, "dated", age=10)
        self.flock(self.acme, "undated", age=None)
        self.assertEqual([r["batch"] for r in self.rows()][-1], "undated")


class StandingBirdValuationTests(TestCase):
    """What the birds still on the farm are worth, on the summary.

    A weighing is a hand-taken sample and is not always kept up: one flock on
    this data last recorded 82 g while lifting birds at 2.27 kg, and valuing
    what was still standing by that sample priced it at a twenty-seventh of its
    weight — which then ran through the FCR, the CFCR and the cost per kilo
    beside it.
    """

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
        self.place(1000)

    def place(self, chicks):
        from inventory.models import Item, ItemCategory, StockTransfer, Warehouse

        item, _ = Item.objects.get_or_create(
            item_code="CHK-001",
            defaults={"description": "Day Old Chick", "standard_cost_per_unit": 0,
                      "category": ItemCategory.objects.get_or_create(
                          name="Day Old Chicks")[0]})
        store, _ = Warehouse.objects.get_or_create(name="Store")
        StockTransfer.objects.create(
            date=self.batch.start_date, item=item, quantity=chicks,
            from_location_type="warehouse", from_warehouse=store,
            to_location_type="farm", to_farm=self.farm, to_batch=self.batch)

    def weigh(self, days_ago, grams):
        DailyEntry.objects.create(
            farm=self.farm, batch=self.batch, supervisor=self.sup,
            date=self.today - timedelta(days=days_ago),
            avg_weight_gms=Decimal(str(grams)))

    def sell(self, birds, weight, days_ago):
        from broiler.models import BirdSale

        BirdSale.objects.create(farm=self.farm, batch=self.batch,
                                date=self.today - timedelta(days=days_ago),
                                birds=birds, net_weight=Decimal(weight))

    def row(self):
        from broiler.views import _live_flock_row
        return _live_flock_row(self.batch, self.today)

    def test_a_lifting_since_the_last_weighing_values_them(self):
        self.weigh(9, 82)
        self.sell(200, "454.00", days_ago=1)          # 2.27 kg a bird
        r = self.row()
        self.assertEqual(r["available"], Decimal("800"))
        self.assertEqual(r["available_weight"], Decimal("1816.00"))
        # The column still reports the weighing itself.
        self.assertEqual(r["avg_bwt"], Decimal("82.00"))

    def test_a_weighing_since_the_last_lifting_values_them(self):
        self.sell(200, "340.00", days_ago=4)          # 1.70 kg a bird
        self.weigh(2, 1810)                           # then 1.81 kg on a scale
        self.assertEqual(self.row()["available_weight"], Decimal("1448.00"))

    def test_without_a_lifting_the_weighing_stands(self):
        self.weigh(2, 1500)
        self.assertEqual(self.row()["available_weight"], Decimal("1500.00"))

    def test_a_flock_with_neither_reading_is_not_given_a_weight(self):
        self.assertEqual(self.row()["available_weight"], Decimal("0.00"))
