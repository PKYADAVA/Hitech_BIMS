"""A batch cannot be closed until every item balances to zero.

Closing a batch settles it, and settling it with feed or medicine still on hand
leaves that stock belonging to nothing: the flock is finished, the next one has
not been placed, and the stock is neither eaten, nor back in the warehouse, nor
on another farm's books. So the settlement is refused until every item has been
consumed, returned or transferred out.

Per item, because a batch total can come to nothing while one feed is over and
another short, and what was asked for is "any item balance left".
"""
import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from broiler.models import (Branch, BroilerBatch, BroilerFarm, DailyEntry,
                            Farmer, GrowingChargeSettlement,
                            MedicineVaccineEntry, Region, Supervisor)
from broiler.views import _pending_item_balances
from inventory.models import (Item, ItemCategory, MedicineTransfer,
                              MedicineTransferItem, StockTransfer, Warehouse)

CREATE = "/create-gc-settlement/"


class CloseWithStockTests(TestCase):

    def setUp(self):
        self.placed = timezone.localdate() - timedelta(days=45)
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region,
                                       prefix="AKB")
        self.supervisor = Supervisor.objects.create(branch=branch, name="A. Pal")
        farmer = Farmer.objects.create(farmer_name="Vishvanath")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=self.supervisor, farmer=farmer,
            region=region, line="Baskhari", farm_name="Vishvanath Farm",
            farm_capacity=5000)
        self.neighbour = BroilerFarm.objects.create(
            branch=branch, supervisor=self.supervisor, farmer=farmer,
            region=region, line="Baskhari", farm_name="Pappu Yadav Farm",
            farm_capacity=5000)
        self.batch = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="AKB-1102-1",
            book_number="BK-AKB", start_date=self.placed)
        self.store = Warehouse.objects.create(name="Akbarpur Warehouse")

        feed_cat = ItemCategory.objects.create(name="Feed")
        med_cat = ItemCategory.objects.create(name="Medicine")
        item = dict(valuation_method="Weighted Average", usage="Produced",
                    source="Purchased", type="Raw Material", item_account="Expense")
        self.starter = Item.objects.create(description="Starter Feed",
                                           category=feed_cat, standard_cost_per_unit=42, **item)
        self.finisher = Item.objects.create(description="Finisher Feed",
                                            category=feed_cat, standard_cost_per_unit=42, **item)
        self.vaccine = Item.objects.create(description="Gumboro Vaccine",
                                           category=med_cat, standard_cost_per_unit=5, **item)

        self.user = get_user_model().objects.create_superuser(
            "closer", "c@x.com", "Str0ngPass!")
        self.client.force_login(self.user)

    # --- movements -------------------------------------------------------

    def day(self, n):
        return self.placed + timedelta(days=n)

    def feed_in(self, item, qty):
        StockTransfer.objects.create(
            date=self.day(1), item=item, quantity=Decimal(qty), rate=42,
            from_location_type="warehouse", from_warehouse=self.store,
            to_location_type="farm", to_farm=self.farm, to_batch=self.batch)

    def eat(self, item, qty, n=30):
        DailyEntry.objects.create(
            farm=self.farm, batch=self.batch, supervisor=self.supervisor,
            date=self.day(n), feed_1=item, feed_1_qty=Decimal(qty))

    def feed_back(self, item, qty):
        StockTransfer.objects.create(
            date=self.day(40), item=item, quantity=Decimal(qty), rate=42,
            from_location_type="farm", from_farm=self.farm, from_batch=self.batch,
            to_location_type="warehouse", to_warehouse=self.store)

    def feed_on(self, item, qty):
        StockTransfer.objects.create(
            date=self.day(41), item=item, quantity=Decimal(qty), rate=42,
            from_location_type="farm", from_farm=self.farm, from_batch=self.batch,
            to_location_type="farm", to_farm=self.neighbour)

    def med_in(self, qty):
        mt = MedicineTransfer.objects.create(
            date=self.day(2), from_location_type="warehouse", from_warehouse=self.store,
            to_location_type="farm", to_farm=self.farm, to_batch=self.batch)
        MedicineTransferItem.objects.create(transfer=mt, item=self.vaccine,
                                            quantity=Decimal(qty), rate=5)

    def med_use(self, qty):
        MedicineVaccineEntry.objects.create(
            date=self.day(10), supervisor=self.supervisor, farm=self.farm,
            batch=self.batch, item=self.vaccine, qty=Decimal(qty))

    def med_back(self, qty):
        mt = MedicineTransfer.objects.create(
            date=self.day(42), from_location_type="farm", from_farm=self.farm,
            from_batch=self.batch, to_location_type="warehouse", to_warehouse=self.store)
        MedicineTransferItem.objects.create(transfer=mt, item=self.vaccine,
                                            quantity=Decimal(qty), rate=5)

    def close(self):
        return self.client.post(CREATE, json.dumps({
            "batch": self.batch.id, "gc_date": timezone.localdate().isoformat(),
        }), content_type="application/json")

    def assertRefused(self, response, *mentions):
        self.assertEqual(response.status_code, 400, response.content[:300])
        error = response.json()["error"]
        for text in mentions:
            self.assertIn(text, error)
        self.batch.refresh_from_db()
        self.assertFalse(self.batch.is_closed)
        self.assertFalse(GrowingChargeSettlement.objects.filter(batch=self.batch).exists())

    def assertClosed(self, response):
        self.assertEqual(response.status_code, 201, response.content[:300])
        self.batch.refresh_from_db()
        self.assertTrue(self.batch.is_closed)

    # --- feed -------------------------------------------------------------

    def test_feed_left_on_the_farm_stops_the_close(self):
        self.feed_in(self.finisher, 1000)
        self.eat(self.finisher, 600)
        self.assertRefused(self.close(), "Finisher Feed", "400.00")

    def test_feed_all_accounted_for_lets_it_close(self):
        """Eaten, returned and passed on — every route out counts."""
        self.feed_in(self.finisher, 1000)
        self.eat(self.finisher, 600)
        self.feed_back(self.finisher, 250)
        self.feed_on(self.finisher, 150)
        self.assertClosed(self.close())

    def test_each_feed_is_checked_on_its_own(self):
        """A total that comes to nothing is not an empty farm. Starter 100 kg
        over and Finisher 100 kg short still leaves Starter on the shelf."""
        self.feed_in(self.starter, 100)
        self.eat(self.finisher, 100)
        self.assertRefused(self.close(), "Starter Feed")

    # --- medicine ---------------------------------------------------------

    def test_medicine_left_on_the_farm_stops_the_close(self):
        self.med_in(50)
        self.med_use(30)
        self.assertRefused(self.close(), "Gumboro Vaccine", "20.00")

    def test_medicine_all_accounted_for_lets_it_close(self):
        self.med_in(50)
        self.med_use(30)
        self.med_back(20)
        self.assertClosed(self.close())

    # --- the message and the edges ----------------------------------------

    def test_the_refusal_names_every_item_left(self):
        self.feed_in(self.finisher, 1000)
        self.med_in(50)
        response = self.close()
        self.assertRefused(response, "Finisher Feed", "Gumboro Vaccine")
        kinds = sorted(p["kind"] for p in response.json()["pending"])
        self.assertEqual(kinds, ["Feed", "Medicine"])

    def test_a_batch_with_nothing_on_it_closes(self):
        self.assertClosed(self.close())

    def test_more_used_than_received_also_stops_the_close(self):
        """A negative balance means the records do not add up, and a batch is
        not settled on figures that do not add up."""
        self.feed_in(self.finisher, 100)
        self.eat(self.finisher, 150)
        self.assertRefused(self.close(), "Finisher Feed", "-50.00", "Correct the entries")

    def test_negative_medicine_also_stops_the_close(self):
        self.med_in(10)
        self.med_use(15)
        self.assertRefused(self.close(), "Gumboro Vaccine", "-5.00")

    def test_the_helper_reports_a_negative_balance(self):
        self.assertEqual(_pending_item_balances(
            {"feed_summary": [{"item": "Finisher Feed", "balance": Decimal("-50")}]}),
            [{"kind": "Feed", "item": "Finisher Feed", "balance": Decimal("-50.00")}])

    def test_the_per_item_case_names_the_short_item_too(self):
        """Starter over and Finisher short: both need fixing, so both are named."""
        self.feed_in(self.starter, 100)
        self.eat(self.finisher, 100)
        self.assertRefused(self.close(), "Starter Feed", "Finisher Feed")
