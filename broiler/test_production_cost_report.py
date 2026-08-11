"""Production Cost — where the money went, and whether it was too much.

The Profit & Loss page is busy with revenue and cannot answer either question
plainly. This report only ever looks at the cost side, and every figure on it
comes from the same batch report and the same P&L service, so a flock's feed
cost is one number across the ERP rather than two that nearly agree.

The variance is the part worth testing hardest: it is a price variance on real
consumption — the item master's standard rate applied to what was actually
eaten — and it has to say so rather than quietly excluding what it could not
price.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from broiler.models import (BirdCategory, Branch, Breed, BroilerBatch,
                            BroilerFarm, DailyEntry, Farmer, Region, Supervisor)
from broiler.services.production_cost import (build_production_cost,
                                              cost_rows_from_pl,
                                              standard_consumption_cost)
from inventory.models import Item, ItemCategory


class StandardCostTests(TestCase):
    """Consumption re-costed at the item master's rate."""

    def setUp(self):
        feed = ItemCategory.objects.create(name="Broiler Feed")
        self.pre = Item.objects.create(item_code="ITM-1", description="Pre-Starter",
                                       category=feed, standard_cost_per_unit=Decimal("30"))
        self.free = Item.objects.create(item_code="ITM-2", description="Unrated Feed",
                                        category=feed, standard_cost_per_unit=Decimal("0"))

    def test_quantity_times_the_master_rate(self):
        total, missing = standard_consumption_cost(
            [{"item_id": self.pre.id, "quantity": Decimal("100"), "name": "Pre-Starter"}])
        self.assertEqual(total, Decimal("3000.00"))
        self.assertEqual(missing, set())

    def test_an_item_with_no_standard_is_named_not_treated_as_free(self):
        """A total that silently drops a line reads as a cheaper flock."""
        total, missing = standard_consumption_cost(
            [{"item_id": self.pre.id, "quantity": Decimal("10"), "name": "Pre-Starter"},
             {"item_id": self.free.id, "quantity": Decimal("500"), "name": "Unrated Feed"}])
        self.assertEqual(total, Decimal("300.00"))
        self.assertEqual(missing, {"Unrated Feed"})

    def test_consumption_of_nothing_costs_nothing(self):
        self.assertEqual(standard_consumption_cost([]), (Decimal("0.00"), set()))


class CostComponentTests(TestCase):
    def test_hand_entered_blocks_are_split_back_into_their_heads(self):
        """"Growing Expenses ₹1.65 L" hides which of labour, electricity or
        diesel actually moved."""
        pl = {"cost_blocks": [
            {"title": "Feed Cost", "total": Decimal("100"), "lines": []},
            {"title": "Growing Expenses", "total": Decimal("30"), "lines": [
                {"label": "Labour", "amount": Decimal("20")},
                {"label": "Diesel", "amount": Decimal("10")},
                {"label": "Water", "amount": None},
            ]},
        ]}
        self.assertEqual(cost_rows_from_pl(pl),
                         [("Feed Cost", Decimal("100")),
                          ("Labour", Decimal("20")), ("Diesel", Decimal("10"))])

    def test_a_block_nobody_filled_in_contributes_nothing(self):
        pl = {"cost_blocks": [{"title": "Administrative Cost", "total": None,
                               "lines": [{"label": "Depreciation", "amount": None}]}]}
        self.assertEqual(cost_rows_from_pl(pl), [])


class SummaryTests(TestCase):
    """The aggregate the page is read from."""

    def row(self, **over):
        row = {
            "placed": Decimal("1000"), "live_birds": Decimal("900"),
            "mortality": Decimal("100"), "weight": Decimal("2000"),
            "feed_kg": Decimal("3200"), "total_cost": Decimal("90000"),
            "std_cost": Decimal("100000"), "feed_cost": Decimal("60000"),
            "std_feed_cost": Decimal("70000"), "sale_value": Decimal("120000"),
            "chick_cost": Decimal("30000"), "medicine_cost": Decimal("0"),
            "growing_cost": None, "admin_cost": None,
            "sub_total": Decimal("90000"),
            "sold_birds": Decimal("900"), "std_fcr": Decimal("1.60"),
            "components": [("Feed Cost", Decimal("60000")),
                           ("Chick Cost", Decimal("30000"))],
            "unpriced": set(), "no_standard": set(),
        }
        row.update(over)
        return row

    def test_a_saving_reads_as_a_negative_variance(self):
        s = build_production_cost([self.row()])
        self.assertEqual(s["variance"], Decimal("-10000.00"))
        self.assertEqual(s["variance_pct"], Decimal("-10.00"))

    def test_components_are_ordered_largest_first(self):
        """The chart answers "where did it go", and that is read from the top."""
        heads = [c["head"] for c in build_production_cost([self.row()])["components"]]
        self.assertEqual(heads, ["Feed Cost", "Chick Cost"])

    def test_component_shares_are_of_the_total(self):
        by_head = {c["head"]: c["pct"]
                   for c in build_production_cost([self.row()])["components"]}
        self.assertEqual(by_head["Feed Cost"], Decimal("66.67"))

    def test_fcr_is_weighted_not_averaged_across_flocks(self):
        """Averaging ratios lets a 200 kg flock pull as hard as a 23,000 kg one."""
        small = self.row(feed_kg=Decimal("400"), weight=Decimal("200"))
        big = self.row(feed_kg=Decimal("32000"), weight=Decimal("20000"))
        s = build_production_cost([small, big])
        self.assertEqual(s["fcr"], Decimal("1.60"))      # 32400 / 20200
        self.assertNotEqual(s["fcr"], Decimal("1.80"))   # the mean of 2.00 and 1.60

    def test_a_ratio_with_no_denominator_is_none_not_zero(self):
        """A cost per kilo on a flock that has sold nothing is not ₹0.00."""
        s = build_production_cost([self.row(weight=Decimal("0"))])
        self.assertIsNone(s["cost_per_kg"])
        self.assertIsNone(s["std_cost_per_kg"])
        self.assertIsNone(s["variance_per_kg"])

    def test_what_could_not_be_priced_is_carried_up_to_the_page(self):
        """A variance computed over incomplete consumption must not read as a
        saving without saying what is missing."""
        s = build_production_cost([self.row(unpriced={"Starter"},
                                            no_standard={"Vitamin B"})])
        self.assertEqual(s["unpriced"], ["Starter"])
        self.assertEqual(s["no_standard"], ["Vitamin B"])

    def test_the_block_columns_add_up_to_the_total(self):
        """Five columns, not "Feed and Other": what the money went on has to
        reconcile rather than leave a remainder nobody can account for."""
        s = build_production_cost([self.row(
            chick_cost=Decimal("25000"), medicine_cost=Decimal("5000"),
            growing_cost=Decimal("0"), admin_cost=None)])
        parts = sum(v for v in (s["chick_cost"], s["feed_cost"], s["medicine_cost"],
                                s["growing_cost"], s["admin_cost"]) if v is not None)
        self.assertEqual(parts, s["total_cost"])

    def test_growing_is_added_after_the_sub_total_not_inside_it(self):
        """The Cost group sub-totals the four blocks under it; Growing is a
        column of its own further right, and the grand total takes both."""
        s = build_production_cost([self.row(
            sub_total=Decimal("80000"), growing_cost=Decimal("10000"),
            total_cost=Decimal("90000"))])
        self.assertEqual(s["sub_total"], Decimal("80000.00"))
        self.assertEqual(s["sub_total"] + s["growing_cost"], s["total_cost"])

    def test_a_block_no_flock_has_filled_in_totals_to_none(self):
        s = build_production_cost([self.row(admin_cost=None)])
        self.assertIsNone(s["admin_cost"])

    def test_the_feed_side_is_split_out_of_the_standard_too(self):
        s = build_production_cost([self.row()])
        self.assertEqual(s["std_feed_cost"], Decimal("70000.00"))
        self.assertEqual(s["feed_variance"], Decimal("-10000.00"))
        self.assertEqual(s["feed_cost_pct"], Decimal("66.67"))


class PageTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region, prefix="AKB")
        sup = Supervisor.objects.create(branch=branch, name="R. Verma")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=sup, farmer=farmer, region=region,
            line="L1", farm_name="Yadav Farm", farm_capacity=5000)
        # A data migration already seeds the standard categories.
        cat, _ = BirdCategory.objects.get_or_create(name="Broiler")
        self.breed = Breed.objects.create(description="COBB 430", bird_category=cat)
        self.batch = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="B-1", breed=self.breed,
            start_date=self.today - timedelta(days=20))

        User = get_user_model()
        self.user = User.objects.create_superuser("pc", "pc@x.com", "Str0ngPass!")
        self.client.force_login(self.user)

    def page(self, **params):
        params.setdefault("from_date", (self.today - timedelta(days=365)).isoformat())
        params.setdefault("to_date", self.today.isoformat())
        return self.client.get(reverse("production_cost_report"), params)

    def test_it_opens_without_choosing_anything(self):
        self.assertEqual(self.page().status_code, 200)

    def test_it_lists_every_flock_running_in_the_window(self):
        rows = self.page().context["rows"]
        self.assertEqual([r["batch"].id for r in rows], [self.batch.id])

    def test_a_flock_that_finished_before_the_window_is_left_out(self):
        old = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="B-OLD", breed=self.breed,
            start_date=self.today - timedelta(days=200), is_closed=True,
            end_date=self.today - timedelta(days=150))
        ids = [r["batch"].id for r in
               self.page(from_date=(self.today - timedelta(days=60)).isoformat())
               .context["rows"]]
        self.assertNotIn(old.id, ids)

    def test_a_flock_placed_before_the_window_but_still_running_is_included(self):
        """A cost report filtered to flocks that merely started inside the
        month would drop every batch the month was actually spent on."""
        ids = [r["batch"].id for r in
               self.page(from_date=(self.today - timedelta(days=2)).isoformat())
               .context["rows"]]
        self.assertIn(self.batch.id, ids)

    def test_the_bird_type_filter_uses_the_breed_s_category(self):
        other, _ = BirdCategory.objects.get_or_create(name="Layer")
        self.assertEqual(len(self.page(bird_type=other.id).context["rows"]), 0)
        self.assertEqual(len(self.page(bird_type=self.breed.bird_category_id)
                             .context["rows"]), 1)

    def test_the_drawer_is_served_with_the_page_not_fetched_again(self):
        """What the drawer shows and what the row shows cannot drift apart."""
        detail = self.page().context["pc_json"]
        self.assertIn(str(self.batch.id), detail)
        self.assertIn("components", detail[str(self.batch.id)])

    def test_money_reaches_the_drawer_as_strings(self):
        """JSON floats would round money on the way to a panel that shows it."""
        d = self.page().context["pc_json"][str(self.batch.id)]
        self.assertIsInstance(d["total_cost"], str)

    def test_an_empty_window_says_so_rather_than_erroring(self):
        far = (self.today - timedelta(days=3650)).isoformat()
        res = self.page(from_date=far, to_date=far)
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(res.context["summary"])
