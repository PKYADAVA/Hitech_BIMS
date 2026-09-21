# -*- coding: utf-8 -*-
"""Starting several flocks in one save, on one farm or on several.

A placement round starts flocks on a handful of farms the same morning. The
rules a single batch has to meet are the same ones each row has to meet, and
a bad row refuses the lot rather than leaving a half-saved round behind.
"""
import json

from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import (Branch, Breed, BroilerBatch, BroilerFarm, BroilerFarmShed,
                     Farmer, Region, Supervisor)

SAVE = "/create-batches/"


class BatchRowsTests(TestCase):
    def setUp(self):
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region,
                                       prefix="AKB")
        supervisor = Supervisor.objects.create(branch=branch, name="R. Verma")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=supervisor, farmer=farmer, region=region,
            line="L1", farm_name="Yadav Farm", farm_capacity=5000)
        self.other = BroilerFarm.objects.create(
            branch=branch, supervisor=supervisor, farmer=farmer, region=region,
            line="L2", farm_name="Pal Farm", farm_capacity=3000)
        self.shed = BroilerFarmShed.objects.create(farm=self.farm, shed_name="Shed A")
        self.shed_b = BroilerFarmShed.objects.create(farm=self.farm, shed_name="Shed B")
        self.far_shed = BroilerFarmShed.objects.create(farm=self.other, shed_name="Shed Z")
        self.breed = Breed.objects.create(code="COBB", description="Cobb 500")
        self.user = get_user_model().objects.create_superuser("u", password="x")
        self.client.force_login(self.user)

    def row(self, farm=None, unit=None, **over):
        body = {"broiler_farm_id": (farm or self.farm).id,
                "shed": (unit or self.shed).id, "breed": self.breed.id}
        body.update(over)
        return body

    def post(self, *rows):
        return self.client.post(SAVE, json.dumps({"rows": list(rows)}),
                                content_type="application/json")

    def prefix(self, farm):
        return farm.farm_code.removeprefix("FRM/")

    def test_one_row_is_still_a_save(self):
        resp = self.post(self.row(book_number="BK-1"))
        self.assertEqual(resp.status_code, 201, resp.content)
        batch = BroilerBatch.objects.get()
        self.assertEqual(batch.batch_name, f"{self.prefix(self.farm)}-1")
        self.assertEqual(batch.book_number, "BK-1")

    def test_flocks_on_several_farms_in_one_save(self):
        resp = self.post(self.row(), self.row(farm=self.other, unit=self.far_shed))
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(
            {b.broiler_farm_id for b in BroilerBatch.objects.all()},
            {self.farm.id, self.other.id})
        self.assertEqual([r["farm"] for r in resp.json()["created"]],
                         ["Yadav Farm", "Pal Farm"])

    def test_two_rows_on_one_farm_take_consecutive_numbers(self):
        # The form shows the second row the number after the first; the real
        # ones are minted here, and they have to agree.
        resp = self.post(self.row(), self.row(unit=self.shed_b))
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(
            sorted(BroilerBatch.objects.values_list("batch_name", flat=True)),
            [f"{self.prefix(self.farm)}-1", f"{self.prefix(self.farm)}-2"])

    def test_two_rows_may_share_one_unit(self):
        resp = self.post(self.row(), self.row())
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(BroilerBatch.objects.filter(shed=self.shed).count(), 2)

    def test_a_row_missing_its_shed_refuses_the_lot(self):
        resp = self.post(self.row(), self.row(shed=""))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["errors"][0]["row"], 2)
        self.assertIn("shed", resp.json()["errors"][0]["error"].lower())
        self.assertEqual(BroilerBatch.objects.count(), 0)

    def test_a_shed_on_another_farm_refuses_the_lot(self):
        resp = self.post(self.row(), self.row(unit=self.far_shed))
        self.assertEqual(resp.status_code, 400)
        self.assertIn(self.farm.farm_name, resp.json()["errors"][0]["error"])
        self.assertEqual(BroilerBatch.objects.count(), 0)

    def test_every_bad_row_is_named_not_just_the_first(self):
        resp = self.post(self.row(), self.row(breed=""), self.row(shed=""))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual([e["row"] for e in resp.json()["errors"]], [2, 3])

    def test_a_row_with_no_farm_is_refused(self):
        resp = self.post(self.row(), {"shed": self.shed.id, "breed": self.breed.id})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("farm", resp.json()["errors"][0]["error"].lower())
        self.assertEqual(BroilerBatch.objects.count(), 0)

    def test_no_rows_is_refused(self):
        resp = self.client.post(SAVE, json.dumps({"rows": []}),
                                content_type="application/json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("at least one", resp.json()["error"].lower())

    def test_it_takes_a_post_only(self):
        self.assertEqual(self.client.get(SAVE).status_code, 405)
