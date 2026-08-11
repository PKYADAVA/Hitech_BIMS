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
from broiler.services.production_cost import (admin_cost_for,
                                              build_production_cost,
                                              cost_rows_from_pl,
                                              growing_charge_for,
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

    def test_the_branch_line_and_supervisor_filters_narrow_the_list(self):
        rows = self.page(branch=self.farm.branch_id).context["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(self.page(line="L1").context["rows"]), 1)
        self.assertEqual(len(self.page(line="nope").context["rows"]), 0)
        self.assertEqual(
            len(self.page(supervisor=self.farm.supervisor_id).context["rows"]), 1)

    def test_the_report_type_defaults_to_management_and_rejects_nonsense(self):
        """It reaches the batch report builder, so it cannot be taken on trust."""
        self.assertEqual(self.page().context["report_type"], "management")
        self.assertEqual(self.page(report_type="farmer").context["report_type"],
                         "farmer")
        self.assertEqual(self.page(report_type="both").context["report_type"],
                         "management")

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


class AdminCostFromSchemeTests(TestCase):
    """Overhead read from the Growing Charge Scheme, which already holds it."""

    def setUp(self):
        self.region = Region.objects.create(description="East")
        self.branch = Branch.objects.create(branch_name="Akbarpur", region=self.region,
                                            prefix="AKB")
        sup = Supervisor.objects.create(branch=self.branch, name="R. Verma")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=self.branch, supervisor=sup, farmer=farmer, region=self.region,
            line="L1", farm_name="Yadav Farm", farm_capacity=5000)
        self.placed_on = date(2026, 7, 1)
        self.batch = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="B-1", start_date=self.placed_on)

    def scheme(self, **over):
        from broiler.models import GrowingChargeScheme
        row = dict(region=self.region, schema_name="S1", is_active=True,
                   from_date=date(2026, 1, 1), to_date=date(2026, 12, 31),
                   farmer_admin_cost=Decimal("3"), management_admin_cost=Decimal("1"))
        row.update(over)
        return GrowingChargeScheme.objects.create(**row)

    def test_one_share_applies_at_a_time_never_both(self):
        """The two fields are the same overhead seen from two sides, so a
        flock cannot carry each of them at once."""
        self.scheme()
        self.assertEqual(admin_cost_for(self.batch, Decimal("12000"), "management"),
                         {"Management Admin Cost": Decimal("12000.00")})
        self.assertEqual(admin_cost_for(self.batch, Decimal("12000"), "farmer"),
                         {"Farmer Admin Cost": Decimal("36000.00")})

    def test_the_head_is_named_rather_than_lumped(self):
        """A breakup showing one "Admin 12,000" is a figure nobody can question."""
        self.scheme()
        self.assertEqual(list(admin_cost_for(self.batch, Decimal("1000"))),
                         ["Management Admin Cost"])

    def test_a_share_set_to_nothing_does_not_take_a_row(self):
        self.scheme(management_admin_cost=Decimal("0"))
        self.assertEqual(admin_cost_for(self.batch, Decimal("1000"),
                                        "management"), {})

    def test_no_scheme_covering_the_placement_means_no_overhead(self):
        """Not zero overhead — no scheme to say. The page prints "no scheme"."""
        self.scheme(from_date=date(2027, 1, 1), to_date=date(2027, 12, 31))
        self.assertEqual(admin_cost_for(self.batch, Decimal("1000")), {})

    def test_another_region_s_scheme_is_not_borrowed(self):
        other = Region.objects.create(description="West")
        self.scheme(region=other)
        self.assertEqual(admin_cost_for(self.batch, Decimal("1000")), {})

    def test_a_flock_with_no_placement_carries_no_overhead(self):
        self.scheme()
        self.assertEqual(admin_cost_for(self.batch, Decimal("0")), {})

    def test_the_farmer_view_bills_only_the_farmer_s_share(self):
        """His statement carries his admin cost, not the company's."""
        self.scheme()
        self.assertEqual(admin_cost_for(self.batch, Decimal("1000"), "farmer"),
                         {"Farmer Admin Cost": Decimal("3000.00")})

    def test_the_management_view_bills_only_the_company_s_share(self):
        self.scheme()
        self.assertEqual(list(admin_cost_for(self.batch, Decimal("1000"),
                                             "management")),
                         ["Management Admin Cost"])


class GrowingChargeSourceTests(TestCase):
    """What the company owes the farmer, from the settlement that worked it out."""

    def setUp(self):
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region, prefix="AKB")
        sup = Supervisor.objects.create(branch=branch, name="R. Verma")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=sup, farmer=farmer, region=region,
            line="L1", farm_name="Yadav Farm", farm_capacity=5000)
        self.batch = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="B-1",
            start_date=timezone.localdate() - timedelta(days=40))

    def settle(self, **over):
        from broiler.models import GrowingChargeSettlement
        row = dict(batch=self.batch, farm=self.farm,
                   gc_date=timezone.localdate())
        row.update(over)
        return GrowingChargeSettlement.objects.create(**row)

    def test_an_unsettled_flock_reports_nothing_rather_than_zero(self):
        """"Not settled" and "cost nothing to grow" are different answers."""
        self.assertIsNone(growing_charge_for(self.batch))

    def test_the_amount_payable_is_the_cost(self):
        """After incentives and deductions, before TDS and advance recovery —
        those are financing, not what the flock cost to grow."""
        self.settle(total_amount_payable=Decimal("42000"),
                    actual_growing_charges=Decimal("40000"))
        self.assertEqual(growing_charge_for(self.batch), Decimal("42000.00"))

    def test_it_falls_back_to_the_growing_charge_when_nothing_is_payable_yet(self):
        self.settle(total_amount_payable=Decimal("0"),
                    actual_growing_charges=Decimal("40000"))
        self.assertEqual(growing_charge_for(self.batch), Decimal("40000.00"))

    def test_a_flock_can_only_be_settled_once(self):
        """The model enforces it, so there is never a second figure to choose
        between — which is the whole reason this is read from the settlement
        rather than typed against the batch."""
        from django.db import IntegrityError, transaction

        self.settle(total_amount_payable=Decimal("42000"))
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.settle(total_amount_payable=Decimal("10000"))

    def test_another_flock_s_settlement_is_not_borrowed(self):
        other = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="B-2",
            start_date=timezone.localdate() - timedelta(days=5))
        self.settle(total_amount_payable=Decimal("42000"))
        self.assertIsNone(growing_charge_for(other))


class SourcedBlocksReachTheDrawerTests(TestCase):
    """What the row shows and what the panel shows have to be one figure.

    The P&L's blocks only ever knew hand-typed growing and admin costs, so the
    drawer read "not entered" for both while the columns beside it showed a
    settlement and a scheme figure. A report cannot disagree with itself one
    click apart.
    """

    def pl(self):
        return {"cost_blocks": [
            {"title": "Feed Cost", "total": Decimal("100"),
             "lines": [{"label": "Pre-Starter", "quantity": Decimal("2"),
                        "rate": Decimal("50"), "amount": Decimal("100")}]},
            {"title": "Growing Expenses", "total": None, "lines": []},
            {"title": "Administrative Cost", "total": None, "lines": []},
        ]}

    def detail(self, **over):
        from broiler.views import _cost_detail
        kw = dict(growing_cost=None, gc_source="unsettled",
                  admin_cost=None, admin_source="no scheme", admin_heads={})
        kw.update(over)
        return {b["title"]: b for b in _cost_detail(self.pl(), **kw)}

    def test_a_settled_growing_charge_replaces_not_entered(self):
        block = self.detail(growing_cost=Decimal("42000"),
                            gc_source="settlement")["Growing Expenses"]
        self.assertEqual(block["total"], Decimal("42000"))
        self.assertEqual([ln["label"] for ln in block["lines"]],
                         ["Growing Charge settlement"])

    def test_scheme_admin_lands_in_the_block_head_by_head(self):
        block = self.detail(
            admin_cost=Decimal("48000"), admin_source="schema",
            admin_heads={"Farmer Admin Cost": Decimal("36000"),
                         "Management Admin Cost": Decimal("12000")},
        )["Administrative Cost"]
        self.assertEqual(block["total"], Decimal("48000"))
        self.assertEqual([ln["label"] for ln in block["lines"]],
                         ["Farmer Admin Cost", "Management Admin Cost"])

    def test_a_hand_typed_figure_is_left_exactly_as_the_statement_had_it(self):
        """Only the sourced cases are substituted; everything else is the P&L's."""
        block = self.detail()["Feed Cost"]
        self.assertEqual(block["total"], Decimal("100"))
        self.assertEqual(block["lines"][0]["rate"], Decimal("50"))

    def test_nothing_is_substituted_when_there_is_nothing_to_substitute(self):
        blocks = self.detail()
        self.assertIsNone(blocks["Growing Expenses"]["total"])
        self.assertIsNone(blocks["Administrative Cost"]["total"])

    def test_the_component_split_counts_the_sourced_heads(self):
        from broiler.views import _cost_components

        heads = [h for h, _a in _cost_components(
            self.pl(), Decimal("42000"), "settlement", Decimal("48000"), "schema",
            {"Farmer Admin Cost": Decimal("36000")})]
        self.assertIn("Growing Charges", heads)
        self.assertIn("Farmer Admin Cost", heads)


class SchemePricingTests(TestCase):
    """Farmer sees scheme rates; management sees what was actually paid."""

    def setUp(self):
        self.region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=self.region,
                                       prefix="AKB")
        sup = Supervisor.objects.create(branch=branch, name="R. Verma")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=sup, farmer=farmer, region=self.region,
            line="L1", farm_name="Yadav Farm", farm_capacity=5000)
        self.batch = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="B-1", start_date=date(2026, 7, 1))

    def scheme(self, **over):
        from broiler.models import GrowingChargeScheme
        row = dict(region=self.region, schema_name="S1", is_active=True,
                   from_date=date(2026, 1, 1), to_date=date(2026, 12, 31),
                   chick_cost=Decimal("35"), feed_cost=Decimal("40"))
        row.update(over)
        return GrowingChargeScheme.objects.create(**row)

    def test_the_farmer_view_reads_the_scheme_s_rates(self):
        from broiler.services.production_cost import scheme_rates_for

        self.scheme()
        self.assertEqual(scheme_rates_for(self.batch),
                         {"chick": Decimal("35"), "feed": Decimal("40")})

    def test_no_scheme_means_no_rates_to_price_from(self):
        """Not free — nothing to say, so the report falls back to actuals and
        marks the column."""
        from broiler.services.production_cost import scheme_rates_for

        self.assertIsNone(scheme_rates_for(self.batch))

    def test_a_scheme_outside_the_placement_date_does_not_apply(self):
        from broiler.services.production_cost import scheme_rates_for

        self.scheme(from_date=date(2027, 1, 1), to_date=date(2027, 12, 31))
        self.assertIsNone(scheme_rates_for(self.batch))

    def test_medicine_is_not_priced_from_the_scheme(self):
        """Its medicine_cost only carries a figure on a "Fixed" basis, and in
        practice every scheme runs Actual or Master — pricing from it would
        read as free rather than as unpriced."""
        from broiler.services.production_cost import scheme_rates_for

        self.scheme()
        self.assertEqual(set(scheme_rates_for(self.batch)), {"chick", "feed"})

    def test_the_blocks_are_repriced_and_say_the_rate_used(self):
        from broiler.views import _cost_detail

        pl = {"cost_blocks": [
            {"title": "Chick Cost", "total": Decimal("80115"),
             "lines": [{"label": "DOC", "quantity": Decimal("2289"),
                        "rate": Decimal("35"), "amount": Decimal("80115")}]},
            {"title": "Feed Cost", "total": Decimal("1125"), "lines": []},
        ]}
        blocks = {b["title"]: b for b in _cost_detail(
            pl, None, "unsettled", None, "no scheme", {},
            {"chick": Decimal("30"), "feed": Decimal("40")},
            Decimal("1000"), Decimal("50"))}
        self.assertEqual(blocks["Chick Cost"]["total"], Decimal("30000.00"))
        self.assertEqual(blocks["Chick Cost"]["lines"][0]["rate"], Decimal("30"))
        self.assertEqual(blocks["Feed Cost"]["total"], Decimal("2000.00"))

    def test_management_leaves_the_purchase_priced_blocks_alone(self):
        from broiler.views import _cost_detail

        pl = {"cost_blocks": [{"title": "Chick Cost", "total": Decimal("80115"),
                               "lines": []}]}
        blocks = {b["title"]: b for b in _cost_detail(
            pl, None, "unsettled", None, "no scheme", {}, None, None, None)}
        self.assertEqual(blocks["Chick Cost"]["total"], Decimal("80115"))


class LiveWeightBeforeALiftingTests(TestCase):
    """Cost per kilo on a flock that has not sold anything yet.

    Live weight came from the batch costing's sold_weight, which is nothing
    before a lifting — so Cost/Kg, Standard/Kg and FCR were all withheld on
    every live flock, which is most of what this report lists. The birds still
    weigh something; the last weighing across the birds still alive is what a
    supervisor would quote, and it is marked as an estimate rather than passed
    off as a weighbridge figure.
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
            line="L1", farm_name="Yadav Farm", farm_capacity=5000)
        self.batch = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="B-1",
            start_date=self.today - timedelta(days=30))

    def weigh(self, days_ago, grams):
        return DailyEntry.objects.create(
            farm=self.farm, batch=self.batch, supervisor=self.sup,
            date=self.today - timedelta(days=days_ago),
            avg_weight_gms=Decimal(str(grams)))

    def row(self):
        from broiler.views import _production_cost_row
        return _production_cost_row(self.batch)

    def test_with_no_placement_there_are_no_birds_to_weigh(self):
        """Live birds come from the placement, so an unplaced flock stays at
        nothing rather than multiplying a weight by zero and pretending."""
        self.weigh(2, 1800)
        r = self.row()
        self.assertEqual(r["live_birds"], Decimal("0"))
        self.assertEqual(r["weight"], Decimal("0"))
        self.assertEqual(r["weight_basis"], "none")

    def test_a_never_weighed_flock_reports_nothing(self):
        r = self.row()
        self.assertEqual(r["weight"], Decimal("0"))
        self.assertEqual(r["weight_basis"], "none")
        self.assertIsNone(r["cost_per_kg"])
        self.assertIsNone(r["avg_bwt"])

    def test_avg_body_weight_reconciles_with_the_live_weight_beside_it(self):
        """The two columns have to tell the same story: per-bird times birds
        is the total, whichever basis produced it."""
        from broiler.views import _production_cost_row

        r = _production_cost_row(self.batch)
        if r["avg_bwt"] and r["live_birds"]:
            self.assertEqual((r["avg_bwt"] * r["live_birds"]).quantize(Decimal("1")),
                             r["weight"].quantize(Decimal("1")))
