from datetime import date

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from broiler.models import (
    Branch, BroilerFarm, BroilerFarmImage, FarmCaptureFile, FarmLocationCapture,
    Farmer, Region, Supervisor,
)

# 1x1 png so an ImageField-backed mirror has real bytes behind it
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
       b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
       b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")


class FarmLocationCaptureTests(TestCase):
    """Broiler > Transactions > Farm Location & Photos.

    The capture is the record of a visit; the farm master carries whatever
    the most recent visit found. These cover that write-through in both
    directions, the photo mirror onto the farm, and the difference between
    Clear (keep the visit, drop what it captured) and Delete.
    """

    def setUp(self):
        self.user = get_user_model().objects.create_superuser("cap", "c@x.com", "Str0ngPass!")
        self.client.force_login(self.user)
        self.region = Region.objects.create(description="East")
        self.branch = Branch.objects.create(
            branch_name="Gorakhpur", region=self.region, prefix="GKP")
        self.supervisor = Supervisor.objects.create(name="Ramesh", branch=self.branch)
        self.farmer = Farmer.objects.create(farmer_name="Suresh Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=self.branch, supervisor=self.supervisor, farmer=self.farmer,
            region="East", line="L1", farm_name="Lacchipur Farm", farm_capacity=5000)

    def photo(self, name="p.png"):
        return SimpleUploadedFile(name, PNG, content_type="image/png")

    def add(self, **over):
        data = {"date": "2026-08-01", "farm": self.farm.id,
                "latitude": "26.760600", "longitude": "83.373200",
                "address": "Lacchipur, Gorakhpur", "remarks": ""}
        data.update(over)
        return self.client.post("/farm-location-capture/add/", data)

    # ------------------------------------------------------------------ core

    def test_capture_writes_location_through_to_the_farm(self):
        resp = self.add()
        self.assertEqual(resp.status_code, 302)
        cap = FarmLocationCapture.objects.get()
        self.assertTrue(cap.capture_no.startswith("FLC-2627-"))
        self.farm.refresh_from_db()
        self.assertAlmostEqual(self.farm.farm_latitude, 26.7606, places=4)
        self.assertEqual(self.farm.farm_address, "Lacchipur, Gorakhpur")

    def test_farmer_is_read_from_the_farm(self):
        self.add()
        cap = FarmLocationCapture.objects.get()
        self.assertEqual(cap.farmer, self.farmer)

    def test_photo_is_mirrored_onto_the_farm(self):
        self.client.post("/farm-location-capture/add/", {
            "date": "2026-08-01", "farm": self.farm.id,
            "latitude": "26.76", "longitude": "83.37",
            "photos": self.photo()})
        self.assertEqual(BroilerFarmImage.objects.filter(farm=self.farm).count(), 1)
        self.assertEqual(FarmCaptureFile.objects.count(), 1)

    def test_half_a_coordinate_pair_is_rejected(self):
        self.add(longitude="")
        self.assertFalse(FarmLocationCapture.objects.exists())

    # --------------------------------------------------------------- actions

    def test_clear_keeps_the_visit_but_drops_location_and_files(self):
        self.client.post("/farm-location-capture/add/", {
            "date": "2026-08-01", "farm": self.farm.id,
            "latitude": "26.76", "longitude": "83.37", "photos": self.photo()})
        cap = FarmLocationCapture.objects.get()
        self.client.post("/farm-location-capture/%d/clear/" % cap.id)
        cap.refresh_from_db()
        print("RESULT after clear         lat=%s files=%d farm_images=%d record_kept=%s" % (
            cap.latitude, cap.files.count(),
            BroilerFarmImage.objects.filter(farm=self.farm).count(),
            FarmLocationCapture.objects.filter(id=cap.id).exists()))
        self.assertIsNone(cap.latitude)
        self.assertEqual(cap.files.count(), 0)
        self.assertEqual(BroilerFarmImage.objects.filter(farm=self.farm).count(), 0)
        self.assertTrue(FarmLocationCapture.objects.filter(id=cap.id).exists())

    def test_delete_removes_the_capture_and_falls_back_to_the_previous_one(self):
        self.add(date="2026-08-01", latitude="26.100000", longitude="83.100000")
        self.add(date="2026-09-01", latitude="26.900000", longitude="83.900000")
        self.farm.refresh_from_db()
        self.assertAlmostEqual(self.farm.farm_latitude, 26.9, places=4)

        newest = FarmLocationCapture.objects.order_by("-date").first()
        self.client.post("/farm-location-capture/%d/delete/" % newest.id)
        self.farm.refresh_from_db()
        self.assertAlmostEqual(self.farm.farm_latitude, 26.1, places=4)

    def test_editing_an_older_capture_does_not_override_the_newer_one(self):
        self.add(date="2026-08-01", latitude="26.100000", longitude="83.100000")
        self.add(date="2026-09-01", latitude="26.900000", longitude="83.900000")
        older = FarmLocationCapture.objects.order_by("date").first()
        self.client.post("/farm-location-capture/%d/edit/" % older.id, {
            "date": "2026-08-01", "farm": self.farm.id,
            "latitude": "26.200000", "longitude": "83.200000"})
        self.farm.refresh_from_db()
        self.assertAlmostEqual(self.farm.farm_latitude, 26.9, places=4)

    # ------------------------------------------------------------ register

    def test_register_and_api(self):
        self.add()
        page = self.client.get("/farm-location-capture/")
        self.assertEqual(page.status_code, 200)
        rows = self.client.get("/farm_location_capture_api/").json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["farmer"], "Suresh Yadav")
        self.assertTrue(rows[0]["has_location"])

    def test_narration_is_generated(self):
        self.add()
        cap = FarmLocationCapture.objects.get()
        self.assertIn("Location Capture", cap.remarks)
