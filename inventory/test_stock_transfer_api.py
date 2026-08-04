"""Creating a Stock Transfer from the phone.

The endpoint was registered read-only, so the app could list transfers and
never add one — the Stock Transfer tab existed but could not do the thing it
is for.

Making it writable is not just a flag. Running stock is stored on each row and
walked chronologically from the source location, so a transfer inserted among
existing ones leaves every later row's stock wrong until the chain is
recomputed. The web POST does that; a plain DRF create would not, and the
damage would be silent — the rows save fine and only the stock figures are
wrong.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from inventory.models import Item, ItemCategory, StockTransfer, Warehouse

URL = "/api/v1/inventory/stock-transfers/"


class StockTransferApiTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.source = Warehouse.objects.create(name="Central Store")
        self.destination = Warehouse.objects.create(name="Akbarpur Store")
        self.item = Item.objects.create(
            description="Starter Feed",
            category=ItemCategory.objects.create(name="Feed"),
            valuation_method="Weighted Average", standard_cost_per_unit=30,
            usage="Produced", source="Purchased", type="Raw Material",
            item_account="Expense")

        User = get_user_model()
        self.user = User.objects.create_superuser("st_api", "st@x.com",
                                                  "Str0ngPass!")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def payload(self, **over):
        body = {
            "date": self.today.isoformat(),
            "item": self.item.id,
            "quantity": "100",
            "rate": "30",
            "from_location_type": "warehouse",
            "from_warehouse": self.source.id,
            "to_location_type": "warehouse",
            "to_warehouse": self.destination.id,
            "dc_no": "DC-1",
            "vehicle_no": "UP53 XX 1234",
            "driver_name": "R. Verma",
        }
        body.update(over)
        return body

    # ---- the tab can do its job at all --------------------------------------

    def test_the_phone_can_create_a_transfer(self):
        response = self.client.post(URL, self.payload(), format="json")
        self.assertIn(response.status_code, (200, 201), response.content[:300])
        self.assertEqual(StockTransfer.objects.count(), 1)

    def test_what_was_sent_is_what_is_stored(self):
        self.client.post(URL, self.payload(), format="json")
        row = StockTransfer.objects.get()
        self.assertEqual(row.item_id, self.item.id)
        self.assertEqual(row.quantity, Decimal("100"))
        self.assertEqual(row.from_warehouse_id, self.source.id)
        self.assertEqual(row.to_warehouse_id, self.destination.id)
        self.assertEqual(row.driver_name, "R. Verma")

    def test_listing_still_works(self):
        self.client.post(URL, self.payload(), format="json")
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)

    # ---- the side effect a plain create would skip ---------------------------

    def test_a_backdated_transfer_repairs_the_rows_after_it(self):
        """Stock is walked from the source location in date order. Inserting an
        earlier transfer has to correct every later row, or the register shows
        stock that never existed."""
        self.client.post(URL, self.payload(date=self.today.isoformat(),
                                           quantity="10"), format="json")
        later = StockTransfer.objects.get()
        stock_before = later.stock

        # An earlier transfer out of the same store, for the same item.
        self.client.post(URL, self.payload(
            date=(self.today - timedelta(days=5)).isoformat(),
            quantity="40"), format="json")

        later.refresh_from_db()
        self.assertNotEqual(later.stock, stock_before,
                            "the later row's stock was left as it was — the "
                            "chain was not recomputed")

    def test_rows_out_of_a_different_store_are_left_alone(self):
        other = Warehouse.objects.create(name="Bahraich Store")
        self.client.post(URL, self.payload(from_warehouse=other.id,
                                           quantity="7"), format="json")
        untouched = StockTransfer.objects.get(from_warehouse=other)
        before = untouched.stock

        self.client.post(URL, self.payload(
            date=(self.today - timedelta(days=3)).isoformat()), format="json")

        untouched.refresh_from_db()
        self.assertEqual(untouched.stock, before)

    # ---- the rule the whole ERP shares --------------------------------------

    def test_a_transfer_dated_tomorrow_is_refused(self):
        response = self.client.post(
            URL, self.payload(date=(self.today + timedelta(days=1)).isoformat()),
            format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("later than today", str(response.content))
        self.assertEqual(StockTransfer.objects.count(), 0)

    def test_today_is_still_allowed(self):
        response = self.client.post(URL, self.payload(), format="json")
        self.assertIn(response.status_code, (200, 201))

    def test_signing_in_is_required(self):
        anon = APIClient()
        self.assertIn(anon.post(URL, self.payload(), format="json").status_code,
                      (401, 403))
