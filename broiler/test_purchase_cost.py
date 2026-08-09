"""Costing a flock at what the company actually paid.

The Growing Charge Statement values a batch at the rates agreed in the master —
what the farmer is paid against. The Production P&L asks what the flock cost
the company in money it really spent, so these rates come from purchases and
from nothing else.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from broiler.services.purchase_cost import purchase_rates, value_consumption
from inventory.models import Item, ItemCategory, UnitOfMeasurement, Warehouse
from purchase.models import GeneralPurchase, GeneralPurchaseItem, Supplier


class PurchaseRateTests(TestCase):
    def setUp(self):
        UnitOfMeasurement.objects.create(name="Kilogram")
        category = ItemCategory.objects.create(name="Feed")
        self.feed = self.item("Starter Feed", category)
        self.other = self.item("Finisher Feed", category)
        self.supplier = Supplier.objects.create(name="Maharashtra Feeds")
        # A purchase line must name exactly one destination.
        self.store = Warehouse.objects.create(name="Akbarpur Feed Store")

    @staticmethod
    def item(description, category):
        return Item.objects.create(description=description, category=category,
                                   valuation_method="fifo", standard_cost_per_unit=0,
                                   usage="raw_material", source="purchase")

    def buy(self, item, qty, amount, on=date(2026, 5, 1), free=0):
        purchase = GeneralPurchase.objects.create(supplier=self.supplier, date=on)
        return GeneralPurchaseItem.objects.create(
            purchase=purchase, item=item, farm_warehouse=self.store,
            sent_qty=qty, rcv_qty=qty, free_qty=free,
            rate=Decimal(str(amount)) / Decimal(str(qty)), amount=amount)

    def test_the_rate_is_what_was_paid(self):
        self.buy(self.feed, 100, 4000)
        self.assertEqual(purchase_rates([self.feed.id])[self.feed.id], Decimal("40.00"))

    def test_two_purchases_average_by_quantity_not_by_invoice(self):
        # 100 kg at 40 and 300 kg at 44 is 43 a kilo, not 42 — the larger load
        # weighs more, and averaging the two rates would understate the cost.
        self.buy(self.feed, 100, 4000)
        self.buy(self.feed, 300, 13200)
        self.assertEqual(purchase_rates([self.feed.id])[self.feed.id], Decimal("43.00"))

    def test_a_later_purchase_does_not_price_an_earlier_flock(self):
        # A price agreed in June cannot be what May's feed cost.
        self.buy(self.feed, 100, 4000, on=date(2026, 5, 1))
        self.buy(self.feed, 100, 9000, on=date(2026, 6, 1))
        rate = purchase_rates([self.feed.id], on_or_before=date(2026, 5, 31))
        self.assertEqual(rate[self.feed.id], Decimal("40.00"))

    def test_an_item_never_bought_has_no_rate_rather_than_zero(self):
        # Zero is a price. "Nothing to price this from" is not, and the report
        # has to be able to say so instead of showing a flock as cheaper.
        self.buy(self.feed, 100, 4000)
        rates = purchase_rates([self.feed.id, self.other.id])
        self.assertIn(self.feed.id, rates)
        self.assertNotIn(self.other.id, rates)

    def test_free_goods_lower_what_a_unit_cost(self):
        # 100 kg paid for and 25 free is 125 kg in the store for 4,000 — the
        # feed eaten cost 32 a kilo, not 40.
        self.buy(self.feed, 100, 4000, free=25)
        self.assertEqual(purchase_rates([self.feed.id])[self.feed.id], Decimal("32.00"))

    def test_a_purchase_that_nets_to_nothing_yields_no_rate(self):
        # A return against its own receipt. There is no rate in it, and
        # dividing would invent one.
        self.buy(self.feed, 100, 4000)
        self.buy(self.feed, -100, -4000)
        self.assertNotIn(self.feed.id, purchase_rates([self.feed.id]))


class ValueConsumptionTests(TestCase):
    def test_it_costs_each_row_at_its_own_rate(self):
        rates = {1: Decimal("40.00"), 2: Decimal("50.00")}
        rows = [{"item_id": 1, "quantity": 10}, {"item_id": 2, "quantity": 4}]
        total, unpriced = value_consumption(rows, rates)
        self.assertEqual(total, Decimal("600.00"))
        self.assertFalse(unpriced)

    def test_it_names_what_it_could_not_price(self):
        # A total that quietly omits an item reads as a cheaper flock rather
        # than an incomplete one — and that is a figure somebody decides on.
        rates = {1: Decimal("40.00")}
        rows = [{"item_id": 1, "quantity": 10}, {"item_id": 9, "quantity": 4}]
        total, unpriced = value_consumption(rows, rates)
        self.assertEqual(total, Decimal("400.00"))
        self.assertEqual(unpriced, {9})
