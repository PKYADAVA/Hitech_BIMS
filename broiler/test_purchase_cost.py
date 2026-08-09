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


class ProductionPLTests(TestCase):
    """The statement itself, from an already-built batch report."""

    def build(self, **over):
        from broiler.services.production_pl import build_production_pl

        report = {
            "batch_costing": {"sold_weight": 3000, "sold_birds": 1500,
                              "chicks_placed": 1600, "fcr": Decimal("1.58")},
            "bird_sales": [{"amount": 300000}],
            # The report calls it chick_placement, singular. The fixture had
            # the plural, so it agreed with the bug instead of catching it.
            "chick_placement": [{"amount": 56000, "birds": 1600}],
            "feed_summary": [], "medicine_consumption": [],
        }
        report.update(over)
        return build_production_pl(report, batch=None)

    def test_revenue_is_what_the_birds_sold_for(self):
        pl = self.build()
        self.assertEqual(pl["total_revenue"], Decimal("300000.00"))

    def test_profit_is_revenue_less_the_costs_that_are_tracked(self):
        pl = self.build()
        self.assertEqual(pl["total_cost"], Decimal("56000.00"))
        self.assertEqual(pl["gross_profit"], Decimal("244000.00"))

    def test_untracked_heads_are_shown_rather_than_dropped(self):
        # An absent row reads as a complete statement. A row saying nothing is
        # recorded reads as the truth.
        pl = self.build()
        untracked = [l["label"] for l in pl["cost_lines"] if not l["tracked"]]
        self.assertIn("Labour", untracked)
        self.assertIn("Depreciation", untracked)
        self.assertTrue(all(l["amount"] is None for l in pl["cost_lines"]
                            if not l["tracked"]))

    def test_it_says_where_the_untracked_figures_came_from(self):
        # They are typed against the batch, not posted anywhere — and a head
        # nobody filled in is not counted as zero. Both need saying, or the
        # total reads as though the system knew.
        note = self.build()["untracked_note"]
        self.assertIn("entered by hand", note)
        self.assertIn("blank are not counted", note)

    def test_a_head_nobody_filled_in_is_not_counted_as_zero(self):
        # "Electricity: 0" says the flock used none. Blank says nobody has told
        # us yet, and only one of those is true.
        pl = self.build()
        growing = [b for b in pl["cost_blocks"] if b["title"] == "Growing Expenses"][0]
        self.assertIsNone(growing["total"])
        self.assertTrue(all(line["amount"] is None for line in growing["lines"]))

    def test_a_flock_that_sold_nothing_does_not_divide_by_zero(self):
        pl = self.build(bird_sales=[], batch_costing={"sold_weight": 0, "sold_birds": 0,
                                                      "chicks_placed": 1600})
        self.assertEqual(pl["profit_per_kg"], Decimal("0.00"))
        self.assertEqual(pl["profit_pct"], Decimal("0.00"))
