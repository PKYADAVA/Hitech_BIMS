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

    def create(self, **over):
        """A valid create, with the required three filled unless overridden."""
        body = {"broiler_farm_id": self.farm.id, "shed": self.shed.id,
                "breed": self.breed.id}
        body.update(over)
        return self.client.post(SAVE, body, format="json")

    # --- creating -------------------------------------------------------

    def test_create_generates_the_batch_number(self):
        resp = self.create(book_number="BK-1", lot_no="LOT-1")
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
        self.create(batch_name="MINE-999")
        self.assertEqual(BroilerBatch.objects.get().batch_name,
                         f"{self.farm.farm_code.removeprefix('FRM/')}-1")

    def test_numbers_run_on_per_farm(self):
        self.create(shed=self.shed.id)
        self.create(shed=self.shed_b.id)
        self.create(broiler_farm_id=self.other_farm.id, shed=self.far_shed.id)
        prefix = self.farm.farm_code.removeprefix("FRM/")
        self.assertEqual(
            sorted(BroilerBatch.objects.filter(broiler_farm=self.farm)
                   .values_list("batch_name", flat=True)),
            [f"{prefix}-1", f"{prefix}-2"])
        self.assertEqual(
            BroilerBatch.objects.get(broiler_farm=self.other_farm).batch_name,
            f"{self.other_farm.farm_code.removeprefix('FRM/')}-1")

    def test_an_occupied_shed_is_refused_by_name(self):
        self.create()
        resp = self.create()
        self.assertEqual(resp.status_code, 400)
        # Naming the batch in the way is the whole point of the message.
        self.assertIn(BroilerBatch.objects.first().batch_name,
                      str(resp.content))
        self.assertEqual(BroilerBatch.objects.count(), 1)

    def test_a_batch_needs_a_shed_and_a_breed(self):
        # Required on the desktop form and here both — a flock is housed
        # somewhere, and is of some breed.
        no_shed = self.create(shed="")
        self.assertEqual(no_shed.status_code, 400)
        self.assertIn("shed", str(no_shed.content).lower())

        no_breed = self.create(breed="")
        self.assertEqual(no_breed.status_code, 400)
        self.assertIn("breed", str(no_breed.content).lower())

        self.assertEqual(BroilerBatch.objects.count(), 0)

    # --- editing --------------------------------------------------------

    def test_edit_changes_what_the_erp_allows_and_nothing_else(self):
        self.create(book_number="BK-1")
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
        self.create(shed=self.shed.id)
        self.create(shed=self.shed_b.id)
        moving = BroilerBatch.objects.get(shed=self.shed_b)
        resp = self.client.put(f"{SAVE}/{moving.id}", {"shed": self.shed.id},
                               format="json")
        self.assertEqual(resp.status_code, 400)
        moving.refresh_from_db()
        self.assertEqual(moving.shed_id, self.shed_b.id)

    def test_an_edit_cannot_clear_the_shed_or_the_breed(self):
        self.create()
        batch = BroilerBatch.objects.get()
        for field in ("shed", "breed"):
            resp = self.client.put(f"{SAVE}/{batch.id}", {field: ""},
                                   format="json")
            self.assertEqual(resp.status_code, 400, f"{field}: {resp.content}")
        batch.refresh_from_db()
        self.assertEqual(batch.shed_id, self.shed.id)
        self.assertEqual(batch.breed_id, self.breed.id)

    def test_an_edit_that_does_not_mention_them_leaves_them_alone(self):
        # Absent is a partial update, not an attempt to clear — otherwise
        # correcting only the book number would fail on a field nobody touched.
        self.create()
        batch = BroilerBatch.objects.get()
        resp = self.client.put(f"{SAVE}/{batch.id}", {"book_number": "BK-5"},
                               format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        batch.refresh_from_db()
        self.assertEqual(batch.book_number, "BK-5")
        self.assertEqual(batch.shed_id, self.shed.id)
        self.assertEqual(batch.breed_id, self.breed.id)

    def test_a_batch_can_be_saved_onto_the_shed_it_already_holds(self):
        # Re-saving without moving must not read as a clash with itself.
        self.create()
        batch = BroilerBatch.objects.get()
        resp = self.client.put(f"{SAVE}/{batch.id}",
                               {"shed": self.shed.id, "book_number": "BK-7"},
                               format="json")
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_get_returns_the_form_shape(self):
        self.create(lot_no="LOT-3")
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
        self.create()
        held = BroilerBatch.objects.get().batch_name
        rows = {r["id"]: r for r in
                self.client.get(SHEDS, {"farm": self.farm.id}).json()["data"]}
        self.assertTrue(rows[self.shed.id]["occupied"])
        self.assertEqual(rows[self.shed.id]["occupied_by"], held)
        self.assertFalse(rows[self.shed_b.id]["occupied"])
        self.assertEqual(rows[self.shed_b.id]["occupied_by"], "")

    def test_a_closed_batch_frees_its_shed(self):
        # Occupancy means "still growing" — a settled batch is not in the way.
        self.create()
        BroilerBatch.objects.update(is_closed=True)
        rows = {r["id"]: r for r in
                self.client.get(SHEDS, {"farm": self.farm.id}).json()["data"]}
        self.assertFalse(rows[self.shed.id]["occupied"])
        self.assertEqual(self.create().status_code, 201)
