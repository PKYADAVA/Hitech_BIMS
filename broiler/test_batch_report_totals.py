"""Every detail table on the Batch History Report adds itself up.

Bird Sales had a Total row and Mortality had weekly subtotals; the eleven
tables between them left the reader to add a column of figures by hand to
answer "how much feed came in", "what did the medicine cost". They each carry
a Total row now, summed in the report engine rather than the template so the
footer and the costing block above it can never disagree, and so the totals
are worked out after the Management basis has repriced the rows.

Rate is not totalled anywhere -- per-unit rates added together mean nothing.
Neither is Feed Transfer-In's Cumulative, whose last row already is the total,
nor Medicine Consumption's Stock, which is a balance and not a flow.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from broiler.models import (Branch, BroilerBatch, BroilerFarm, DailyEntry,
                            Farmer, MedicineVaccineEntry, Region, Supervisor)
from broiler.views import _TABLE_TOTAL_COLUMNS, _build_batch_report
from inventory.models import (Item, ItemCategory, MedicineTransfer,
                              MedicineTransferItem, StockTransfer, Warehouse)


class BatchReportTableTotalsTests(TestCase):

    def setUp(self):
        self.placed = timezone.localdate() - timedelta(days=45)
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region, prefix="AKB")
        self.supervisor = Supervisor.objects.create(branch=branch, name="A. Pal")
        farmer = Farmer.objects.create(farmer_name="Vishvanath")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=self.supervisor, farmer=farmer, region=region,
            line="Baskhari", farm_name="Vishvanath Farm", farm_capacity=5000)
        self.batch = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="AKB-1102-1", book_number="BK",
            start_date=self.placed)
        self.store = Warehouse.objects.create(name="Akbarpur Warehouse")

        spec = dict(valuation_method="Weighted Average", usage="Produced",
                    source="Purchased", type="Raw Material", item_account="Expense")
        self.feed = Item.objects.create(description="Starter Feed", standard_cost_per_unit=42,
                                        category=ItemCategory.objects.create(name="Broiler Feed"),
                                        kg_per_bag=50, **spec)
        self.chick = Item.objects.create(description="Day Old Chick", standard_cost_per_unit=30,
                                         category=ItemCategory.objects.create(name="Day Old Chicks"),
                                         **spec)
        self.vaccine = Item.objects.create(description="Gumboro Vaccine", standard_cost_per_unit=5,
                                           category=ItemCategory.objects.create(name="Medicine"),
                                           **spec)

    def day(self, n):
        return self.placed + timedelta(days=n)

    def transfer_in(self, item, qty, rate, n):
        StockTransfer.objects.create(
            date=self.day(n), item=item, quantity=Decimal(qty), rate=Decimal(rate),
            from_location_type="warehouse", from_warehouse=self.store,
            to_location_type="farm", to_farm=self.farm, to_batch=self.batch)

    def report(self):
        return _build_batch_report(self.batch)

    # --- the sums themselves ---------------------------------------------

    def test_chick_placement_totals_quantity_and_amount(self):
        self.transfer_in(self.chick, 600, 30, 0)
        self.transfer_in(self.chick, 400, 32, 1)
        totals = self.report()["table_totals"]["chick_placement"]
        self.assertEqual(totals["quantity"], Decimal("1000.00"))
        self.assertEqual(totals["amount"], Decimal("30800.00"))

    def test_feed_transfer_in_totals_quantity_and_amount(self):
        self.transfer_in(self.feed, 500, 42, 1)
        self.transfer_in(self.feed, 250, 44, 8)
        totals = self.report()["table_totals"]["feed_transfer_in"]
        self.assertEqual(totals["quantity"], Decimal("750.00"))
        self.assertEqual(totals["amount"], Decimal("32000.00"))

    def test_medicine_transfer_in_totals_across_both_its_sources(self):
        """The table is fed by Medicine Vaccine Transfer lines and by Stock
        Transfers of a medicine item, and the Total row covers both."""
        mt = MedicineTransfer.objects.create(
            date=self.day(2), from_location_type="warehouse", from_warehouse=self.store,
            to_location_type="farm", to_farm=self.farm, to_batch=self.batch)
        MedicineTransferItem.objects.create(transfer=mt, item=self.vaccine,
                                            quantity=Decimal("2000"), rate=5)
        self.transfer_in(self.vaccine, 500, 6, 4)
        totals = self.report()["table_totals"]["medicine_transfer_in"]
        self.assertEqual(totals["quantity"], Decimal("2500.00"))
        self.assertEqual(totals["amount"], Decimal("13000.00"))

    def test_feed_summary_totals_every_movement_column(self):
        self.transfer_in(self.feed, 500, 42, 1)
        DailyEntry.objects.create(farm=self.farm, batch=self.batch, supervisor=self.supervisor,
                                  date=self.day(10), feed_1=self.feed,
                                  feed_1_qty=Decimal("460"))
        StockTransfer.objects.create(
            date=self.day(40), item=self.feed, quantity=Decimal("40"), rate=42,
            from_location_type="farm", from_farm=self.farm, from_batch=self.batch,
            to_location_type="warehouse", to_warehouse=self.store)
        totals = self.report()["table_totals"]["feed_summary"]
        self.assertEqual(totals["transfer_in"], Decimal("500.00"))
        self.assertEqual(totals["consumed"], Decimal("460.00"))
        self.assertEqual(totals["returned"], Decimal("40.00"))
        self.assertEqual(totals["balance"], Decimal("0.00"))

    def test_medicine_consumption_totals_quantity_only(self):
        MedicineVaccineEntry.objects.create(
            date=self.day(10), supervisor=self.supervisor, farm=self.farm,
            batch=self.batch, item=self.vaccine, qty=Decimal("1200"))
        MedicineVaccineEntry.objects.create(
            date=self.day(18), supervisor=self.supervisor, farm=self.farm,
            batch=self.batch, item=self.vaccine, qty=Decimal("700"))
        totals = self.report()["table_totals"]["medicine_consumption"]
        self.assertEqual(totals, {"quantity": Decimal("1900.00")})

    # --- what is deliberately left out ------------------------------------

    def test_rate_is_never_totalled(self):
        for columns in _TABLE_TOTAL_COLUMNS.values():
            self.assertNotIn("rate", columns)

    def test_running_columns_are_never_totalled(self):
        """Cumulative and Stock carry the running figure forward row by row,
        so adding the column up would give a number several times the truth."""
        self.assertNotIn("cumulative", _TABLE_TOTAL_COLUMNS["feed_transfer_in"])
        self.assertNotIn("stock", _TABLE_TOTAL_COLUMNS["medicine_consumption"])

    def test_an_empty_table_gets_no_total_row_at_all(self):
        """Nothing in, nothing to add up -- the key is absent rather than
        zero, so the template can hide the footer on the same test it uses to
        show the empty-state row."""
        self.assertEqual(self.report()["table_totals"], {})

    # --- the page itself ---------------------------------------------------

    def test_the_report_page_renders_the_total_rows(self):
        from django.contrib.auth import get_user_model

        self.transfer_in(self.chick, 1000, 30, 0)
        self.transfer_in(self.feed, 500, 42, 1)
        user = get_user_model().objects.create_superuser("rep", "r@x.com", "Str0ngPass!")
        self.client.force_login(user)
        html = self.client.get("/broiler-report/", {"batch": self.batch.id}).content.decode()
        self.assertIn("<tfoot>", html)
        # 1000 chicks at 30 and 500 kg at 42, each in its own table's footer.
        self.assertIn("30000.00", html)
        self.assertIn("21000.00", html)
