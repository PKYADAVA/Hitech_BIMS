"""General Purchase: a line delivered to a farm must name that farm's batch.

The same rule Stock Transfer and Medicine Transfer keep — stock onto a farm is
for one flock, and without its batch it is charged to nobody.
"""
import json
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from broiler.models import Branch, BroilerBatch, BroilerFarm, Farmer, Region, Supervisor
from inventory.models import Item, ItemCategory, Warehouse
from purchase.models import GeneralPurchase, GeneralPurchaseItem, Supplier
from purchase.views import _save_general_purchase


class GeneralPurchaseFarmBatchTests(TestCase):

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser(
            "gpbatch", "b@x.com", "Str0ngPass!"))
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region, prefix="AKB")
        supervisor = Supervisor.objects.create(branch=branch, name="R. Verma")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.day = date(2026, 8, 22)
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=supervisor, farmer=farmer, region="East", line="L1",
            farm_name="Green Valley Farm", farm_capacity=9000)
        self.other_farm = BroilerFarm.objects.create(
            branch=branch, supervisor=supervisor, farmer=farmer, region="East", line="L1",
            farm_name="Maa Durga Farm", farm_capacity=9000)
        self.batch = BroilerBatch.objects.create(broiler_farm=self.farm,
                                                 start_date=self.day - timedelta(days=10))
        self.other_batch = BroilerBatch.objects.create(broiler_farm=self.other_farm,
                                                       start_date=self.day - timedelta(days=10))
        self.store = Warehouse.objects.create(name="Akbarpur Warehouse")
        self.item = Item.objects.create(item_code="ITM-0001", description="Pre-Starter Feed",
                                        category=ItemCategory.objects.create(name="Feed"),
                                        standard_cost_per_unit=0)
        self.supplier = Supplier.objects.create(name="Shree Feeds")

    def line(self, destination, batch=""):
        return {"item": self.item.id, "unit": "Bag", "sent_qty": "10", "rcv_qty": "10",
                "rate": "2000", "destination": destination, "batch": batch}

    def post(self, *lines):
        return self.client.post("/general-purchase/add/", {
            "date": self.day.isoformat(), "supplier": self.supplier.id,
            "items_json": json.dumps(list(lines))}, follow=True)

    def test_a_farm_line_without_its_batch_is_refused_and_nothing_saved(self):
        response = self.post(self.line("warehouse:%d" % self.store.id),
                             self.line("farm:%d" % self.farm.id))
        self.assertContains(response, "Select the batch for every farm line: row 2 (Green Valley Farm).")
        self.assertFalse(GeneralPurchase.objects.exists())

    def test_a_farm_line_with_its_batch_saves(self):
        self.post(self.line("farm:%d" % self.farm.id, self.batch.id))
        line = GeneralPurchaseItem.objects.get()
        self.assertEqual((line.farm_id, line.batch_id), (self.farm.id, self.batch.id))

    def test_another_farms_batch_does_not_count(self):
        self.post(self.line("farm:%d" % self.farm.id, self.other_batch.id))
        self.assertFalse(GeneralPurchase.objects.exists())

    def test_warehouse_lines_need_no_batch(self):
        self.post(self.line("warehouse:%d" % self.store.id))
        self.assertEqual(GeneralPurchaseItem.objects.get().farm_warehouse_id, self.store.id)

    def test_an_approved_change_without_the_batch_leaves_the_bill_untouched(self):
        self.post(self.line("warehouse:%d" % self.store.id))
        purchase = GeneralPurchase.objects.get()
        with self.assertRaises(ValidationError):
            _save_general_purchase({"date": self.day.isoformat(), "supplier": self.supplier.id,
                                    "bill_no": "CHANGED",
                                    "items": [self.line("farm:%d" % self.farm.id)]}, purchase.id)
        purchase.refresh_from_db()
        self.assertEqual(purchase.bill_no, "")
        self.assertEqual(GeneralPurchaseItem.objects.get().farm_warehouse_id, self.store.id)

    def test_the_form_marks_the_batch_required(self):
        html = self.client.get("/general-purchase/add/").content.decode()
        self.assertIn('col-batch d-none">Flock / Batch <span class="text-danger">*</span>', html)
        self.assertIn("Select the Flock / Batch for every farm row", html)
