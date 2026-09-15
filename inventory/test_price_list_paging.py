"""Item Price List paging: the server sends one page at a time.

The list used to load every item into the browser. Now the filters, counts,
sort and page are answered by the server, only the page on screen is built in
full, and the two things that need every matching item (Select all, and a Bulk
Revise with nothing ticked) ask for the matching ids instead of reading the
page.
"""
from datetime import timedelta
from decimal import Decimal

from django.urls import reverse

from inventory.models import Item, ItemPriceList, Warehouse
from inventory.test_item_price_list import PriceListBase


class PagingTests(PriceListBase):

    def setUp(self):
        super().setUp()
        common = dict(category=self.feed, valuation_method="Weighted Average", usage="Produced",
                      source="Purchased", type="Raw Material", item_account="Expense",
                      standard_cost_per_unit=0)
        self.bulk = []
        for n in range(30):
            item = Item.objects.create(description=f"Bulk Feed {n:02d}", **common)
            ItemPriceList.objects.create(item=item, price=Decimal(100 + n),
                                         effective_date=self.day(-5))
            self.bulk.append(item)
        self.price(self.vaccine, 5, 3)  # upcoming; tonic and starter stay unpriced

    def page(self, **extra):
        params = {"draw": "7", "start": "0", "length": "10",
                  "columns[2][data]": "item_code", "order[0][column]": "2", "order[0][dir]": "asc"}
        params.update(extra)
        return self.client.get(reverse("item_price_list_overview_data"), params).json()

    def codes_in_order(self):
        return list(Item.objects.order_by("item_code").values_list("item_code", flat=True))

    def test_sends_one_page_with_the_totals(self):
        res = self.page()
        self.assertEqual(res["draw"], 7)
        self.assertEqual((res["recordsTotal"], res["recordsFiltered"]), (33, 33))
        self.assertEqual(len(res["data"]), 10)
        self.assertEqual([r["item_code"] for r in res["data"]], self.codes_in_order()[:10])

    def test_the_next_page_carries_on(self):
        res = self.page(start="10")
        self.assertEqual([r["item_code"] for r in res["data"]], self.codes_in_order()[10:20])

    def test_sorts_by_price_highest_first_with_unpriced_last(self):
        res = self.page(**{"columns[7][data]": "price", "order[0][column]": "7",
                           "order[0][dir]": "desc", "length": "-1"})
        prices = [r["price"] for r in res["data"]]
        priced = [Decimal(p) for p in prices if p is not None]
        self.assertEqual(priced, sorted(priced, reverse=True))
        self.assertEqual(prices[-2:], [None, None])

    def test_a_column_the_database_cannot_sort_falls_back_to_item_code(self):
        res = self.page(**{"columns[6][data]": "last_purchase", "order[0][column]": "6"})
        self.assertEqual([r["item_code"] for r in res["data"]], self.codes_in_order()[:10])

    def test_counts_every_status_and_filters_by_one(self):
        res = self.page(status="not_priced")
        self.assertEqual(res["counts"], {"all": 33, "active": 30, "inactive": 0,
                                         "upcoming": 1, "not_priced": 2})
        self.assertEqual(res["recordsFiltered"], 2)
        self.assertEqual({r["item"] for r in res["data"]}, {self.starter.id, self.tonic.id})

    def test_an_inactive_item_is_counted_as_inactive(self):
        self.bulk[0].is_active = False
        self.bulk[0].save(update_fields=["is_active"])
        res = self.page(status="inactive")
        self.assertEqual([r["item"] for r in res["data"]], [self.bulk[0].id])
        self.assertEqual(res["counts"]["active"], 29)

    def test_searches_by_name_or_code(self):
        res = self.page(**{"search[value]": "gumboro"})
        self.assertEqual([r["item"] for r in res["data"]], [self.vaccine.id])

    def test_filters_by_category(self):
        res = self.page(category=str(self.medicine.id))
        self.assertEqual({r["item"] for r in res["data"]}, {self.vaccine.id, self.tonic.id})

    def test_below_cost_is_filtered_across_every_page(self):
        from purchase.models import GeneralPurchase, GeneralPurchaseItem, Supplier

        store = Warehouse.objects.create(name="Bahraich Warehouse")
        purchase = GeneralPurchase.objects.create(
            date=self.day(-2), supplier=Supplier.objects.create(name="Maharashtra Feeds Pvt Ltd"))
        GeneralPurchaseItem.objects.create(
            purchase=purchase, item=self.bulk[25], farm_warehouse=store, unit="",
            rcv_qty=Decimal("10"), rate=Decimal("500"), discount_percent=Decimal("0"),
            discount_amount=Decimal("0"), gst_percent=Decimal("0"))
        res = self.page(below_cost="1")
        self.assertEqual(res["recordsFiltered"], 1)
        self.assertEqual([r["item"] for r in res["data"]], [self.bulk[25].id])

    def test_all_rows_at_once_for_an_export(self):
        res = self.page(length="-1")
        self.assertEqual(len(res["data"]), 33)

    def test_lists_every_matching_id_for_select_all(self):
        ids = self.client.get(reverse("item_price_list_overview_data"),
                              {"ids": "1", "status": "active"}).json()["ids"]
        self.assertEqual(sorted(ids), sorted(item.id for item in self.bulk))

    def test_the_add_prices_dropdown_lists_active_items(self):
        self.tonic.is_active = False
        self.tonic.save(update_fields=["is_active"])
        options = self.client.get(reverse("item_price_list_items_data")).json()["items"]
        ids = [o["id"] for o in options]
        self.assertIn(self.starter.id, ids)
        self.assertNotIn(self.tonic.id, ids)

    def test_the_whole_list_is_still_available_without_paging(self):
        rows = self.client.get(reverse("item_price_list_overview_data")).json()["rows"]
        self.assertEqual(len(rows), 33)

    def test_the_new_endpoint_needs_view_rights(self):
        from user.access import derive_tab, resolve_action
        name = "item_price_list_items_data"
        self.assertEqual(resolve_action(name) or derive_tab(name), ("item_price_list", "view"))
