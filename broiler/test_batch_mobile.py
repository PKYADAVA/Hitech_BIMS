"""Batch Creation on the phone, delegating to the ERP's own batch API.

The phone must not carry a second copy of these rules: the batch number is
generated on save and never accepted from a form, a shed holding an open batch
cannot take another, and an edit may change only the book number, lot number,
breed and shed. Each of those is asserted here through the mobile endpoint, so
the delegation is what is tested — not a restatement of it.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from .models import (Branch, Breed, BroilerBatch, BroilerFarm, BroilerFarmShed,
                     Farmer, Region, Supervisor)

SAVE = "/api/v1/broiler/batches/save"
SHEDS = "/api/v1/broiler/batch-sheds"


class BatchWriteTests(TestCase):
    def setUp(self):
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region,
                                       prefix="AKB")
        supervisor = Supervisor.objects.create(branch=branch, name="R. Verma")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=supervisor, farmer=farmer, region=region,
            line="L1", farm_name="Yadav Farm", farm_capacity=5000)
        self.other_farm = BroilerFarm.objects.create(
            branch=branch, supervisor=supervisor, farmer=farmer, region=region,
            line="L2", farm_name="Pal Farm", farm_capacity=3000)
        self.shed = BroilerFarmShed.objects.create(farm=self.farm,
                                                   shed_name="Shed A")
        self.shed_b = BroilerFarmShed.objects.create(farm=self.farm,
                                                     shed_name="Shed B")
        self.far_shed = BroilerFarmShed.objects.create(farm=self.other_farm,
                                                       shed_name="Shed Z")
        self.breed = Breed.objects.create(code="COBB", description="Cobb 500")

        self.user = get_user_model().objects.create_superuser("u", password="x")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    # --- creating -------------------------------------------------------

    def test_create_generates_the_batch_number(self):
        resp = self.client.post(SAVE, {
            "broiler_farm_id": self.farm.id, "shed": self.shed.id,
            "book_number": "BK-1", "lot_no": "LOT-1", "breed": self.breed.id,
        }, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        batch = BroilerBatch.objects.get()
        self.assertEqual(batch.batch_name,
                         f"{self.farm.farm_code.removeprefix('FRM/')}-1")
        self.assertEqual(batch.shed_id, self.shed.id)
        self.assertEqual(batch.book_number, "BK-1")
        self.assertEqual(batch.breed_id, self.breed.id)

    def test_a_posted_batch_number_is_ignored(self):
        # The form shows it read-only; this is the rule underneath, so a
        # hand-rolled request cannot mint its own numbering.
        self.client.post(SAVE, {"broiler_farm_id": self.farm.id,
                                "batch_name": "MINE-999"}, format="json")
        self.assertEqual(BroilerBatch.objects.get().batch_name,
                         f"{self.farm.farm_code.removeprefix('FRM/')}-1")

    def test_numbers_run_on_per_farm(self):
        for _ in range(2):
            self.client.post(SAVE, {"broiler_farm_id": self.farm.id},
                             format="json")
        self.client.post(SAVE, {"broiler_farm_id": self.other_farm.id},
                         format="json")
        prefix = self.farm.farm_code.removeprefix("FRM/")
        self.assertEqual(
            sorted(BroilerBatch.objects.filter(broiler_farm=self.farm)
                   .values_list("batch_name", flat=True)),
            [f"{prefix}-1", f"{prefix}-2"])
        self.assertEqual(
            BroilerBatch.objects.get(broiler_farm=self.other_farm).batch_name,
            f"{self.other_farm.farm_code.removeprefix('FRM/')}-1")

    def test_an_occupied_shed_is_refused_by_name(self):
        self.client.post(SAVE, {"broiler_farm_id": self.farm.id,
                                "shed": self.shed.id}, format="json")
        resp = self.client.post(SAVE, {"broiler_farm_id": self.farm.id,
                                       "shed": self.shed.id}, format="json")
        self.assertEqual(resp.status_code, 400)
        # Naming the batch in the way is the whole point of the message.
        self.assertIn(BroilerBatch.objects.first().batch_name,
                      str(resp.content))
        self.assertEqual(BroilerBatch.objects.count(), 1)

    def test_a_batch_may_be_started_without_a_shed(self):
        resp = self.client.post(SAVE, {"broiler_farm_id": self.farm.id},
                                format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertIsNone(BroilerBatch.objects.get().shed_id)

    # --- editing --------------------------------------------------------

    def test_edit_changes_what_the_erp_allows_and_nothing_else(self):
        self.client.post(SAVE, {"broiler_farm_id": self.farm.id,
                                "shed": self.shed.id, "book_number": "BK-1"},
                         format="json")
        batch = BroilerBatch.objects.get()
        original_name = batch.batch_name

        resp = self.client.put(f"{SAVE}/{batch.id}", {
            "book_number": "BK-2", "lot_no": "LOT-9", "breed": self.breed.id,
            "shed": self.shed_b.id,
            # Ignored: the farm is fixed at creation and the number is minted.
            "broiler_farm_id": self.other_farm.id, "batch_name": "MINE-999",
        }, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)

        batch.refresh_from_db()
        self.assertEqual(batch.book_number, "BK-2")
        self.assertEqual(batch.lot_no, "LOT-9")
        self.assertEqual(batch.shed_id, self.shed_b.id)
        self.assertEqual(batch.batch_name, original_name)
        self.assertEqual(batch.broiler_farm_id, self.farm.id)

    def test_moving_onto_an_occupied_shed_is_refused(self):
        self.client.post(SAVE, {"broiler_farm_id": self.farm.id,
                                "shed": self.shed.id}, format="json")
        self.client.post(SAVE, {"broiler_farm_id": self.farm.id,
                                "shed": self.shed_b.id}, format="json")
        moving = BroilerBatch.objects.get(shed=self.shed_b)
        resp = self.client.put(f"{SAVE}/{moving.id}", {"shed": self.shed.id},
                               format="json")
        self.assertEqual(resp.status_code, 400)
        moving.refresh_from_db()
        self.assertEqual(moving.shed_id, self.shed_b.id)

    def test_a_batch_can_be_saved_onto_the_shed_it_already_holds(self):
        # Re-saving without moving must not read as a clash with itself.
        self.client.post(SAVE, {"broiler_farm_id": self.farm.id,
                                "shed": self.shed.id}, format="json")
        batch = BroilerBatch.objects.get()
        resp = self.client.put(f"{SAVE}/{batch.id}",
                               {"shed": self.shed.id, "book_number": "BK-7"},
                               format="json")
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_get_returns_the_form_shape(self):
        self.client.post(SAVE, {"broiler_farm_id": self.farm.id,
                                "shed": self.shed.id, "lot_no": "LOT-3"},
                         format="json")
        batch = BroilerBatch.objects.get()
        data = self.client.get(f"{SAVE}/{batch.id}").json()["data"]
        self.assertEqual(data["broiler_farm"], str(self.farm.id))
        self.assertEqual(data["broiler_farm_name"], "Yadav Farm")
        self.assertEqual(data["shed"], str(self.shed.id))
        self.assertEqual(data["lot_no"], "LOT-3")
        self.assertEqual(data["batch_name"], batch.batch_name)

    # --- the shed picker ------------------------------------------------

    def test_sheds_are_scoped_to_the_farm(self):
        rows = self.client.get(SHEDS, {"farm": self.farm.id}).json()["data"]
        self.assertEqual({r["id"] for r in rows},
                         {self.shed.id, self.shed_b.id})

    def test_no_farm_yet_asks_nothing_and_answers_nothing(self):
        # The form's opening state, not an error.
        resp = self.client.get(SHEDS)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"], [])

    def test_an_occupied_shed_says_which_batch_holds_it(self):
        self.client.post(SAVE, {"broiler_farm_id": self.farm.id,
                                "shed": self.shed.id}, format="json")
        held = BroilerBatch.objects.get().batch_name
        rows = {r["id"]: r for r in
                self.client.get(SHEDS, {"farm": self.farm.id}).json()["data"]}
        self.assertTrue(rows[self.shed.id]["occupied"])
        self.assertEqual(rows[self.shed.id]["occupied_by"], held)
        self.assertFalse(rows[self.shed_b.id]["occupied"])
        self.assertEqual(rows[self.shed_b.id]["occupied_by"], "")

    def test_a_closed_batch_frees_its_shed(self):
        # Occupancy means "still growing" — a settled batch is not in the way.
        self.client.post(SAVE, {"broiler_farm_id": self.farm.id,
                                "shed": self.shed.id}, format="json")
        BroilerBatch.objects.update(is_closed=True)
        rows = {r["id"]: r for r in
                self.client.get(SHEDS, {"farm": self.farm.id}).json()["data"]}
        self.assertFalse(rows[self.shed.id]["occupied"])
        resp = self.client.post(SAVE, {"broiler_farm_id": self.farm.id,
                                       "shed": self.shed.id}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
