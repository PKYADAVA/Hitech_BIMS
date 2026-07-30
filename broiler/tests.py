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

    # ------------------------------------------------------- master documents

    def test_each_slot_lands_on_its_master_field(self):
        self.client.post("/farm-location-capture/add/", {
            "date": "2026-08-01", "farm": self.farm.id,
            "slot_farmer_photo": self.photo("face.png"),
            "slot_pan": self.photo("pan.png"),
            "slot_aadhar_front": self.photo("af.png"),
            "slot_aadhar_back": self.photo("ab.png"),
            "slot_agreement": self.photo("agr.png"),
            "slot_cheque_1": self.photo("chq1.png"),
        })
        self.farmer.refresh_from_db()
        self.farm.refresh_from_db()
        for label, value, expect in (
            ("farmer_photo", self.farmer.farmer_photo.name, "face"),
            ("pan_upload", self.farmer.pan_upload.name, "pan"),
            ("aadhar_front", self.farmer.aadhar_upload_front.name, "af"),
            ("aadhar_back", self.farmer.aadhar_upload_back.name, "ab"),
            ("agreement_copy", self.farm.agreement_copy.name, "agr"),
            ("cheque_1_file", self.farm.cheque_1_file.name, "chq1"),
        ):
            print("RESULT %-16s -> %s" % (label, value))
            self.assertIn(expect, value)

    def test_a_newer_capture_replaces_the_master_document(self):
        self.client.post("/farm-location-capture/add/", {
            "date": "2026-08-01", "farm": self.farm.id,
            "slot_pan": self.photo("old_pan.png")})
        self.client.post("/farm-location-capture/add/", {
            "date": "2026-09-01", "farm": self.farm.id,
            "slot_pan": self.photo("new_pan.png")})
        self.farmer.refresh_from_db()
        print("RESULT pan after newer  -> %s" % self.farmer.pan_upload.name)
        self.assertIn("new_pan", self.farmer.pan_upload.name)

    def test_deleting_the_newer_capture_falls_back_to_the_older_document(self):
        self.client.post("/farm-location-capture/add/", {
            "date": "2026-08-01", "farm": self.farm.id,
            "slot_pan": self.photo("old_pan.png")})
        self.client.post("/farm-location-capture/add/", {
            "date": "2026-09-01", "farm": self.farm.id,
            "slot_pan": self.photo("new_pan.png")})
        newest = FarmLocationCapture.objects.order_by("-date").first()
        self.client.post("/farm-location-capture/%d/delete/" % newest.id)
        self.farmer.refresh_from_db()
        print("RESULT pan after delete -> %s" % self.farmer.pan_upload.name)
        self.assertIn("old_pan", self.farmer.pan_upload.name)

    def test_form_offers_every_master_slot(self):
        html = self.client.get("/farm-location-capture/add/").content.decode()
        for name in ("slot_farmer_photo", "slot_pan", "slot_aadhar_front",
                     "slot_aadhar_back", "slot_agreement", "slot_cheque_1",
                     "slot_cheque_2", "slot_cheque_3", "slot_cheque_4"):
            self.assertIn('name="%s"' % name, html)
        for label in ("Farmer Photo", "PAN Card", "Aadhar (Front)",
                      "Aadhar (Back)", "Agreement Copy", "Farm Pictures"):
            self.assertIn(label, html)
        print("RESULT form offers all slots and labels")

    def test_several_picture_rows_all_arrive(self):
        # The form repeats a file input named "photos"; the view reads them all.
        self.client.post("/farm-location-capture/add/", {
            "date": "2026-08-01", "farm": self.farm.id,
            "photos": [self.photo("a.png"), self.photo("b.png"), self.photo("c.png")],
        })
        cap = FarmLocationCapture.objects.get()
        photos = cap.files.filter(kind=FarmCaptureFile.KIND_PHOTO).count()
        mirrored = BroilerFarmImage.objects.filter(farm=self.farm).count()
        print("RESULT picture rows     %d captured, %d mirrored on the farm" % (photos, mirrored))
        self.assertEqual(photos, 3)
        self.assertEqual(mirrored, 3)

    def test_form_has_the_add_picture_control(self):
        html = self.client.get("/farm-location-capture/add/").content.decode()
        for token in ('id="add-picture"', 'id="picture-rows"', 'Add Picture'):
            self.assertIn(token, html)
        # rows are added by the script, so the container ships empty
        self.assertIn('<div id="picture-rows"></div>', html)
        print("RESULT add-picture control present, single input removed")

    def test_branch_select_precedes_farm_and_tags_each_farm(self):
        html = self.client.get("/farm-location-capture/add/").content.decode()
        self.assertIn('id="branch"', html)
        # Branch must come before Farm in the markup
        self.assertLess(html.index('id="branch"'), html.index('id="farm"'))
        # every farm option carries its branch so the list can be narrowed
        self.assertIn('data-branch="%d"' % self.branch.id, html)
        print("RESULT branch select before farm, farms tagged with branch")

    def test_branch_is_not_stored_on_the_capture(self):
        # It only narrows the list; the branch is already reachable via the farm.
        self.add()
        cap = FarmLocationCapture.objects.get()
        self.assertFalse(hasattr(cap, "branch_id"))
        self.assertEqual(cap.farm.branch, self.branch)
        print("RESULT branch derived from the farm, not duplicated")

