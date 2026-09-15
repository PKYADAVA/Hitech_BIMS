"""Item Not Priced: an active item holding stock with no price in force.

A transfer is valued at the Item Price List rate and refused without one, so
this is a transfer waiting to fail. The alert names the item once, however
many stores hold it: the fix is one price.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.utils import timezone

from alerthub import detectors
from alerthub.models import AlertRule, Notification
from inventory.models import Item, ItemCategory, ItemPriceList, Warehouse


class ItemNotPricedTests(TestCase):

    def setUp(self):
        from purchase.models import Supplier

        self.today = timezone.localdate()
        group = Group.objects.create(name="Stores")
        user = User.objects.create_user("storekeeper", password="x")
        user.groups.add(group)
        self.rule = AlertRule.objects.create(
            name="Item Not Priced", rule_key="inventory.item_not_priced",
            priority="high", operator="gte", is_active=True)
        self.rule.notify_groups.set([group])

        feed = ItemCategory.objects.create(name="Broiler Feed")
        common = dict(category=feed, valuation_method="Weighted Average", usage="Produced",
                      source="Purchased", type="Raw Material", item_account="Expense",
                      standard_cost_per_unit=0)
        self.grower = Item.objects.create(description="Grower Feed", **common)
        self.store = Warehouse.objects.create(name="Bahraich Warehouse")
        self.other_store = Warehouse.objects.create(name="Akbarpur Warehouse")
        self.supplier = Supplier.objects.create(name="Maharashtra Feeds Pvt Ltd")
        self.common = common

    def receive(self, item, qty, store=None):
        from purchase.models import GeneralPurchase, GeneralPurchaseItem

        purchase = GeneralPurchase.objects.create(date=self.today - timedelta(days=3),
                                                  supplier=self.supplier)
        GeneralPurchaseItem.objects.create(
            purchase=purchase, item=item, farm_warehouse=store or self.store, unit="Bag",
            rcv_qty=Decimal(str(qty)), rate=Decimal("2000"),
            discount_percent=Decimal("0"), discount_amount=Decimal("0"),
            gst_percent=Decimal("0"))

    def scan(self):
        detectors.autodiscover()
        detectors.get("inventory.item_not_priced")(self.rule)
        return list(Notification.objects.all())

    def test_stock_without_a_price_is_raised_once_per_item(self):
        self.receive(self.grower, 40)
        self.receive(self.grower, 25, store=self.other_store)
        alerts = self.scan()
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].title, "Item Not Priced")
        self.assertIn("Grower Feed", alerts[0].message)
        self.assertIn("2 locations", alerts[0].message)

    def test_a_priced_item_is_not_raised(self):
        self.receive(self.grower, 40)
        ItemPriceList.objects.create(item=self.grower, price=Decimal("2100"),
                                     effective_date=self.today - timedelta(days=1))
        self.assertEqual(self.scan(), [])

    def test_a_price_only_from_a_later_date_still_leaves_it_unpriced_today(self):
        self.receive(self.grower, 40)
        ItemPriceList.objects.create(item=self.grower, price=Decimal("2100"),
                                     effective_date=self.today + timedelta(days=5))
        self.assertEqual(len(self.scan()), 1)

    def test_an_inactive_item_is_not_raised(self):
        self.receive(self.grower, 40)
        self.grower.is_active = False
        self.grower.save(update_fields=["is_active"])
        self.assertEqual(self.scan(), [])

    def test_an_item_with_no_stock_is_not_raised(self):
        Item.objects.create(description="Finisher Feed", **self.common)
        self.assertEqual(self.scan(), [])

    def test_a_second_scan_does_not_repeat_it(self):
        self.receive(self.grower, 40)
        self.scan()
        self.assertEqual(len(self.scan()), 1)
