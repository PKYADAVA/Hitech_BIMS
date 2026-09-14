"""Putting right a settlement that was signed on a wrong figure.

A settlement freezes every figure the form showed, and editing one deliberately
touches only what a person typed. Both are right on their own and together they
leave a trap: when a calculation turns out to have been wrong, the fix reaches
every batch settled afterwards and no batch settled before, and there is no way
to correct the old ones — the one path that could is the one path that will not
touch a computed figure.

The fault this was built for: Feed Out counted feed returned to the warehouse
and not feed passed to another farm, so a batch closed holding 500 kg it had
given away. Batches settled while that was true still say 500.

What matters here is not that a re-run changes numbers. It is what it must
refuse to change — the deductions somebody typed, and the fact that it
happened at all.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from broiler.models import (Branch, BroilerBatch, BroilerFarm, DailyEntry,
                            Farmer, GCSettlementRecalculation,
                            GrowingChargeSettlement, Region, Supervisor)
from broiler.services import gc_recalc
from broiler.views import _build_batch_report, _gc_settlement_autofill
from inventory.models import Item, ItemCategory, StockTransfer, Warehouse


class RecalculateTests(TestCase):

    def setUp(self):
        self.placed = timezone.localdate() - timedelta(days=60)
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region,
                                       prefix="AKB")
        self.supervisor = Supervisor.objects.create(branch=branch, name="A. Pal")
        farmer = Farmer.objects.create(farmer_name="Vishvanath")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=self.supervisor, farmer=farmer,
            region=region, line="Baskhari", farm_name="Vishvanath Farm",
            farm_capacity=5000)
        self.neighbour = BroilerFarm.objects.create(
            branch=branch, supervisor=self.supervisor, farmer=farmer,
            region=region, line="Baskhari", farm_name="Pappu Yadav Farm",
            farm_capacity=5000)
        self.batch = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="AKB-1102-1",
            book_number="BK-AKB", start_date=self.placed)

        self.store = Warehouse.objects.create(name="Akbarpur Warehouse")
        self.feed = Item.objects.create(
            description="Finisher Feed",
            category=ItemCategory.objects.create(name="Feed"),
            valuation_method="Weighted Average", standard_cost_per_unit=42,
            usage="Produced", source="Purchased", type="Raw Material",
            item_account="Expense")

        self.user = get_user_model().objects.create_superuser(
            "gc_fixer", "g@x.com", "Str0ngPass!")

        # 5,500 in, 4,500 eaten, 500 to a neighbour, 500 back to the store.
        StockTransfer.objects.create(
            date=self.placed + timedelta(days=1), item=self.feed,
            quantity=Decimal("5500"), rate=42,
            from_location_type="warehouse", from_warehouse=self.store,
            to_location_type="farm", to_farm=self.farm, to_batch=self.batch)
        DailyEntry.objects.create(
            farm=self.farm, batch=self.batch, supervisor=self.supervisor,
            date=self.placed + timedelta(days=30),
            feed_1=self.feed, feed_1_qty=Decimal("4500"))
        StockTransfer.objects.create(
            date=self.placed + timedelta(days=43), item=self.feed,
            quantity=Decimal("500"), rate=42,
            from_location_type="farm", from_farm=self.farm, from_batch=self.batch,
            to_location_type="farm", to_farm=self.neighbour)
        StockTransfer.objects.create(
            date=self.placed + timedelta(days=50), item=self.feed,
            quantity=Decimal("500"), rate=42,
            from_location_type="farm", from_farm=self.farm, from_batch=self.batch,
            to_location_type="warehouse", to_warehouse=self.store)

    # --- fixtures ---------------------------------------------------------

    def settle(self, **overrides):
        """A settlement holding today's correct figures."""
        fields = _gc_settlement_autofill(self.batch, None)
        s = GrowingChargeSettlement(
            batch=self.batch, farm=self.farm,
            gc_date=fields.get("gc_date_default") or timezone.localdate())
        names = {f.name for f in GrowingChargeSettlement._meta.fields}
        for k, v in fields.items():
            if k in names:
                setattr(s, k, v)
        for k, v in overrides.items():
            setattr(s, k, v)
        s.save()
        return s

    def settled_the_old_way(self):
        """A settlement as it would have been signed before the fix: Feed Out
        counting only the warehouse return, and closing the day after the last
        sale."""
        return self.settle(
            feed_out=Decimal("500.00"), feed_balance=Decimal("500.00"),
            gc_date=self.placed + timedelta(days=41))

    # --- what it finds ----------------------------------------------------

    def test_it_finds_the_figures_that_are_wrong(self):
        s = self.settled_the_old_way()
        changes, _ = gc_recalc.plan(s)
        self.assertEqual(changes["feed_out"], {"from": "500.00", "to": "1000.00"})
        self.assertEqual(changes["feed_balance"], {"from": "500.00", "to": "0.00"})

    def test_a_settlement_already_right_reports_nothing(self):
        """The answer for every batch settled after the fix, and the reason a
        sweep over all of them is readable."""
        changes, _ = gc_recalc.plan(self.settle())
        self.assertEqual(changes, {})

    def test_previewing_writes_nothing(self):
        s = self.settled_the_old_way()
        gc_recalc.plan(s)
        s.refresh_from_db()
        self.assertEqual(s.feed_balance, Decimal("500.00"))
        self.assertEqual(GCSettlementRecalculation.objects.count(), 0)

    # --- what it does -----------------------------------------------------

    def test_applying_corrects_the_figures(self):
        s = self.settled_the_old_way()
        gc_recalc.recalculate(s, user=self.user)
        s.refresh_from_db()
        self.assertEqual(s.feed_out, Decimal("1000.00"))
        self.assertEqual(s.feed_balance, Decimal("0.00"))

    def test_it_leaves_what_a_person_typed_alone(self):
        """The line this must not cross. Those deductions were somebody's
        decision, not a calculation — a re-run that overwrote them would
        destroy the work it claims to protect."""
        s = self.settled_the_old_way()
        s.other_deductions = Decimal("1500.00")
        s.advance_deductions = Decimal("2750.00")
        s.transportation_charges = Decimal("900.00")
        s.save()

        gc_recalc.recalculate(s, user=self.user)

        s.refresh_from_db()
        self.assertEqual(s.other_deductions, Decimal("1500.00"))
        self.assertEqual(s.advance_deductions, Decimal("2750.00"))
        self.assertEqual(s.transportation_charges, Decimal("900.00"))

    def test_the_totals_are_rebuilt_from_both_halves(self):
        """Not from the fresh figures alone. A total that ignored the typed
        deduction would be a different kind of wrong — and one that only ever
        showed up in what a farmer was paid."""
        s = self.settled_the_old_way()
        s.other_deductions = Decimal("1000.00")
        s.save()

        gc_recalc.recalculate(s, user=self.user)

        s.refresh_from_db()
        # No growing charge on this fixture, so the deduction is the whole of
        # it: the total is what the typed figure takes away.
        self.assertEqual(s.other_deductions, Decimal("1000.00"))
        self.assertEqual(s.total_amount_payable, Decimal("-1000.00"))

    def test_it_records_who_did_it_and_what_moved(self):
        """A correction nobody can see afterwards is indistinguishable from an
        error."""
        s = self.settled_the_old_way()
        gc_recalc.recalculate(s, user=self.user, note="Feed Out fix")

        entry = GCSettlementRecalculation.objects.get()
        self.assertEqual(entry.settlement, s)
        self.assertEqual(entry.actor, self.user)
        self.assertEqual(entry.note, "Feed Out fix")
        self.assertEqual(entry.changes["feed_balance"],
                         {"from": "500.00", "to": "0.00"})

    def test_a_re_run_that_changes_nothing_is_not_an_event(self):
        """Otherwise a nightly sweep fills the log with rows saying nothing
        happened, and the ones that matter are lost in them."""
        s = self.settle()
        self.assertEqual(gc_recalc.recalculate(s, user=self.user), {})
        self.assertEqual(GCSettlementRecalculation.objects.count(), 0)

    def test_running_it_twice_corrects_once(self):
        s = self.settled_the_old_way()
        gc_recalc.recalculate(s, user=self.user)
        gc_recalc.recalculate(s, user=self.user)
        self.assertEqual(GCSettlementRecalculation.objects.count(), 1)

    # --- the closing date -------------------------------------------------

    def test_it_corrects_the_closing_date_too(self):
        """Settled the day after the last sale, when feed moved for another
        nine days."""
        s = self.settled_the_old_way()
        gc_recalc.recalculate(s, user=self.user)
        s.refresh_from_db()
        self.assertEqual(s.gc_date, self.placed + timedelta(days=50))

    def test_the_batch_agrees_with_its_settlement_about_when_it_ended(self):
        s = self.settled_the_old_way()
        gc_recalc.recalculate(s, user=self.user)
        s.refresh_from_db()
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.closed_on, s.gc_date)
        self.assertEqual(self.batch.end_date, s.gc_date)

    def test_the_date_can_be_left_alone(self):
        """It moves a voucher between periods, which may be a decision rather
        than a correction — so it can be held while the figures are fixed."""
        s = self.settled_the_old_way()
        was = s.gc_date
        gc_recalc.recalculate(s, user=self.user, include_date=False)
        s.refresh_from_db()
        self.assertEqual(s.gc_date, was)
        self.assertEqual(s.feed_balance, Decimal("0.00"))


class RecalculateEndpointTests(RecalculateTests):
    """The same thing over HTTP, which is how it is actually reached."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def url(self, s):
        return "/gc_settlement/%s/recalculate/" % s.id

    def test_get_previews_without_writing(self):
        s = self.settled_the_old_way()
        body = self.client.get(self.url(s)).json()
        self.assertFalse(body["up_to_date"])
        self.assertEqual(body["changes"]["feed_balance"]["to"], "0.00")

        s.refresh_from_db()
        self.assertEqual(s.feed_balance, Decimal("500.00"))

    def test_post_applies(self):
        s = self.settled_the_old_way()
        response = self.client.post(self.url(s), {}, content_type="application/json")
        self.assertEqual(response.status_code, 200)

        s.refresh_from_db()
        self.assertEqual(s.feed_balance, Decimal("0.00"))

    def test_it_says_so_when_there_is_nothing_to_do(self):
        s = self.settle()
        body = self.client.post(self.url(s), {}, content_type="application/json").json()
        self.assertTrue(body["up_to_date"])
        self.assertEqual(body["changes"], {})

    def test_signing_out_closes_it(self):
        s = self.settled_the_old_way()
        self.client.logout()
        self.assertIn(self.client.get(self.url(s)).status_code, (302, 401, 403))
