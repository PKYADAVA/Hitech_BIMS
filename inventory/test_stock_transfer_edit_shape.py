"""What an existing Stock Transfer hands back when the phone opens it to edit.

The phone's transfer form keeps date, DC number, both locations and the
logistics *on the row*, because the web grid does: one sheet moves different
items between different pairs of stores, and a single header cannot say that.
The edit loader returned those under "header" instead, so opening a transfer
showed From Location and To Location empty on a record that plainly had both —
and the payload builder reads them off the row, so saving would have sent the
blanks back over a real transfer.

Nothing in the suite noticed, because the two halves live in different
languages: the field layout is TypeScript, the loader is here. This is the
agreement written down on the Python side.
"""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from broiler.models import Branch, BroilerFarm, Farmer, Region, Supervisor
from inventory.api_write import _load_stock_transfer
from inventory.models import Item, ItemCategory, StockTransfer, Warehouse

#: Every key the phone's row renders. Adding a field to the row means adding it
#: here, which is the point: a field the loader forgets renders empty.
ROW_KEYS = {
    "date", "dc_no", "item", "quantity", "rate",
    "from_type", "from_id", "from_batch",
    "to_type", "to_id", "to_batch",
    "vehicle_no", "driver_name", "remarks",
}


class StockTransferEditShapeTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user("tx_editor", "e@x.com", "Str0ngPass!")
        region = Region.objects.create(description="East")
        self.branch = Branch.objects.create(branch_name="Bahraich", region=region,
                                            prefix="BHR")
        self.source = Warehouse.objects.create(name="Akbarpur", code="WH1")
        category = ItemCategory.objects.create(name="Feed")
        self.item = Item.objects.create(
            description="Pre Starter", category=category,
            valuation_method="Weighted Average", standard_cost_per_unit=50,
            usage="Produced", source="Purchased", type="Raw Material",
            item_account="Expense")
        supervisor = Supervisor.objects.create(name="Ram", branch=self.branch)
        farmer = Farmer.objects.create(farmer_name="Shyam")
        self.farm = BroilerFarm.objects.create(
            farm_name="Green Valley", branch=self.branch, supervisor=supervisor,
            farmer=farmer, farm_type="Own", farm_capacity=1000)

        self.transfer = StockTransfer.objects.create(
            date=date(2026, 7, 21), dc_no="2345", item=self.item, quantity=100,
            rate=35, from_location_type="warehouse", from_warehouse=self.source,
            to_location_type="farm", to_farm=self.farm,
            vehicle_no="UP53 AA 1111", driver_name="Mohan", remarks="moved")

    def test_the_row_carries_everything_the_form_renders(self):
        row = _load_stock_transfer(self.transfer)["items"][0]
        self.assertEqual(ROW_KEYS - set(row), set(),
                         "these render empty in the phone's edit form")

    def test_the_locations_come_back_on_the_row(self):
        """The bug: both pickers opened empty on a record that had both."""
        row = _load_stock_transfer(self.transfer)["items"][0]
        self.assertEqual(row["from_type"], "warehouse")
        self.assertEqual(row["from_id"], str(self.source.id))
        self.assertEqual(row["to_type"], "farm")
        self.assertEqual(row["to_id"], str(self.farm.id))

    def test_the_date_and_dc_number_are_the_rows_own(self):
        """They sit per row, as the web grid's columns do."""
        row = _load_stock_transfer(self.transfer)["items"][0]
        self.assertEqual(row["date"], "2026-07-21")
        self.assertEqual(row["dc_no"], "2345")

    def test_nothing_is_left_on_the_header(self):
        """The form has no header card for this document to fill."""
        self.assertEqual(_load_stock_transfer(self.transfer)["header"], {})
