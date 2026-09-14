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
