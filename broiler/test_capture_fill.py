"""Filling a capture's blanks from the phone, and dropping a wrong pin.

Both delegate to the web views, so what is under test here is that the phone
reaches the same rule — above all that a fill writes *blanks only*. A request
that could replace a GPS reading or a scanned cheque would be worse than no
button at all, and the phone locking those boxes is a courtesy, not the guard.
"""
from datetime import date

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase

from broiler.models import (Branch, BroilerFarm, FarmCaptureFile,
                            FarmLocationCapture, Farmer, Region, Supervisor)

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
       b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
       b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")


def png(name="shot.png"):
    return SimpleUploadedFile(name, PNG, content_type="image/png")


class CaptureFillTests(APITestCase):
    def setUp(self):
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Bahraich", region=region,
                                       prefix="BHR")
        supervisor = Supervisor.objects.create(branch=branch, name="R. Verma")
        self.farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=supervisor, farmer=self.farmer,
            region=region, line="L1", farm_name="Yadav Farm", farm_capacity=900)
        self.user = get_user_model().objects.create_superuser("u", password="x")
        self.client.force_authenticate(self.user)

    def capture(self, **kw):
        return FarmLocationCapture.objects.create(
            farm=self.farm, date=date(2026, 8, 1), captured_by=self.user, **kw)

    def fill(self, cap, **data):
        return self.client.post(
            f"/api/v1/broiler/location-captures/{cap.id}/fill", data,
            format="multipart")

    # --- what it fills ---------------------------------------------------

    def test_a_blank_pin_and_address_are_filled(self):
        cap = self.capture()
        resp = self.fill(cap, latitude="26.7", longitude="82.1",
                         state="UP", district="Bahraich", area="Nanpara",
                         address="Near the canal")
        self.assertEqual(resp.status_code, 200, resp.content)
        cap.refresh_from_db()
        self.assertEqual(float(cap.latitude), 26.7)
        self.assertEqual(cap.district, "Bahraich")
        self.assertEqual(cap.address, "Near the canal")

    def test_what_is_already_there_is_not_replaced(self):
        # The whole point of the "+": it adds, it never amends.
        cap = self.capture(latitude=20.0, longitude=80.0, district="Gonda",
                           address="Old address")
        self.fill(cap, latitude="26.7", longitude="82.1",
                  district="Bahraich", address="New address")
        cap.refresh_from_db()
        self.assertEqual(float(cap.latitude), 20.0)
        self.assertEqual(cap.district, "Gonda")
        self.assertEqual(cap.address, "Old address")

    def test_a_document_slot_already_held_is_left_alone(self):
        cap = self.capture()
        FarmCaptureFile.objects.create(capture=cap, kind="pan", file=png("first.png"))
        self.fill(cap, slot_pan=png("second.png"))
        pans = cap.files.filter(kind="pan")
        self.assertEqual(pans.count(), 1)
        self.assertIn("first", pans.first().file.name)

    def test_an_empty_slot_is_filled(self):
        cap = self.capture()
        self.fill(cap, slot_agreement=png("agreement.png"))
        self.assertEqual(cap.files.filter(kind="agreement").count(), 1)

    def test_pictures_are_never_full(self):
        # More photographs of a farm are always worth having, so these two are
        # offered whatever is already held.
        cap = self.capture()
        FarmCaptureFile.objects.create(capture=cap, kind="photo", file=png("a.png"))
        self.fill(cap, photos=png("b.png"))
        self.assertEqual(cap.files.filter(kind="photo").count(), 2)

    def test_the_pin_goes_in_as_a_pair_or_not_at_all(self):
        cap = self.capture()
        self.fill(cap, latitude="26.7")
        cap.refresh_from_db()
        self.assertIsNone(cap.latitude)
        self.assertIsNone(cap.longitude)

    # --- clearing --------------------------------------------------------

    def test_clearing_drops_the_pin_and_keeps_the_visit(self):
        cap = self.capture(latitude=26.7, longitude=82.1, address="Near the canal")
        FarmCaptureFile.objects.create(capture=cap, kind="photo", file=png())
        resp = self.client.post(
            f"/api/v1/broiler/location-captures/{cap.id}/clear")
        self.assertEqual(resp.status_code, 200, resp.content)
        cap.refresh_from_db()
        self.assertIsNone(cap.latitude)
        self.assertIsNone(cap.longitude)
        # The visit and its evidence survive — only the reading goes.
        self.assertEqual(cap.files.filter(kind="photo").count(), 1)
        self.assertTrue(FarmLocationCapture.objects.filter(pk=cap.pk).exists())

    def test_a_cleared_capture_can_be_pinned_again(self):
        cap = self.capture(latitude=26.7, longitude=82.1)
        self.client.post(f"/api/v1/broiler/location-captures/{cap.id}/clear")
        self.fill(cap, latitude="27.0", longitude="83.0")
        cap.refresh_from_db()
        self.assertEqual(float(cap.latitude), 27.0)
