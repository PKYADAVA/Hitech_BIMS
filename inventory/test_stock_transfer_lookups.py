"""The Stock Transfer row's derived fields, for the phone.

A transfer row shows three things it does not ask for: the item's UOM, the
price effective on the row's date, and what is actually at the source location.
The web form fills them from two lookups; the phone had neither, so its row
showed "auto" forever.

Both endpoints call the same view functions the web form does, so a price rule
or a stock definition cannot apply on one client and not the other. These tests
are about that agreement as much as the values.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from inventory.models import Item, ItemCategory, StockTransfer, Warehouse

ITEM_URL = "/api/v1/inventory/stock-transfer-item"
STOCK_URL = "/api/v1/inventory/stock-transfer-stock"


class StockTransferLookupTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.warehouse = Warehouse.objects.create(name="Main Warehouse")
        self.item = Item.objects.create(
            description="Pre-Starter Feed",
            category=ItemCategory.objects.create(name="Feed"),
            valuation_method="Weighted Average", standard_cost_per_unit=30,
            usage="Produced", source="Purchased", type="Raw Material",
            item_account="Expense")

        User = get_user_model()
        self.user = User.objects.create_superuser("stl_user", "stl@x.com",
                                                  "Str0ngPass!")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def receive(self, quantity, days_ago=5):
        """Stock arriving into the warehouse."""
        return StockTransfer.objects.create(
            item=self.item, quantity=quantity, rate=30,
            date=self.today - timedelta(days=days_ago),
            from_location_type="warehouse", to_location_type="warehouse",
            to_warehouse=self.warehouse)

    # ---- the item lookup ----------------------------------------------------

    def test_the_item_lookup_answers(self):
        response = self.client.get(ITEM_URL, {"item": self.item.id,
                                              "date": self.today.isoformat()})
        self.assertEqual(response.status_code, 200)
        body = response.json()["data"]
        for key in ("unit", "rate", "price_missing", "message"):
            with self.subTest(field=key):
                self.assertIn(key, body)

    def test_it_says_when_there_is_no_price_rather_than_inventing_one(self):
        """The row flags a missing price instead of quietly showing zero."""
        body = self.client.get(ITEM_URL, {"item": self.item.id,
                                          "date": self.today.isoformat()}).json()["data"]
        if body["price_missing"]:
            self.assertTrue(body["message"])
        else:
            self.assertTrue(body["rate"])

    def test_an_unknown_item_is_empty_not_an_error(self):
        response = self.client.get(ITEM_URL, {"item": "999999",
                                              "date": self.today.isoformat()})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["unit"], "")

    # ---- the stock lookup ---------------------------------------------------

    def test_stock_reflects_what_arrived(self):
        self.receive(500)
        body = self.client.get(STOCK_URL, {
            "location_type": "warehouse", "location_id": self.warehouse.id,
            "item": self.item.id, "date": self.today.isoformat()}).json()["data"]
        self.assertEqual(float(body["stock"]), 500.0)

    def test_stock_is_as_of_the_row_s_date_not_today(self):
        """A backdated row must be judged against the stock of that day."""
        self.receive(500, days_ago=2)
        body = self.client.get(STOCK_URL, {
            "location_type": "warehouse", "location_id": self.warehouse.id,
            "item": self.item.id,
            "date": (self.today - timedelta(days=10)).isoformat()}).json()["data"]
        self.assertEqual(float(body["stock"]), 0.0)

    def test_an_empty_location_reports_zero_not_an_error(self):
        body = self.client.get(STOCK_URL, {
            "location_type": "warehouse", "location_id": self.warehouse.id,
            "item": self.item.id, "date": self.today.isoformat()}).json()["data"]
        self.assertEqual(float(body["stock"]), 0.0)

    def test_missing_parameters_are_answered_with_zero(self):
        response = self.client.get(STOCK_URL, {"item": self.item.id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(float(response.json()["data"]["stock"]), 0.0)

    # ---- both are behind the login ------------------------------------------

    def test_both_require_authentication(self):
        anon = APIClient()
        for url in (ITEM_URL, STOCK_URL):
            with self.subTest(url=url):
                self.assertIn(anon.get(url).status_code, (401, 403))
