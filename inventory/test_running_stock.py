"""What a location holds, against what its documents have moved out.

Every document that keeps a running stock column chained from an opening
balance of zero over its own rows — which is not an opening balance but an
assumption that nothing had ever arrived. A warehouse that had received 5,070
chicks showed its transfers out as a growing negative: -2,429 then -4,718,
where the real balances were 2,641 and 352.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from account.models import ChartOfAccount
from inventory.models import (InventoryAdjustment, InventoryAdjustmentItem,
                              Item, ItemCategory, MedicineTransfer,
                              MedicineTransferItem, StockReceive,
                              StockReceiveItem, StockTransfer, Warehouse)
from inventory.services.item_summary import balance_excluding, location_item_stock


class RunningStockTests(TestCase):
    def setUp(self):
        self.store = Warehouse.objects.create(name="Main Store")
        self.other = Warehouse.objects.create(name="Branch Store")
        self.account = ChartOfAccount.objects.create(
            code="5001", description="Feed Expense", type="Expense")
        self.item = Item.objects.create(
            description="Day Old Chicks",
            category=ItemCategory.objects.create(name="Chicks"),
            valuation_method="Weighted Average", standard_cost_per_unit=40,
            usage="Produced", source="Purchased", type="Raw Material",
            item_account="Expense")

    def receive(self, qty, on):
        head = StockReceive.objects.create(date=on,
                                           chart_of_account=self.account)
        StockReceiveItem.objects.create(
            receive=head, item=self.item, quantity=Decimal(qty), rate=40,
            location_type="warehouse", warehouse=self.store)

    def send(self, qty, on):
        return StockTransfer.objects.create(
            date=on, item=self.item, quantity=Decimal(qty), rate=40,
            from_location_type="warehouse", from_warehouse=self.store,
            to_location_type="warehouse", to_warehouse=self.other)

    # --- stock transfer --------------------------------------------------

    def test_a_transfer_leaves_what_was_received_behind(self):
        self.receive(5000, date(2026, 5, 1))
        self.send(2000, date(2026, 5, 2))
        self.assertEqual(
            StockTransfer.previous_stock("warehouse", self.store.id,
                                         self.item.id, date(2026, 5, 3), None),
            Decimal("3000.00"))

    def test_the_stored_column_matches_the_real_balance(self):
        from inventory.views import _recompute_stock_transfer_chain

        self.receive(5070, date(2026, 5, 1))
        first = self.send(2429, date(2026, 5, 2))
        second = self.send(2289, date(2026, 5, 3))
        _recompute_stock_transfer_chain("warehouse", self.store.id, self.item.id)

        first.refresh_from_db()
        second.refresh_from_db()
        # The reported figures: -2429 and -4718 under the old chain.
        self.assertEqual(first.stock, Decimal("2641.00"))
        self.assertEqual(second.stock, Decimal("352.00"))
        self.assertEqual(second.stock,
                         location_item_stock("warehouse", self.store.id,
                                             self.item.id, date(2026, 5, 3)))

    def test_stock_arriving_mid_chain_lands_on_its_own_day(self):
        self.receive(1000, date(2026, 5, 1))
        self.send(400, date(2026, 5, 2))
        self.receive(500, date(2026, 5, 3))
        self.assertEqual(
            StockTransfer.previous_stock("warehouse", self.store.id,
                                         self.item.id, date(2026, 5, 4), None),
            Decimal("1100.00"))

    def test_nothing_received_still_reads_negative(self):
        # Sending what you do not have is a real answer, not one to clamp.
        self.send(100, date(2026, 5, 2))
        self.assertEqual(
            StockTransfer.previous_stock("warehouse", self.store.id,
                                         self.item.id, date(2026, 5, 3), None),
            Decimal("-100.00"))

    # --- the primitive ---------------------------------------------------

    def test_a_chain_excludes_only_its_own_movements(self):
        # Counting them here as well would subtract each of them twice, which
        # is how the column ends up back where it started.
        self.receive(1000, date(2026, 5, 1))
        self.send(300, date(2026, 5, 2))
        self.assertEqual(
            balance_excluding("warehouse", self.store.id, self.item.id,
                              date(2026, 5, 3), {"stock_transfer_out"}),
            Decimal("1000.00"))
        self.assertEqual(
            location_item_stock("warehouse", self.store.id, self.item.id,
                                date(2026, 5, 3)),
            Decimal("700.00"))

    # --- inventory adjustment --------------------------------------------

    def test_an_adjustment_nets_against_what_is_held(self):
        from inventory.views import _recompute_inventory_adjustment_chain

        self.receive(500, date(2026, 5, 1))
        head = InventoryAdjustment.objects.create(
            date=date(2026, 5, 2), location_type="warehouse", warehouse=self.store,
            chart_of_account=self.account)
        line = InventoryAdjustmentItem.objects.create(
            adjustment=head, item=self.item, quantity=Decimal("40"),
            adjustment_type="Deduct", rate=40)
        _recompute_inventory_adjustment_chain("warehouse", self.store.id,
                                              self.item.id)
        line.refresh_from_db()
        self.assertEqual(line.stock, Decimal("460.00"))

    # --- medicine transfer ------------------------------------------------

    def test_a_medicine_transfer_reads_the_source_balance(self):
        from inventory.views import _recompute_medicine_stock_chain

        self.receive(200, date(2026, 5, 1))
        head = MedicineTransfer.objects.create(
            date=date(2026, 5, 2),
            from_location_type="warehouse", from_warehouse=self.store,
            to_location_type="warehouse", to_warehouse=self.other)
        line = MedicineTransferItem.objects.create(
            transfer=head, item=self.item, quantity=Decimal("30"), rate=40)
        _recompute_medicine_stock_chain("warehouse", self.store.id, self.item.id)
        line.refresh_from_db()
        self.assertEqual(line.stock, Decimal("170.00"))


class NoChainStartsAtZeroTests(TestCase):
    """A guard, because this bug appeared five separate times.

    Each of these was written the same way — walk my own rows, start at zero —
    and each was wrong for the same reason. A sixth document with a running
    stock column will be written one day; this is what tells its author.
    """

    def test_every_running_stock_chain_reads_a_real_opening_balance(self):
        import inspect

        from broiler import views as broiler_views
        from inventory import views as inventory_views

        chains = [
            broiler_views._recompute_stock_chain,
            broiler_views._recompute_medicine_stock_chain,
            inventory_views._recompute_stock_transfer_chain,
            inventory_views._recompute_medicine_stock_chain,
            inventory_views._recompute_inventory_adjustment_chain,
        ]
        for chain in chains:
            source = inspect.getsource(chain)
            self.assertIn(
                "balance", source,
                f"{chain.__name__} does not read an opening balance — if it "
                f"starts at zero it is reporting movement, not stock")
