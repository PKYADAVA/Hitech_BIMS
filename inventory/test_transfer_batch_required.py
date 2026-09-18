"""A transfer touching a farm must name the batch it moved against.

Stock onto a farm is for one flock, and stock off it comes out of one. Left
blank, the feed, medicine or chicks land on the farm with no batch to charge
them to, and every per-flock figure built on them — consumption, cost, the
settlement — is short by that amount. Both Stock Transfer and Medicine
Transfer now refuse a farm location without its batch, the same way they
already refused one without the farm itself.
"""
import json
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from broiler.models import Branch, BroilerBatch, BroilerFarm, Farmer, Region, Supervisor
from inventory.models import (Item, ItemCategory, ItemPriceList, MedicineTransfer,
                              StockTransfer, Warehouse)


class TransferBatchBase(TestCase):

    def setUp(self):
        self.today = date(2026, 7, 23)
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region, prefix="AKB")
        supervisor = Supervisor.objects.create(branch=branch, name="R. Verma")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=supervisor, farmer=farmer, region="East",
            line="L1", farm_name="Green Valley Farm", farm_capacity=9000)
        self.batch = BroilerBatch.objects.create(broiler_farm=self.farm,
                                                 start_date=self.today - timedelta(days=10))
        self.warehouse = Warehouse.objects.create(name="Akbarpur Store")
        self.other_warehouse = Warehouse.objects.create(name="Basti Store")
        feed = ItemCategory.objects.create(name="Broiler Feed")
        self.item = Item.objects.create(item_code="ITM-0001", description="Pre-Starter Feed",
                                        category=feed, standard_cost_per_unit=0)
        ItemPriceList.objects.create(item=self.item, price=Decimal("30"),
                                     effective_date=self.today - timedelta(days=30))

    def stock(self, **kw):
        base = dict(date=self.today, item=self.item, quantity=Decimal("10"),
                    from_location_type="warehouse", from_warehouse=self.warehouse)
        base.update(kw)
        return StockTransfer(**base)


class StockTransferModelTests(TransferBatchBase):

    def test_a_transfer_onto_a_farm_without_its_batch_is_refused(self):
        with self.assertRaises(ValidationError) as caught:
            self.stock(to_location_type="farm", to_farm=self.farm).full_clean(
                exclude=["trnum", "stock"])
        self.assertIn("to_batch", caught.exception.message_dict)
        self.assertIn("Green Valley Farm", str(caught.exception))

    def test_a_transfer_onto_a_farm_with_its_batch_passes_this_rule(self):
        transfer = self.stock(to_location_type="farm", to_farm=self.farm, to_batch=self.batch)
        try:
            transfer.full_clean(exclude=["trnum", "stock"])
        except ValidationError as error:
            self.assertNotIn("to_batch", getattr(error, "message_dict", {}))

    def test_a_transfer_between_warehouses_needs_no_batch(self):
        transfer = self.stock(to_location_type="warehouse", to_warehouse=self.other_warehouse)
        try:
            transfer.full_clean(exclude=["trnum", "stock"])
        except ValidationError as error:
            self.assertNotIn("to_batch", getattr(error, "message_dict", {}))
            self.assertNotIn("from_batch", getattr(error, "message_dict", {}))


class StockTransferApiTests(TransferBatchBase):

    def setUp(self):
        super().setUp()
        self.client.force_login(get_user_model().objects.create_superuser(
            "tradmin", "t@x.com", "Str0ngPass!"))

    def post(self, **row):
        body = {"rows": [dict({
            "date": self.today.isoformat(), "item": self.item.id, "quantity": "10", "rate": "30",
            "from_location_type": "warehouse", "from_location_id": self.warehouse.id,
            "to_location_type": "farm", "to_location_id": self.farm.id}, **row)]}
        return self.client.post(reverse("stock_transfer_api_list"), json.dumps(body),
                                content_type="application/json")

    def test_the_api_refuses_a_farm_row_without_its_batch_and_says_why(self):
        response = self.post()
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("Select the batch at Green Valley Farm", response.json()["error"])
        self.assertFalse(StockTransfer.objects.exists())


class MedicineTransferModelTests(TransferBatchBase):

    def test_a_medicine_transfer_onto_a_farm_without_its_batch_is_refused(self):
        transfer = MedicineTransfer(date=self.today,
                                    from_location_type="warehouse", from_warehouse=self.warehouse,
                                    to_location_type="farm", to_farm=self.farm)
        with self.assertRaises(ValidationError) as caught:
            transfer.clean()
        self.assertIn("to_batch", caught.exception.message_dict)

    def test_a_medicine_transfer_off_a_farm_without_its_batch_is_refused(self):
        transfer = MedicineTransfer(date=self.today,
                                    from_location_type="farm", from_farm=self.farm,
                                    to_location_type="warehouse", to_warehouse=self.warehouse)
        with self.assertRaises(ValidationError) as caught:
            transfer.clean()
        self.assertIn("from_batch", caught.exception.message_dict)

    def test_with_its_batch_it_is_accepted(self):
        MedicineTransfer(date=self.today,
                         from_location_type="warehouse", from_warehouse=self.warehouse,
                         to_location_type="farm", to_farm=self.farm, to_batch=self.batch).clean()


class FormTests(TransferBatchBase):

    def setUp(self):
        super().setUp()
        self.client.force_login(get_user_model().objects.create_superuser(
            "fmadmin", "f@x.com", "Str0ngPass!"))

    def test_the_stock_transfer_form_marks_batch_as_required(self):
        html = self.client.get(reverse("stock_transfer_add")).content.decode()
        self.assertIn('col-from-batch d-none">Batch <span class="text-danger">*</span>', html)
        self.assertIn('col-to-batch d-none">Batch <span class="text-danger">*</span>', html)
        self.assertIn("Select the Batch for every farm location", html)

    def test_the_medicine_transfer_form_marks_batch_as_required(self):
        html = self.client.get(reverse("medicine_transfer_add")).content.decode()
        self.assertEqual(html.count('Batch <span class="text-danger">*</span>'), 2)
        self.assertIn("Select the Batch for the farm location", html)
