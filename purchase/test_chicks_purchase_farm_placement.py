"""Chicks Purchase straight onto a farm creates, and keeps, its Chicks Placement.

Every placed-birds figure reads a chick-category stock transfer into the batch,
so a farm line is booked in through a warehouse and placed from it by a
transfer the purchase owns: created on save, updated on edit (keeping its
number), removed with the line or the purchase, and refused if changed from
the Chicks Placement side.
"""
import json
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from broiler.models import Branch, BroilerBatch, BroilerFarm, Farmer, Region, Supervisor
from inventory.models import Item, ItemCategory, ItemPriceList, StockTransfer, Warehouse
from purchase.models import ChicksPurchase, ChicksPurchaseItem, Supplier


class ChicksPurchaseFarmPlacementTests(TestCase):

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser(
            "cpfarm", "c@x.com", "Str0ngPass!"))
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region, prefix="AKB")
        supervisor = Supervisor.objects.create(branch=branch, name="R. Verma")
        self.day = date(2026, 8, 22)
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=supervisor, farmer=Farmer.objects.create(farmer_name="S. Yadav"),
            region="East", line="L1", farm_name="Green Valley Farm", farm_capacity=9000)
        self.batch = BroilerBatch.objects.create(broiler_farm=self.farm, start_date=self.day)
        self.store = Warehouse.objects.create(name="Akbarpur Warehouse")
        self.chicks = Item.objects.create(item_code="DOC-0001", description="Day Old Chicks",
                                          category=ItemCategory.objects.create(name="Day Old Chicks"),
                                          standard_cost_per_unit=0)
        ItemPriceList.objects.create(item=self.chicks, price=Decimal("38"),
                                     effective_date=self.day - timedelta(days=30))
        self.supplier = Supplier.objects.create(name="Venky's Hatchery")

    def farm_line(self, sent="5000", batch=True, via=True):
        return {"sent_qty": sent, "rate": "36", "farm": self.farm.id,
                "farm_warehouse": self.store.id if via else "",
                "farm_batch": self.batch.id if batch else ""}

    def warehouse_line(self, sent="5000"):
        return {"sent_qty": sent, "rate": "36", "farm_warehouse": self.store.id}

    def save(self, *lines, purchase=None):
        url = "/chicks-purchase/%d/edit/" % purchase.id if purchase else "/chicks-purchase/add/"
        return self.client.post(url, {
            "date": self.day.isoformat(), "supplier": self.supplier.id, "item": self.chicks.id,
            "bill_no": "VH-101", "items_json": json.dumps(list(lines))}, follow=True)

    def placement(self):
        return StockTransfer.objects.get(to_farm=self.farm)

    def test_a_farm_line_creates_its_placement(self):
        self.save(self.farm_line())
        st = self.placement()
        line = ChicksPurchaseItem.objects.get()
        self.assertEqual(line.placement_id, st.id)
        self.assertEqual((st.from_warehouse_id, st.to_batch_id, st.item_id, st.date),
                         (self.store.id, self.batch.id, self.chicks.id, self.day))
        self.assertEqual(st.quantity, line.total_qty)
        self.assertEqual(st.source_supplier_id, self.supplier.id)
        self.assertEqual(st.chicks_ordered, Decimal("5000"))

    def test_the_warehouse_nets_to_nothing_and_the_farm_holds_the_chicks(self):
        from inventory.models import warehouse_item_stock
        self.save(self.farm_line())
        self.assertEqual(warehouse_item_stock(self.chicks.id, self.store.id, as_of_date=self.day), 0)

    def test_an_edit_updates_the_same_placement(self):
        self.save(self.farm_line())
        purchase, before = ChicksPurchase.objects.get(), self.placement()
        self.save(self.farm_line(sent="4000"), purchase=purchase)
        after = self.placement()
        self.assertEqual((after.id, after.trnum), (before.id, before.trnum))
        self.assertEqual(after.quantity, Decimal("4000"))

    def test_a_line_moved_back_to_the_warehouse_drops_its_placement(self):
        self.save(self.farm_line())
        self.save(self.warehouse_line(), purchase=ChicksPurchase.objects.get())
        self.assertFalse(StockTransfer.objects.exists())

    def test_deleting_the_purchase_deletes_its_placement(self):
        self.save(self.farm_line())
        self.client.post("/chicks-purchase/%d/delete/" % ChicksPurchase.objects.get().id)
        self.assertFalse(ChicksPurchase.objects.exists())
        self.assertFalse(StockTransfer.objects.exists())

    def test_a_farm_line_without_its_flock_is_refused_and_nothing_saved(self):
        response = self.save(self.farm_line(batch=False))
        self.assertContains(response, "select the flock / batch")
        self.assertFalse(ChicksPurchase.objects.exists())
        self.assertFalse(StockTransfer.objects.exists())

    def test_a_farm_line_without_its_warehouse_is_refused(self):
        response = self.save(self.farm_line(via=False))
        self.assertFalse(ChicksPurchase.objects.exists())

    def test_the_placement_cannot_be_changed_from_chicks_placement(self):
        self.save(self.farm_line())
        st = self.placement()
        response = self.client.delete("/stock_transfer_api/%d/" % st.id)
        self.assertEqual(response.status_code, 400)
        self.assertIn("made by Chicks Purchase", response.json()["error"])
        response = self.client.put("/stock_transfer_api/%d/" % st.id, json.dumps({
            "date": self.day.isoformat(), "item": self.chicks.id, "quantity": "10", "rate": "38",
            "from_location_type": "warehouse", "from_location_id": self.store.id,
            "to_location_type": "farm", "to_location_id": self.farm.id, "to_batch": self.batch.id}),
            content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(StockTransfer.objects.filter(id=st.id).exists())

    def test_the_list_names_the_farm(self):
        self.save(self.farm_line())
        rows = self.client.get("/chicks_purchase_api/", {"from_date": self.day.isoformat(),
                                                         "to_date": self.day.isoformat()}).json()
        self.assertEqual(rows[0]["farm_warehouse_names"], "Green Valley Farm")

    def test_the_form_offers_farms(self):
        html = self.client.get("/chicks-purchase/add/").content.decode()
        self.assertIn('<optgroup label="Farms">', html)
        self.assertIn('value="f:%d">Green Valley Farm' % self.farm.id, html)
        self.assertIn('Flock / Batch <span class="text-danger">*</span>', html)

    def test_the_lot_label_is_no_longer_asked_for(self):
        html = self.client.get("/chicks-purchase/add/").content.decode()
        self.assertNotIn('class="form-control batch"', html)
        self.assertIn("tr.dataset.lot", html)   # a saved lot is carried back on edit
