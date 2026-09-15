"""Item Price List improvements: margin over purchase cost, repricing from the
last purchase, the transfers a price covers, change log filters, letterhead.

The unit question runs through the first two. A bill is typed per whatever
unit the supplier sold in and a price is per the item's own unit, so a feed
bought at 42 per Kg and priced at 2,000 per Bag has to be restated before the
two are compared, and left uncompared when they cannot be matched.
"""
from datetime import timedelta
from decimal import Decimal

from django.urls import reverse

from inventory.models import (Item, ItemPriceList, ItemPriceListAudit,
                              MedicineTransfer, MedicineTransferItem,
                              StockTransfer, UnitOfMeasurement, Warehouse)
from inventory.services.price_list import (price_overview, price_usage,
                                           purchase_rate_per_price_unit,
                                           revise_preview)
from inventory.test_item_price_list import PriceListBase


class PurchaseBase(PriceListBase):

    def setUp(self):
        super().setUp()
        from purchase.models import Supplier

        self.store = Warehouse.objects.create(name="Bahraich Warehouse")
        self.mills = Supplier.objects.create(name="Maharashtra Feeds Pvt Ltd")
        bag = UnitOfMeasurement.objects.create(name="Bag", symbol="Bag")
        self.grower = Item.objects.create(
            description="Grower Feed", category=self.feed, type="Raw Material",
            storage_uom=bag, kg_per_bag=Decimal("50"), valuation_method="Weighted Average",
            usage="Produced", source="Purchased", item_account="Expense",
            standard_cost_per_unit=0)
        self.loose = Item.objects.create(
            description="Loose Grit", category=self.feed, type="Raw Material",
            storage_uom=bag, valuation_method="Weighted Average", usage="Produced",
            source="Purchased", item_account="Expense", standard_cost_per_unit=0)

    def buy(self, item, rate, days, unit):
        from purchase.models import GeneralPurchase, GeneralPurchaseItem

        purchase = GeneralPurchase.objects.create(date=self.day(days), supplier=self.mills)
        GeneralPurchaseItem.objects.create(
            purchase=purchase, item=item, farm_warehouse=self.store, unit=unit,
            rcv_qty=Decimal("100"), rate=Decimal(str(rate)),
            discount_percent=Decimal("0"), discount_amount=Decimal("0"),
            gst_percent=Decimal("0"))


class CostMarginTests(PurchaseBase):

    def test_the_same_unit_is_compared_as_it_stands(self):
        self.price(self.starter, 44, -5)
        self.buy(self.starter, 40, -3, unit="Kg")
        row = self.row_for(price_overview(today=self.today), self.starter)
        self.assertEqual((row["cost_rate"], row["margin_pct"], row["below_cost"]),
                         ("40.00", "10.00", False))

    def test_a_price_under_the_last_purchase_is_flagged(self):
        self.price(self.starter, 38, -5)
        self.buy(self.starter, 40, -3, unit="Kg")
        row = self.row_for(price_overview(today=self.today), self.starter)
        self.assertTrue(row["below_cost"])
        self.assertEqual(row["margin_pct"], "-5.00")

    def test_bought_per_kg_is_restated_per_bag(self):
        """42 a Kg at 50 Kg a Bag is 2,100 a Bag, so 2,000 a Bag is below cost."""
        self.price(self.grower, 2000, -5)
        self.buy(self.grower, 42, -3, unit="Kg")
        row = self.row_for(price_overview(today=self.today), self.grower)
        self.assertEqual((row["cost_rate"], row["below_cost"]), ("2100.00", True))
        self.assertEqual(purchase_rate_per_price_unit(self.grower, Decimal("2100"), "Bag"),
                         Decimal("2100.00"))

    def test_units_that_cannot_be_matched_are_not_compared(self):
        """No Kg per Bag on the item: better no comparison than a wrong one."""
        self.price(self.loose, 300, -5)
        self.buy(self.loose, 7, -3, unit="Kg")
        row = self.row_for(price_overview(today=self.today), self.loose)
        self.assertIsNone(row["margin_pct"])
        self.assertFalse(row["below_cost"])
        self.assertIn("Kg per Bag", row["cost_note"])

    def test_no_purchase_means_no_margin(self):
        self.price(self.vaccine, 5, -5)
        row = self.row_for(price_overview(today=self.today), self.vaccine)
        self.assertEqual((row["margin_pct"], row["cost_note"]), (None, ""))


class ReviseFromPurchaseTests(PurchaseBase):

    def test_marks_up_the_restated_purchase_rate(self):
        self.price(self.grower, 2000, -5)
        self.buy(self.grower, 42, -3, unit="Kg")
        row = revise_preview([self.grower.id], "purchase", "5", self.day(1))["rows"][0]
        self.assertEqual((row["base_rate"], row["new_price"], row["action"]),
                         ("2100.00", "2205.00", "create"))
        self.assertEqual(row["current_price"], "2000.00")

    def test_a_change_over_half_is_flagged_for_a_unit_check(self):
        """Priced 42 per Bag but bought at 42 per Kg: repricing would be 2,100,
        which is almost always a price typed in the wrong unit."""
        self.price(self.grower, 42, -5)
        self.buy(self.grower, 42, -3, unit="Kg")
        row = revise_preview([self.grower.id], "purchase", "0", self.day(1))["rows"][0]
        self.assertEqual(row["new_price"], "2100.00")
        self.assertTrue(row["large_change"])
        self.assertIn("check the item's unit", row["message"])

    def test_an_ordinary_change_is_not_flagged(self):
        self.price(self.grower, 2000, -5)
        self.buy(self.grower, 42, -3, unit="Kg")
        row = revise_preview([self.grower.id], "purchase", "0", self.day(1))["rows"][0]
        self.assertNotIn("large_change", row)

    def test_zero_matches_the_purchase_rate(self):
        self.buy(self.grower, 42, -3, unit="Kg")
        row = revise_preview([self.grower.id], "purchase", "0", self.day(1))["rows"][0]
        self.assertEqual(row["new_price"], "2100.00")

    def test_prices_an_item_that_has_no_price_yet(self):
        self.buy(self.tonic, 300, -3, unit="")
        row = revise_preview([self.tonic.id], "purchase", "10", self.day(1))["rows"][0]
        self.assertEqual((row["current_price"], row["new_price"], row["action"]),
                         (None, "330.00", "create"))

    def test_an_item_never_bought_is_skipped(self):
        self.price(self.vaccine, 5, -5)
        row = revise_preview([self.vaccine.id], "purchase", "10", self.day(1))["rows"][0]
        self.assertEqual((row["action"], row["message"]), ("skip", "No purchase rate to work from"))

    def test_unmatched_units_are_skipped(self):
        self.buy(self.loose, 7, -3, unit="Kg")
        row = revise_preview([self.loose.id], "purchase", "10", self.day(1))["rows"][0]
        self.assertEqual(row["action"], "skip")
        self.assertIn("units do not match", row["message"])


class PriceUsageTests(PriceListBase):

    def setUp(self):
        super().setUp()
        self.store = Warehouse.objects.create(name="Bahraich Warehouse")
        self.branch_store = Warehouse.objects.create(name="Akbarpur Warehouse")

    def transfer(self, days):
        StockTransfer.objects.create(
            date=self.day(days), item=self.starter, quantity=Decimal("10"), rate=Decimal("40"),
            from_location_type="warehouse", from_warehouse=self.store,
            to_location_type="warehouse", to_warehouse=self.branch_store)

    def medicine_transfer(self, days):
        header = MedicineTransfer.objects.create(
            date=self.day(days), from_location_type="warehouse", from_warehouse=self.store,
            to_location_type="warehouse", to_warehouse=self.branch_store)
        MedicineTransferItem.objects.create(transfer=header, item=self.starter,
                                            quantity=Decimal("2"), rate=Decimal("40"))

    def test_counts_the_transfers_up_to_the_next_price(self):
        first = self.price(self.starter, 40, -30)
        second = self.price(self.starter, 42, -10)
        self.transfer(-20)
        self.medicine_transfer(-25)
        self.transfer(-5)
        self.assertEqual(price_usage(first), {
            "from": self.day(-30).isoformat(), "until": self.day(-10).isoformat(),
            "stock_transfers": 1, "medicine_transfers": 1,
        })
        self.assertEqual(price_usage(second)["stock_transfers"], 1)
        self.assertIsNone(price_usage(second)["until"])

    def test_the_page_asks_for_it(self):
        entry = self.price(self.starter, 40, -30)
        self.transfer(-2)
        res = self.client.get(reverse("item_price_list_usage_data", args=[entry.id])).json()
        self.assertEqual(res["stock_transfers"], 1)

    def test_it_needs_view_rights_on_the_price_list(self):
        from user.access import derive_tab, resolve_action
        name = "item_price_list_usage_data"
        self.assertEqual(resolve_action(name) or derive_tab(name), ("item_price_list", "view"))


class ChangeLogFilterTests(PriceListBase):

    def setUp(self):
        super().setUp()
        entry = self.price(self.starter, 40, -5)
        entry.price = Decimal("41")
        entry.save()
        self.price(self.vaccine, 5, -5).delete()

    def rows(self, **params):
        return self.client.get(reverse("item_price_list_audit_data"), params).json()

    def test_filters_by_action(self):
        rows = self.rows(action="delete")["rows"]
        self.assertEqual([r["action"] for r in rows], ["delete"])

    def test_offers_the_sources_and_filters_by_one(self):
        res = self.rows()
        self.assertEqual(res["options"]["sources"], ["System"])
        self.assertEqual(len(self.rows(source="System")["rows"]), ItemPriceListAudit.objects.count())
        self.assertEqual(self.rows(source="Upload")["rows"], [])

    def test_filters_by_date(self):
        self.assertEqual(self.rows(date_to=self.day(-1).isoformat())["rows"], [])
        self.assertEqual(len(self.rows(date_from=self.today.isoformat())["rows"]), 4)


class LetterheadTests(PriceListBase):

    def test_the_page_carries_the_company_for_printed_exports(self):
        from account.models import CompanyProfile

        from django.core.cache import cache

        company = CompanyProfile.get_solo()
        company.name = "Hi Tech Farms"
        company.save()
        # The page reads the company through a five-minute cache; an earlier
        # test in the same run may have filled it with a different name.
        cache.delete("company_profile_solo")
        response = self.client.get(reverse("item_price_list"))
        self.assertContains(response, 'data-co-name="Hi Tech Farms"')
        self.assertContains(response, "pdfLetterhead")
