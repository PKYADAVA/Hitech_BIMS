"""The feed a farm has, against the feed it was sent.

Daily Entry's Stock column chained from an opening balance of zero over its own
entries, so nothing delivered to the farm ever entered it: a farm sent 2,337 kg
of Starter Feed showed 0, and the figure went further negative every day it was
fed. What it displayed was cumulative consumption with a minus sign.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from broiler.models import (Branch, BroilerBatch, BroilerFarm, DailyEntry,
                            Farmer, MedicineVaccineEntry, Region, Supervisor)
from inventory.models import Item, ItemCategory, StockTransfer, Warehouse
from inventory.services.item_summary import (farm_receipts_balance,
                                             location_item_stock)


class FarmStockTests(TestCase):
    def setUp(self):
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Bahraich", region=region,
                                       prefix="BHR")
        self.supervisor = Supervisor.objects.create(branch=branch, name="R. Verma")
        supervisor = self.supervisor
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=supervisor, farmer=farmer, region=region,
            line="L1", farm_name="Yadav Farm", farm_capacity=5000)
        self.batch = BroilerBatch.objects.create(broiler_farm=self.farm,
                                                 batch_name="B1")
        self.store = Warehouse.objects.create(name="Feed Store")
        self.feed = Item.objects.create(
            description="Starter Feed",
            category=ItemCategory.objects.create(name="Feed"),
            valuation_method="Weighted Average", standard_cost_per_unit=30,
            usage="Produced", source="Purchased", type="Raw Material",
            item_account="Expense")

    def deliver(self, qty, on):
        StockTransfer.objects.create(
            date=on, item=self.feed, quantity=Decimal(qty), rate=30,
            from_location_type="warehouse", from_warehouse=self.store,
            to_location_type="farm", to_farm=self.farm, to_batch=self.batch)

    def feed_day(self, qty, on):
        return DailyEntry.objects.create(
            farm=self.farm, batch=self.batch, supervisor=self.supervisor,
            date=on, feed_1=self.feed, feed_1_qty=Decimal(qty))

    # --- the opening balance --------------------------------------------

    def test_delivered_feed_is_the_opening_stock(self):
        # The reported bug: 1,000 kg delivered and the form said 0.
        self.deliver(1000, date(2026, 5, 1))
        self.assertEqual(
            DailyEntry.previous_stock(self.farm.id, self.feed.id,
                                      date(2026, 5, 2), None),
            Decimal("1000.00"))

    def test_nothing_delivered_is_still_zero(self):
        self.assertEqual(
            DailyEntry.previous_stock(self.farm.id, self.feed.id,
                                      date(2026, 5, 2), None), 0)

    def test_feeding_draws_the_balance_down_not_below_zero_by_itself(self):
        self.deliver(1000, date(2026, 5, 1))
        self.feed_day(120, date(2026, 5, 2))
        self.assertEqual(
            DailyEntry.previous_stock(self.farm.id, self.feed.id,
                                      date(2026, 5, 3), None),
            Decimal("880.00"))

    def test_a_delivery_mid_chain_shows_up_on_the_day_it_arrived(self):
        # Reading receipts once at the start would miss this entirely.
        self.deliver(500, date(2026, 5, 1))
        self.feed_day(100, date(2026, 5, 2))
        self.deliver(300, date(2026, 5, 3))
        self.assertEqual(
            DailyEntry.previous_stock(self.farm.id, self.feed.id,
                                      date(2026, 5, 4), None),
            Decimal("700.00"))

    def test_feeding_more_than_was_sent_still_reads_negative(self):
        # Negative is a real answer — it says the paperwork disagrees with the
        # shed — and must not be clamped away.
        self.deliver(50, date(2026, 5, 1))
        self.feed_day(80, date(2026, 5, 2))
        self.assertEqual(
            DailyEntry.previous_stock(self.farm.id, self.feed.id,
                                      date(2026, 5, 3), None),
            Decimal("-30.00"))

    # --- the stored chain -----------------------------------------------

    def test_the_stored_stock_matches_the_true_balance(self):
        from broiler.views import _recompute_stock_chain

        self.deliver(1000, date(2026, 5, 1))
        first = self.feed_day(100, date(2026, 5, 2))
        second = self.feed_day(150, date(2026, 5, 3))
        _recompute_stock_chain(self.farm.id, self.feed.id)

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.feed_1_stock, Decimal("900.00"))
        self.assertEqual(second.feed_1_stock, Decimal("750.00"))
        # And the closing figure is the farm's actual balance.
        self.assertEqual(second.feed_1_stock,
                         location_item_stock("farm", self.farm.id,
                                             self.feed.id, date(2026, 5, 3)))

    def test_receipts_balance_leaves_consumption_out(self):
        # It is what consumption is drawn *from*; counting the entries here as
        # well would subtract every one of them twice.
        self.deliver(1000, date(2026, 5, 1))
        self.feed_day(100, date(2026, 5, 2))
        self.assertEqual(
            farm_receipts_balance(self.farm.id, self.feed.id, date(2026, 5, 3)),
            Decimal("1000.00"))
        self.assertEqual(
            location_item_stock("farm", self.farm.id, self.feed.id,
                                date(2026, 5, 3)),
            Decimal("900.00"))

    def test_medicine_reads_its_farm_stock_the_same_way(self):
        self.deliver(200, date(2026, 5, 1))
        MedicineVaccineEntry.objects.create(
            farm=self.farm, batch=self.batch, supervisor=self.supervisor,
            date=date(2026, 5, 2), item=self.feed, qty=Decimal("30"))
        self.assertEqual(
            MedicineVaccineEntry.previous_stock(self.farm.id, self.feed.id,
                                                date(2026, 5, 3), None),
            Decimal("170.00"))


class RebuildCommandTests(TestCase):
    def test_it_is_idempotent(self):
        from django.core.management import call_command
        from io import StringIO

        out = StringIO()
        call_command("rebuild_farm_stock", stdout=out)
        again = StringIO()
        call_command("rebuild_farm_stock", stdout=again)
        self.assertIn("0 stored figures change", again.getvalue())
