"""Medicine sent to a flock on the Stock Transfer screen is medicine.

Medicine and vaccine reach a farm two ways — Inventory > Medicine Vaccine
Transfer, and an ordinary Stock Transfer of a medicine item — and the Batch
History Report only ever read the first. The second was filed as feed, because
the incoming split was "chicks, or else feed": a vaccine was listed under Feed
Transfer In, priced into feed cost, counted into a feed summary it could never
be eaten out of (Daily Entry cannot consume a vaccine), and absent from the
Medicine and Vaccine tables the reader went looking in.

The rule is one rule now (inventory.item_families.item_family) and it is a
positive one on both sides: a category named for chicks is chicks, one named
for feed is feed, anything else a flock is sent is medicine.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from broiler.models import (Branch, BroilerBatch, BroilerFarm, Farmer,
                            MedicineVaccineEntry, Region, Supervisor)
from broiler.views import _build_batch_report, _pending_item_balances
from inventory.item_families import item_family
from inventory.models import (Item, ItemCategory, MedicineTransfer,
                              MedicineTransferItem, StockTransfer, Warehouse)


class BatchReportMedicineFamilyTests(TestCase):

    def setUp(self):
        self.placed = timezone.localdate() - timedelta(days=45)
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region, prefix="AKB")
        self.supervisor = Supervisor.objects.create(branch=branch, name="A. Pal")
        farmer = Farmer.objects.create(farmer_name="Vishvanath")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=self.supervisor, farmer=farmer, region=region,
            line="Baskhari", farm_name="Vishvanath Farm", farm_capacity=5000)
        self.neighbour = BroilerFarm.objects.create(
            branch=branch, supervisor=self.supervisor, farmer=farmer, region=region,
            line="Baskhari", farm_name="Pappu Yadav Farm", farm_capacity=5000)
        self.batch = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="AKB-1102-1", book_number="BK",
            start_date=self.placed)
        self.store = Warehouse.objects.create(name="Akbarpur Warehouse")

        spec = dict(valuation_method="Weighted Average", usage="Produced",
                    source="Purchased", type="Raw Material", item_account="Expense")
        self.feed = Item.objects.create(description="Starter Feed", standard_cost_per_unit=42,
                                        category=ItemCategory.objects.create(name="Broiler Feed"),
                                        **spec)
        self.chick = Item.objects.create(description="Day Old Chick", standard_cost_per_unit=30,
                                         category=ItemCategory.objects.create(name="Day Old Chicks"),
                                         **spec)
        self.vaccine = Item.objects.create(description="Gumboro Vaccine", standard_cost_per_unit=5,
                                           category=ItemCategory.objects.create(name="Medicine"),
                                           **spec)
        self.place(1000)

    # --- movements -------------------------------------------------------

    def day(self, n):
        return self.placed + timedelta(days=n)

    def place(self, qty):
        StockTransfer.objects.create(
            date=self.placed, item=self.chick, quantity=qty, rate=30,
            from_location_type="warehouse", from_warehouse=self.store,
            to_location_type="farm", to_farm=self.farm, to_batch=self.batch)

    def stock_transfer_in(self, item, qty, rate, n=2):
        return StockTransfer.objects.create(
            date=self.day(n), item=item, quantity=Decimal(qty), rate=rate,
            from_location_type="warehouse", from_warehouse=self.store,
            to_location_type="farm", to_farm=self.farm, to_batch=self.batch)

    def stock_transfer_out(self, item, qty, rate, to_warehouse, n=40):
        destination = ({"to_location_type": "warehouse", "to_warehouse": self.store}
                       if to_warehouse else
                       {"to_location_type": "farm", "to_farm": self.neighbour})
        return StockTransfer.objects.create(
            date=self.day(n), item=item, quantity=Decimal(qty), rate=rate,
            from_location_type="farm", from_farm=self.farm, from_batch=self.batch,
            **destination)

    def medicine_transfer_in(self, qty, rate, n=3):
        mt = MedicineTransfer.objects.create(
            date=self.day(n), from_location_type="warehouse", from_warehouse=self.store,
            to_location_type="farm", to_farm=self.farm, to_batch=self.batch)
        MedicineTransferItem.objects.create(transfer=mt, item=self.vaccine,
                                            quantity=Decimal(qty), rate=rate)
        return mt

    def used(self, qty, n=10):
        MedicineVaccineEntry.objects.create(
            date=self.day(n), supervisor=self.supervisor, farm=self.farm,
            batch=self.batch, item=self.vaccine, qty=Decimal(qty))

    def report(self, fetch_type="farmer"):
        return _build_batch_report(self.batch, fetch_type=fetch_type)

    # --- the rule --------------------------------------------------------

    def test_item_family_names_the_three_families(self):
        self.assertEqual(item_family(self.chick), "chicks")
        self.assertEqual(item_family(self.feed), "feed")
        self.assertEqual(item_family(self.vaccine), "medicine")

    # --- transfers in ----------------------------------------------------

    def test_medicine_sent_on_a_stock_transfer_lands_in_the_medicine_table(self):
        self.stock_transfer_in(self.vaccine, 20, 5)
        report = self.report()
        self.assertEqual([(r["item"], r["quantity"]) for r in report["medicine_transfer_in"]],
                         [(str(self.vaccine), Decimal("20.00"))])
        self.assertEqual(report["feed_transfer_in"], [])

    def test_feed_is_still_feed(self):
        self.stock_transfer_in(self.feed, 500, 42)
        report = self.report()
        self.assertEqual([r["quantity"] for r in report["feed_transfer_in"]], [Decimal("500.00")])
        self.assertEqual(report["medicine_transfer_in"], [])
        # The running total is the feed column's own, and it no longer counts
        # what is no longer filed as feed.
        self.assertEqual(report["feed_transfer_in"][0]["cumulative"], Decimal("500.00"))

    def test_both_medicine_sources_share_one_table_in_date_order(self):
        self.medicine_transfer_in(10, 5, n=1)
        self.stock_transfer_in(self.vaccine, 20, 5, n=4)
        self.medicine_transfer_in(30, 5, n=7)
        report = self.report()
        self.assertEqual([r["quantity"] for r in report["medicine_transfer_in"]],
                         [Decimal("10.00"), Decimal("20.00"), Decimal("30.00")])

    def test_medicine_no_longer_inflates_the_feed_summary(self):
        self.stock_transfer_in(self.feed, 500, 42)
        self.stock_transfer_in(self.vaccine, 20, 5)
        self.assertEqual([r["item"] for r in self.report()["feed_summary"]],
                         [self.feed.description])

    # --- transfers out ---------------------------------------------------

    def test_medicine_returned_on_a_stock_transfer_is_a_medicine_return(self):
        self.stock_transfer_in(self.vaccine, 20, 5)
        self.stock_transfer_out(self.vaccine, 6, 5, to_warehouse=True)
        report = self.report()
        self.assertEqual([r["quantity"] for r in report["medicine_return"]], [Decimal("6.00")])
        self.assertEqual(report["feed_return"], [])

    def test_medicine_sent_on_to_another_farm_is_a_medicine_transfer_out(self):
        self.stock_transfer_in(self.vaccine, 20, 5)
        self.stock_transfer_out(self.vaccine, 6, 5, to_warehouse=False)
        report = self.report()
        self.assertEqual([(r["to_location"], r["quantity"]) for r in report["medicine_transfer_out"]],
                         [(self.neighbour.farm_name, Decimal("6.00"))])
        self.assertEqual(report["feed_transfer_out"], [])

    # --- what the misfiling cost ------------------------------------------

    def test_a_vaccine_no_longer_holds_the_batch_open_as_unconsumed_feed(self):
        """Used in full, the flock owes nothing. Counted as feed it owed 20
        units of a vaccine Daily Entry has no way to consume, and settlement
        was refused over stock that was not there."""
        self.stock_transfer_in(self.vaccine, 20, 5)
        self.used(20)
        self.assertEqual(_pending_item_balances(self.report()), [])

    def test_medicine_left_on_the_farm_is_still_pending_as_medicine(self):
        self.stock_transfer_in(self.vaccine, 20, 5)
        self.used(14)
        self.assertEqual(_pending_item_balances(self.report()),
                         [{"kind": "Medicine", "item": str(self.vaccine),
                           "balance": Decimal("6.00")}])

    def test_medicine_cost_is_medicine_cost_not_feed_cost(self):
        self.stock_transfer_in(self.vaccine, 20, 5)
        self.used(20)
        costing = self.report()["batch_costing"]
        self.assertEqual(Decimal(str(costing["med_cost"])), Decimal("100.00"))

    def test_management_basis_prices_a_stock_transferred_medicine_row(self):
        """The Management pass excludes the row being priced from the ledger
        replay by whichever key that row carries — a Stock Transfer's own id
        here, a Medicine Transfer line's id for the other source — and the two
        now sit in one list."""
        self.stock_transfer_in(self.vaccine, 20, 5)
        self.medicine_transfer_in(10, 5)
        rows = self.report(fetch_type="management")["medicine_transfer_in"]
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row["rate"], Decimal("5.00"))
            self.assertEqual(row["amount"], row["rate"] * row["quantity"])
