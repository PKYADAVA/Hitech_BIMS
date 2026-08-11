"""The Item Ledger reads a farm as well as a warehouse.

The location select was labelled "Farm/Sector" and listed only stores, so a
farm — which holds feed and medicine for weeks — could only ever be seen as
the far side of somebody else's transfer. There was no way to ask what a farm
had received, eaten and been left with.

A farm has two outflows a store never has: feed eaten, which exists only as a
Daily Entry, and medicine given, which exists only as a Medicine & Vaccine
Entry. Leaving either out would show a farm receiving tonnes and using none,
so the ledger's closing balance is checked against ``location_item_stock`` —
the figure the rest of the ERP treats as farm stock.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from broiler.models import (Branch, BroilerBatch, BroilerFarm, DailyEntry,
                            Farmer, Region, Supervisor)
from inventory.models import Item, ItemCategory, StockTransfer, Warehouse
from inventory.services.item_summary import location_item_stock
from inventory.services.valuation import item_ledger


class FarmLedgerTests(TestCase):
    def setUp(self):
        self.today = date(2026, 7, 23)
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region, prefix="AKB")
        self.sup = Supervisor.objects.create(branch=branch, name="R. Verma")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=self.sup, farmer=farmer, region=region,
            line="L1", farm_name="Yadav Farm", farm_capacity=9000)
        self.other = BroilerFarm.objects.create(
            branch=branch, supervisor=self.sup, farmer=farmer, region=region,
            line="L1", farm_name="Second Farm", farm_capacity=5000)
        self.store = Warehouse.objects.create(name="Akbarpur Store")
        feed = ItemCategory.objects.create(name="Broiler Feed")
        self.item = Item.objects.create(item_code="ITM-1", description="Pre-Starter",
                                        category=feed, standard_cost_per_unit=0)
        self.batch = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="B-1",
            start_date=self.today - timedelta(days=10))

    def deliver(self, kg, rate="40", days_ago=5, to=None):
        return StockTransfer.objects.create(
            date=self.today - timedelta(days=days_ago), item=self.item, quantity=kg,
            rate=Decimal(rate), from_location_type="warehouse", from_warehouse=self.store,
            to_location_type="farm", to_farm=to or self.farm)

    def feed(self, kg, days_ago=2):
        return DailyEntry.objects.create(
            farm=self.farm, batch=self.batch, supervisor=self.sup,
            date=self.today - timedelta(days=days_ago),
            feed_1=self.item, feed_1_qty=Decimal(str(kg)))

    def ledger(self, farm=None):
        return item_ledger(self.item.id, (farm or self.farm).id, location_type="farm")

    def test_a_delivery_to_the_farm_is_an_inflow(self):
        self.deliver(Decimal("500"))
        led = self.ledger()
        self.assertEqual(led["closing"]["qty"], Decimal("500"))
        self.assertEqual([r["type"] for r in led["rows"]], ["Transfer-In"])

    def test_feed_eaten_is_an_outflow(self):
        """It is a Daily Entry, not a stock document — but the feed left."""
        self.deliver(Decimal("500"))
        self.feed(120)
        led = self.ledger()
        self.assertEqual(led["closing"]["qty"], Decimal("380"))
        self.assertIn("Feed Consumed", [r["type"] for r in led["rows"]])

    def test_both_feed_slots_of_one_entry_count(self):
        """A day feeding the same item through Primary and Optional took the
        sum out of the store, and counting one of them understates it."""
        self.deliver(Decimal("500"))
        DailyEntry.objects.create(
            farm=self.farm, batch=self.batch, supervisor=self.sup,
            date=self.today - timedelta(days=1),
            feed_1=self.item, feed_1_qty=Decimal("60"),
            feed_2=self.item, feed_2_qty=Decimal("40"))
        self.assertEqual(self.ledger()["closing"]["qty"], Decimal("400"))

    def test_the_closing_balance_agrees_with_the_rest_of_the_erp(self):
        """A second definition of farm stock is a second answer to the same
        question, and the two would drift."""
        self.deliver(Decimal("500"))
        self.feed(120)
        self.assertEqual(self.ledger()["closing"]["qty"],
                         location_item_stock("farm", self.farm.id, self.item.id))

    def test_a_transfer_off_the_farm_is_an_outflow(self):
        self.deliver(Decimal("500"))
        StockTransfer.objects.create(
            date=self.today - timedelta(days=1), item=self.item, quantity=Decimal("100"),
            rate=Decimal("40"), from_location_type="farm", from_farm=self.farm,
            to_location_type="farm", to_farm=self.other)
        self.assertEqual(self.ledger()["closing"]["qty"], Decimal("400"))
        self.assertEqual(self.ledger(self.other)["closing"]["qty"], Decimal("100"))

    def test_another_farm_s_movements_do_not_appear(self):
        self.deliver(Decimal("500"), to=self.other)
        self.assertEqual(self.ledger()["rows"], [])

    def test_the_warehouse_side_still_reads_as_it_did(self):
        """The store's own ledger must not change shape because farms were
        added to the same function."""
        self.deliver(Decimal("500"))
        led = item_ledger(self.item.id, self.store.id, location_type="warehouse")
        self.assertEqual([r["type"] for r in led["rows"]], ["Transfer-Out"])
        self.assertEqual(led["closing"]["qty"], Decimal("-500"))

    def test_a_farm_ledger_never_reads_a_warehouse_only_document(self):
        """Egg purchases, chick sales and chick purchases are booked to a
        store and carry no farm at all — filtering a farm id against their
        warehouse column would have matched the wrong rows."""
        self.deliver(Decimal("500"))
        self.assertEqual([r["type"] for r in self.ledger()["rows"]], ["Transfer-In"])


class LedgerPageTests(TestCase):
    def setUp(self):
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region, prefix="AKB")
        sup = Supervisor.objects.create(branch=branch, name="R. Verma")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=sup, farmer=farmer, region=region,
            line="L1", farm_name="Yadav Farm", farm_capacity=9000)
        self.store = Warehouse.objects.create(name="Akbarpur Store")
        feed = ItemCategory.objects.create(name="Broiler Feed")
        self.item = Item.objects.create(item_code="ITM-1", description="Pre-Starter",
                                        category=feed, standard_cost_per_unit=0)
        User = get_user_model()
        self.user = User.objects.create_superuser("led", "l@x.com", "Str0ngPass!")
        self.client.force_login(self.user)

    def page(self, **params):
        return self.client.get(reverse("item_ledger_report"), params)

    def test_the_page_offers_farms_as_well_as_warehouses(self):
        """The select was labelled Farm/Sector and listed only stores."""
        res = self.page()
        self.assertIn(self.farm, list(res.context["farms"]))
        self.assertIn(self.store, list(res.context["warehouses"]))

    def test_a_farm_is_chosen_as_one_value_carrying_its_own_type(self):
        res = self.page(item=self.item.id, location=f"farm:{self.farm.id}")
        self.assertEqual(res.context["location_type"], "farm")
        self.assertEqual(res.context["location"], self.farm)

    def test_the_old_warehouse_link_still_works(self):
        """Every existing bookmark and Excel export on this page uses it."""
        res = self.page(item=self.item.id, warehouse=self.store.id)
        self.assertEqual(res.context["location_type"], "warehouse")
        self.assertEqual(res.context["location"], self.store)

    def test_a_location_type_nobody_offers_falls_back_to_warehouse(self):
        """It picks which columns are queried, so it cannot be taken on trust."""
        res = self.page(item=self.item.id, location=f"lorry:{self.farm.id}")
        self.assertEqual(res.context["location_type"], "warehouse")

    def test_a_farm_outside_the_user_s_scope_is_not_read(self):
        """A querystring is not a permission."""
        res = self.page(item=self.item.id, location="farm:999999")
        self.assertIsNone(res.context["location"])
        self.assertIsNone(res.context["ledger"])

    def test_the_heading_names_whichever_kind_was_chosen(self):
        res = self.page(item=self.item.id, location=f"farm:{self.farm.id}")
        self.assertEqual(res.context["location_name"], self.farm.farm_name)
