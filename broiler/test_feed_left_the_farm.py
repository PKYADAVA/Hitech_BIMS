"""Feed that left the farm, by whichever route it left.

Reported from a closed batch. The Batch History Report's Feed Summary showed a
balance of zero for every feed — correctly, because it subtracts both ways
stock leaves a farm: sent back to the warehouse, and passed on to another
farm that is still running. The Growing Charges tab, settling the same flock,
showed 500 kg still on hand.

The two were working the same sum out separately, and only one of them
remembered the second route:

    Feed Summary      in - consumed - returned - transferred to other farms
    Growing Charges   in - consumed - returned

So a farmer who had given 500 kg to a neighbouring farm was closed out as
though it were still in their shed. It is the number the settlement is
actually about, and there is no third opinion to break the tie — either the
feed is there or it is not.

The figures below are that batch's: 5,500 kg in, 4,500 kg eaten, 500 kg back
to the warehouse, 500 kg away to other farms. Nothing left.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from broiler.models import (Branch, BroilerBatch, BroilerFarm, DailyEntry,
                            Farmer, Region, Supervisor)
from broiler.views import _build_batch_report, _gc_settlement_autofill
from inventory.models import Item, ItemCategory, StockTransfer, Warehouse


class FeedThatLeftTheFarmTests(TestCase):

    def setUp(self):
        self.today = timezone.localdate()
        self.placed = self.today - timedelta(days=40)

        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region,
                                       prefix="AKB")
        self.supervisor = Supervisor.objects.create(branch=branch, name="A. Pal")
        farmer = Farmer.objects.create(farmer_name="Vishvanath")

        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=self.supervisor, farmer=farmer,
            region=region, line="Baskhari", farm_name="Vishvanath Farm",
            farm_capacity=5000)
        # Somewhere for the feed to go that is not the warehouse.
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

    # --- the movements ---------------------------------------------------

    def send(self, qty, days_in):
        """Warehouse -> this farm."""
        StockTransfer.objects.create(
            date=self.placed + timedelta(days=days_in), item=self.feed,
            quantity=Decimal(qty), rate=42,
            from_location_type="warehouse", from_warehouse=self.store,
            to_location_type="farm", to_farm=self.farm, to_batch=self.batch)

    def eat(self, qty, days_in):
        DailyEntry.objects.create(
            farm=self.farm, batch=self.batch, supervisor=self.supervisor,
            date=self.placed + timedelta(days=days_in),
            feed_1=self.feed, feed_1_qty=Decimal(qty))

    def return_to_store(self, qty, days_in):
        """This farm -> back where it came from."""
        StockTransfer.objects.create(
            date=self.placed + timedelta(days=days_in), item=self.feed,
            quantity=Decimal(qty), rate=42,
            from_location_type="farm", from_farm=self.farm,
            from_batch=self.batch,
            to_location_type="warehouse", to_warehouse=self.store)

    def pass_to_neighbour(self, qty, days_in):
        """This farm -> another farm that is still running."""
        StockTransfer.objects.create(
            date=self.placed + timedelta(days=days_in), item=self.feed,
            quantity=Decimal(qty), rate=42,
            from_location_type="farm", from_farm=self.farm,
            from_batch=self.batch,
            to_location_type="farm", to_farm=self.neighbour)

    def a_batch_that_used_everything(self):
        """5,500 in, 4,500 eaten, 500 returned, 500 passed on. Nothing left."""
        self.send(5500, 1)
        self.eat(4500, 30)
        self.pass_to_neighbour(500, 41)
        self.return_to_store(500, 42)

    def report(self):
        return _build_batch_report(self.batch, fetch_type="farmer")

    def settlement(self, report):
        return _gc_settlement_autofill(self.batch, None, report=report)

    # --- what each of them says ------------------------------------------

    def test_the_feed_summary_has_nothing_left(self):
        """The report that was already right, pinned so it stays right."""
        self.a_batch_that_used_everything()
        rows = self.report()["feed_summary"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(Decimal(str(rows[0]["balance"])), Decimal("0"))

    def test_the_settlement_has_nothing_left_either(self):
        """The bug as reported: 500 kg of feed the farmer had given away."""
        self.a_batch_that_used_everything()
        self.assertEqual(self.settlement(self.report())["feed_balance"],
                         Decimal("0.00"))

    def test_feed_out_counts_both_ways_it_left(self):
        """Not just the return. 500 back to the store and 500 to a neighbour
        is 1,000 kg gone from this farm."""
        self.a_batch_that_used_everything()
        self.assertEqual(self.settlement(self.report())["feed_out"],
                         Decimal("1000.00"))

    def test_the_two_screens_agree(self):
        """The whole complaint, in one assertion. Whatever the numbers, the
        page that says what is on the farm and the page that settles the
        farmer for it must not disagree."""
        self.a_batch_that_used_everything()
        report = self.report()
        summary_balance = sum(Decimal(str(r["balance"]))
                              for r in report["feed_summary"])
        self.assertEqual(self.settlement(report)["feed_balance"], summary_balance)

    def test_a_farm_that_really_is_holding_feed_still_says_so(self):
        """The fix must not simply zero the balance. Send more than leaves,
        and what is left is what is left."""
        self.send(5500, 1)
        self.eat(4000, 30)
        self.pass_to_neighbour(200, 41)
        self.return_to_store(300, 42)

        report = self.report()
        self.assertEqual(self.settlement(report)["feed_balance"], Decimal("1000.00"))
        self.assertEqual(sum(Decimal(str(r["balance"]))
                             for r in report["feed_summary"]), Decimal("1000"))

    def test_feed_kept_on_the_farm_is_not_counted_as_gone(self):
        """No outgoing movements at all — the plainest case, and the one a
        careless fix would break by subtracting something that never left."""
        self.send(1000, 1)
        self.eat(600, 30)
        self.assertEqual(self.settlement(self.report())["feed_balance"],
                         Decimal("400.00"))

    def test_the_costing_engine_reports_the_two_routes_separately(self):
        """They are one number on the settlement line and two different
        events, and the history tables show them under separate headings —
        Feed Return, and Feed Transfer to Other Farms."""
        self.a_batch_that_used_everything()
        bc = self.report()["batch_costing"]
        self.assertEqual(bc["feed_return"], Decimal("500.00"))
        self.assertEqual(bc["feed_transfer_out"], Decimal("500.00"))

    def test_the_costing_summary_carries_the_feed_balance(self):
        """Shown on the Batch History report beside Feed Transferred Out: sent,
        less consumed, less returned, less transferred out."""
        self.a_batch_that_used_everything()
        self.assertEqual(self.report()["batch_costing"]["feed_balance"], Decimal("0.00"))

    def test_the_costing_summary_balance_shows_feed_still_held(self):
        self.send(5500, 1)
        self.eat(4000, 30)
        self.pass_to_neighbour(200, 41)
        self.return_to_store(300, 42)
        self.assertEqual(self.report()["batch_costing"]["feed_balance"],
                         Decimal("1000.00"))

    def test_non_feed_items_moved_out_are_listed_apart_from_feed(self):
        """Chicks moved out of the batch — to another farm or back to the
        warehouse — are not feed. They get their own table and leave Feed
        Return, Feed Transferred Out, Feed Balance and the Feed Summary alone."""
        chicks = Item.objects.create(
            description="Broiler Chicks",
            category=ItemCategory.objects.create(name="Broiler Chicks"),
            valuation_method="Weighted Average", standard_cost_per_unit=35,
            usage="Produced", source="Purchased", type="Raw Material",
            item_account="Expense")
        self.a_batch_that_used_everything()
        StockTransfer.objects.create(
            date=self.placed + timedelta(days=5), item=chicks,
            quantity=Decimal("200"), rate=35,
            from_location_type="farm", from_farm=self.farm, from_batch=self.batch,
            to_location_type="farm", to_farm=self.neighbour)
        StockTransfer.objects.create(
            date=self.placed + timedelta(days=6), item=chicks,
            quantity=Decimal("50"), rate=35,
            from_location_type="farm", from_farm=self.farm, from_batch=self.batch,
            to_location_type="warehouse", to_warehouse=self.store)

        report = self.report()
        bc = report["batch_costing"]
        self.assertEqual(bc["feed_return"], Decimal("500.00"))
        self.assertEqual(bc["feed_transfer_out"], Decimal("500.00"))
        self.assertEqual(bc["feed_balance"], Decimal("0.00"))
        self.assertEqual([r["quantity"] for r in report["other_transfer_out"]],
                         [Decimal("200"), Decimal("50")])
        self.assertNotIn("Broiler Chicks", [r["item"] for r in report["feed_summary"]])


class ClosingDateTests(TestCase):
    """The settlement closes after everything it is settling.

    Reported alongside the feed balance, from the same batch: the birds sold
    out on 30 August, feed went to two other farms on 2 September and back to
    the warehouse on 9 September, and the GC Date offered was 31 August — the
    day after the last sale, and a week before two of the movements the
    settlement accounts for.
    """

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

    def day(self, n):
        return self.placed + timedelta(days=n)

    def sell(self, days_in):
        from broiler.models import BirdSale

        BirdSale.objects.create(
            batch=self.batch, farm=self.farm, date=self.day(days_in),
            birds=1000, net_weight=Decimal("2000"), rate=Decimal("107"),
            amount=Decimal("214000"))

    def entry(self, days_in):
        DailyEntry.objects.create(
            farm=self.farm, batch=self.batch, supervisor=self.supervisor,
            date=self.day(days_in), feed_1=self.feed, feed_1_qty=Decimal("100"))

    def move_out(self, days_in, to_warehouse):
        StockTransfer.objects.create(
            date=self.day(days_in), item=self.feed, quantity=Decimal("100"),
            rate=42, from_location_type="farm", from_farm=self.farm,
            from_batch=self.batch,
            **({"to_location_type": "warehouse", "to_warehouse": self.store}
               if to_warehouse else
               {"to_location_type": "farm", "to_farm": self.neighbour}))

    def gc_date(self):
        report = _build_batch_report(self.batch, fetch_type="farmer")
        return _gc_settlement_autofill(self.batch, None, report=report)["gc_date_default"]

    def test_it_closes_on_the_last_movement_not_the_last_sale(self):
        """The reported batch, in order: sale, then transfers for another ten
        days."""
        self.entry(30)
        self.sell(40)
        self.move_out(43, to_warehouse=False)    # on to a running farm
        self.move_out(50, to_warehouse=True)     # back to the warehouse
        self.assertEqual(self.gc_date(), self.day(50))

    def test_a_daily_entry_can_be_the_last_word(self):
        """Nothing about this is specific to transfers — whatever happened
        last is what the batch closes on."""
        self.sell(40)
        self.entry(44)
        self.assertEqual(self.gc_date(), self.day(44))

    def test_a_sale_can_still_be_the_last_word(self):
        """The ordinary case has to keep working: sell up and close."""
        self.entry(30)
        self.sell(40)
        self.assertEqual(self.gc_date(), self.day(40))

    def test_it_is_the_day_itself_not_the_day_after(self):
        """It used to offer last sale + 1. The rule is the date of the last
        entry, so a batch whose last act was a sale closes on the sale."""
        self.sell(40)
        self.assertNotEqual(self.gc_date(), self.day(41))
        self.assertEqual(self.gc_date(), self.day(40))

    def test_a_batch_nothing_has_happened_to_has_no_closing_date(self):
        """Rather than a guess, or a crash on max() of nothing."""
        self.assertIsNone(self.gc_date())

    def buy_for_the_farm(self, days_in, batch=None):
        """A feed purchase delivered straight to the farm.

        ``batch=None`` is the row the Batch History report keeps by date alone
        — bought for this farm, naming no flock.
        """
        from purchase.models import GeneralPurchase, GeneralPurchaseItem
        from purchase.models import Supplier

        purchase = GeneralPurchase.objects.create(
            supplier=Supplier.objects.create(name="Ravi Feeds"),
            date=self.day(days_in))
        return GeneralPurchaseItem.objects.create(
            purchase=purchase, item=self.feed, farm=self.farm, batch=batch,
            sent_qty=100, rcv_qty=100, rate=42, amount=4200)

    def test_a_purchase_naming_this_flock_counts(self):
        """Tagged to the batch, so it is this batch's activity."""
        self.sell(40)
        self.buy_for_the_farm(45, batch=self.batch)
        self.assertEqual(self.gc_date(), self.day(45))

    def test_a_purchase_naming_no_flock_does_not_close_this_one(self):
        """The case worth guarding. Batches keep no end date until they are
        settled, so the report's date window has no upper bound and an
        untagged purchase bought for the *next* flock is swept in. It may
        appear in the history — that is deliberate, better than losing it —
        but it must not be the thing that decides when this flock finished.
        """
        self.sell(40)
        self.buy_for_the_farm(60)               # no batch named
        self.assertEqual(self.gc_date(), self.day(40))

    def test_the_untagged_purchase_is_still_in_the_history(self):
        """Excluded from the closing date, not hidden from the report."""
        self.sell(40)
        self.buy_for_the_farm(60)
        rows = _build_batch_report(self.batch, fetch_type="farmer")["feed_purchase"]
        self.assertEqual([r["date"] for r in rows], [self.day(60)])
