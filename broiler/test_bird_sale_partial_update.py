"""Patching one thing on a bird sale must not decide the others again.

The phone stamps a lifting's location from the photographs screen, which is
the only chance a desk-raised sale ever gets to reach the map. That write
names nothing but a pair of coordinates, and the serializer met it twice:

* it refused the write outright — "Customer is required for a Customer Sale"
  — because it looked for the buyer in the payload rather than on the record
  the payload is amending;

* and, had it not refused, it would have re-derived the batch. ``farm`` falls
  back to the stored sale, so ``_resolve_batch`` would hand back the farm's
  *currently* open flock: stamping an August lifting in October would quietly
  re-file it against whatever is on the farm now, taking the birds off the
  wrong flock with nobody having asked.

So a partial update that names neither the farm nor the kind of sale leaves
the batch and the buyer exactly as they are, and a write that does name one
still derives them — which is the rule the derivation was put there for.
"""
from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from broiler.models import (BirdSale, Branch, BroilerBatch, BroilerFarm,
                            Farmer, Region, Supervisor)
from sales.models import Customer

PATH = "/api/v1/broiler/bird-sales/"


class BirdSalePartialUpdateTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region, prefix="AKB")
        supervisor = Supervisor.objects.create(branch=branch, name="R. Verma")
        self.farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=supervisor, farmer=self.farmer, region=region,
            line="L1", farm_name="Green Valley Farm", farm_capacity=9000)
        self.customer = Customer.objects.create(name="Metro Poultry")

        # The flock the sale was actually filed against, and the one that
        # replaced it on the farm afterwards.
        self.sold_from = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="AUGUST", start_date=self.today)
        self.sale = BirdSale.objects.create(
            date=self.today, sale_type="customer", customer=self.customer,
            farm=self.farm, batch=self.sold_from, birds=1250,
            net_weight=Decimal("2625.00"), rate=Decimal("102.00"))

        User = get_user_model()
        self.user = User.objects.create_superuser("bsp", "bsp@x.com", "Str0ngPass!")
        self.client.force_login(self.user)

    def patch(self, body):
        return self.client.patch(f"{PATH}{self.sale.id}/", body,
                                 content_type="application/json")

    # ---- the write the phone makes -----------------------------------------

    def test_a_lifting_can_be_put_on_the_map_on_its_own(self):
        response = self.patch({"lift_latitude": "26.85", "lift_longitude": "80.95",
                               "lift_place": "Green Valley Farm, Sitapur"})
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.sale.refresh_from_db()
        self.assertEqual(float(self.sale.lift_latitude), 26.85)
        self.assertEqual(float(self.sale.lift_longitude), 80.95)
        self.assertEqual(self.sale.lift_place, "Green Valley Farm, Sitapur")

    def test_stamping_the_map_leaves_the_flock_alone(self):
        """The costly one. A newer flock on the farm must not capture an older
        sale just because somebody stamped its location."""
        BroilerBatch.objects.create(broiler_farm=self.farm, batch_name="OCTOBER",
                                    start_date=self.today)
        self.patch({"lift_latitude": "26.85", "lift_longitude": "80.95"})
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.batch, self.sold_from)

    def test_stamping_the_map_leaves_the_buyer_alone(self):
        self.patch({"lift_latitude": "26.85", "lift_longitude": "80.95"})
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.customer, self.customer)
        self.assertIsNone(self.sale.farmer)

    def test_any_other_single_field_patches_too(self):
        """Nothing about this is particular to coordinates — the whole partial
        update path was unusable."""
        response = self.patch({"vehicle": "UP53KY7896"})
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.vehicle, "UP53KY7896")

    # ---- what the derivation is still there for ----------------------------

    def test_naming_a_farm_still_re_derives_the_flock(self):
        """A write that moves the sale to another farm cannot keep a batch
        belonging to the old one."""
        other = BroilerFarm.objects.create(
            branch=self.farm.branch, supervisor=self.farm.supervisor,
            farmer=self.farmer, region=self.farm.region, line="L1",
            farm_name="Other Farm", farm_capacity=5000)
        theirs = BroilerBatch.objects.create(broiler_farm=other, batch_name="THEIRS",
                                             start_date=self.today)
        response = self.patch({"farm": other.id})
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.farm, other)
        self.assertEqual(self.sale.batch, theirs)

    def test_turning_it_into_a_farmer_sale_still_derives_the_farmer(self):
        response = self.patch({"sale_type": "farmer"})
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.farmer, self.farmer)
        self.assertIsNone(self.sale.customer)

    def test_a_new_sale_still_has_to_name_its_customer(self):
        """The check that started all this keeps working where it belongs."""
        response = self.client.post(PATH, {
            "date": self.today.isoformat(), "sale_type": "customer",
            "farm": self.farm.id, "birds": 10, "net_weight": "20.00", "rate": "90",
        }, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Customer is required", response.content)
