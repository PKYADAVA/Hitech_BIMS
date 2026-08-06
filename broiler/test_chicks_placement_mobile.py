"""The Chicks Placement tab on the phone, answering as the web page does.

A placement is a Stock Transfer: chicks leave a warehouse and land on a flock.
The dedicated form exists because a transfer grid cannot ask how many were
ordered against how many walked off the lorry, and those four shortfall
columns are the reason a placement is recorded separately at all.

The phone had the *report* and not the transaction, so these cover the pieces
that had to be built for it — and, more usefully, that they answer the same as
the web form's own lookups rather than a second copy of them.
"""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from broiler.models import Branch, BroilerBatch, BroilerFarm, Farmer, Region, Supervisor
from inventory.models import Item, ItemCategory, Warehouse
from purchase.models import Supplier


class ChicksPlacementMobileTests(TestCase):
    def setUp(self):
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region, prefix="AKB")
        supervisor = Supervisor.objects.create(branch=branch, name="R. Verma")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=supervisor, farmer=farmer, region=region,
            line="L1", farm_name="Green Valley Farm", farm_capacity=9000)
        self.warehouse = Warehouse.objects.create(name="Akbarpur Store")
        self.supplier = Supplier.objects.create(name="Sunrise Hatcheries")

        chicks = ItemCategory.objects.create(name="Chicks")
        feed = ItemCategory.objects.create(name="Feed")
        self.chick_item = Item.objects.create(
            item_code="CHK-001", description="Day Old Chick", category=chicks,
            standard_cost_per_unit=0)
        self.feed_item = Item.objects.create(
            item_code="FD-001", description="Starter Crumble", category=feed,
            standard_cost_per_unit=0)

        User = get_user_model()
        self.user = User.objects.create_superuser("cp_user", "cp@x.com", "Str0ngPass!")
        self.client.force_login(self.user)

    # ---- the two pickers the phone had no endpoint for ---------------------

    def test_the_source_picker_offers_hatcheries_and_suppliers_together(self):
        """Two masters behind one control, exactly as the web form renders it."""
        resp = self.client.get("/api/v1/broiler/chicks-sources")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()["data"]

        names = [r["name"] for r in rows]
        self.assertIn("Sunrise Hatcheries", names)
        # The prefix is what lets one picker round-trip either kind; without it
        # the save cannot tell which column an id belongs in.
        for row in rows:
            self.assertRegex(str(row["id"]), r"^[hs]:\d+$")
            self.assertIn(row["group"], {"Hatcheries", "Suppliers"})

    def test_the_source_picker_matches_the_web_form_s_own_list(self):
        from broiler.views import _chicks_sources

        web = _chicks_sources(self.user)
        phone = self.client.get("/api/v1/broiler/chicks-sources").json()["data"]
        self.assertEqual([s["value"] for s in web], [p["id"] for p in phone])

    def test_the_item_picker_offers_chicks_and_not_feed(self):
        """A placement moves chicks. The full item list would offer feed and
        medicine as things to place on a farm."""
        rows = self.client.get("/api/v1/broiler/chick-items").json()["data"]
        codes = [r["item_code"] for r in rows]
        self.assertIn("CHK-001", codes)
        self.assertNotIn("FD-001", codes)

    def test_farm_batches_answers_the_same_as_the_web_lookup(self):
        open_batch = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="BR2607", start_date=date(2026, 7, 1))
        BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="BR2606", start_date=date(2026, 5, 1),
            end_date=date(2026, 6, 20))

        phone = self.client.get("/api/v1/inventory/farm-batches",
                                {"farm": self.farm.id}).json()["data"]
        web = self.client.get(reverse("stock_transfer_farm_batches"),
                              {"farm": self.farm.id}).json()
        self.assertEqual(phone, web)

        # Closed batches are offered too — a correction filed later belongs to
        # the batch it was about — with the current one flagged.
        self.assertEqual(len(phone), 2)
        active = [b for b in phone if b["is_active"]]
        self.assertEqual([b["id"] for b in active], [open_batch.id])

    def test_a_farm_with_no_batches_answers_empty_rather_than_erroring(self):
        resp = self.client.get("/api/v1/inventory/farm-batches", {"farm": self.farm.id})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"], [])

    # ---- the register the form's Register button reaches --------------------

    def test_the_register_is_transfers_landing_on_a_farm(self):
        """The phone's list is the web page's own narrowing of stock transfers,
        not a second table saying the same thing."""
        resp = self.client.get("/api/v1/inventory/stock-transfers/",
                               {"to_location_type": "farm"})
        self.assertEqual(resp.status_code, 200)

        # And the filter is real: a transfer between warehouses stays out.
        from inventory.models import StockTransfer

        other = Warehouse.objects.create(name="Depot")
        StockTransfer.objects.create(
            date=date(2026, 8, 1), item=self.chick_item, quantity=100,
            from_location_type="warehouse", from_warehouse=self.warehouse,
            to_location_type="warehouse", to_warehouse=other)
        placed = StockTransfer.objects.create(
            date=date(2026, 8, 2), item=self.chick_item, quantity=1000,
            from_location_type="warehouse", from_warehouse=self.warehouse,
            to_location_type="farm", to_farm=self.farm)

        rows = self.client.get("/api/v1/inventory/stock-transfers/",
                               {"to_location_type": "farm"}).json()["data"]
        self.assertEqual([r["id"] for r in rows], [placed.id])
