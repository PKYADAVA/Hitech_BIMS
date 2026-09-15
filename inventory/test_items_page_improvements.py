"""Items page improvements: the sectioned item form, Source, Item Account and
the Active switch saved on create, required fields named per field, and the
list's price and stock columns.
"""
import json
from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from inventory.models import Item, ItemPriceList
from inventory.services.item_summary import stock_on_hand_by_item
from inventory.services.price_list import current_prices
from inventory.test_items_page import ItemsPageBase


class ItemFormTests(ItemsPageBase):

    def create(self, **overrides):
        body = {"description": "Grower Feed", "category": self.feed.id,
                "valuation_method": "FIFO", "standard_cost_per_unit": 40, "usage": "Produced",
                "warehouse": [self.north.id]}
        body.update(overrides)
        return self.client.post(reverse("item_create"), json.dumps(body), content_type="application/json")

    def test_source_account_and_active_are_saved_on_create(self):
        response = self.create(source="Purchased", item_account="Asset", is_active=False)
        self.assertEqual(response.status_code, 201, response.content)
        item = Item.objects.get(id=response.json()["id"])
        self.assertEqual((item.source, item.item_account, item.is_active), ("Purchased", "Asset", False))
        self.assertEqual(response.json()["item_code"], item.item_code)

    def test_active_is_the_default(self):
        item = Item.objects.get(id=self.create().json()["id"])
        self.assertTrue(item.is_active)

    def test_a_missing_required_field_is_named(self):
        response = self.create(description="  ")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["field"], "description")
        response = self.create(usage="")
        self.assertEqual(response.json()["field"], "usage")

    def test_zero_standard_cost_is_allowed(self):
        self.assertEqual(self.create(standard_cost_per_unit=0).status_code, 201)

    def test_the_active_switch_saves_on_edit(self):
        response = self.client.put(f"/item/{self.starter.id}/", json.dumps({"is_active": False}),
                                   content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.starter.refresh_from_db()
        self.assertFalse(self.starter.is_active)

    def test_the_page_offers_the_new_form(self):
        response = self.client.get(reverse("items"))
        for text in ("Save and Add Another", 'id="itl-wh-list"', 'id="source"', 'id="item_account"',
                     'id="is_active"', "Units and Packing", "Stock on Hand"):
            self.assertContains(response, text)
        self.assertEqual(dict(response.context["source_choices"]), dict(Item.SOURCE_CHOICES))


class PriceAndStockColumnTests(ItemsPageBase):

    def receive(self, qty):
        from purchase.models import GeneralPurchase, GeneralPurchaseItem, Supplier

        purchase = GeneralPurchase.objects.create(
            date=timezone.localdate() - timedelta(days=2),
            supplier=Supplier.objects.create(name="Maharashtra Feeds Pvt Ltd"))
        GeneralPurchaseItem.objects.create(
            purchase=purchase, item=self.starter, farm_warehouse=self.north, unit="Bag",
            rcv_qty=Decimal(str(qty)), rate=Decimal("42"), discount_percent=Decimal("0"),
            discount_amount=Decimal("0"), gst_percent=Decimal("0"))

    def test_the_list_shows_the_price_in_force_and_stock_on_hand(self):
        today = timezone.localdate()
        ItemPriceList.objects.create(item=self.starter, price=Decimal("40"), effective_date=today - timedelta(days=30))
        ItemPriceList.objects.create(item=self.starter, price=Decimal("44"), effective_date=today - timedelta(days=3))
        ItemPriceList.objects.create(item=self.starter, price=Decimal("50"), effective_date=today + timedelta(days=5))
        self.receive(120)
        row = next(r for r in self.client.get(reverse("item_list")).json() if r["id"] == self.starter.id)
        self.assertEqual((row["current_price"], row["price_date"]),
                         ("44.00", (today - timedelta(days=3)).isoformat()))
        self.assertEqual(row["stock_on_hand"], "120.00")

    def test_an_unpriced_item_has_no_price(self):
        row = next(r for r in self.client.get(reverse("item_list")).json() if r["id"] == self.starter.id)
        self.assertIsNone(row["current_price"])
        self.assertEqual(row["stock_on_hand"], "0.00")

    def test_the_view_dialog_gets_price_and_stock_too(self):
        ItemPriceList.objects.create(item=self.starter, price=Decimal("44"),
                                     effective_date=timezone.localdate() - timedelta(days=3))
        self.receive(30)
        detail = self.client.get(f"/item/{self.starter.id}/").json()
        self.assertEqual((detail["current_price"], detail["stock_on_hand"]), ("44.00", "30.00"))

    def test_the_helpers(self):
        self.receive(10)
        self.assertEqual(stock_on_hand_by_item()[self.starter.id], Decimal("10"))
        self.assertEqual(current_prices([self.starter.id]), {})

    def test_the_price_list_opens_already_searched_from_a_link(self):
        response = self.client.get(reverse("item_price_list"), {"search": self.starter.item_code})
        self.assertContains(response, "INITIAL_SEARCH")
