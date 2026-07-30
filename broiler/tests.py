from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from inventory.models import Item, ItemCategory, Warehouse
from purchase.models import GeneralPurchase, GeneralPurchaseItem, Supplier
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

    def test_clear_drops_the_location_but_keeps_the_files(self):
        self.client.post("/farm-location-capture/add/", {
            "date": "2026-08-01", "farm": self.farm.id,
            "latitude": "26.76", "longitude": "83.37", "photos": self.photo()})
        cap = FarmLocationCapture.objects.get()
        self.client.post("/farm-location-capture/%d/clear/" % cap.id)
        cap.refresh_from_db()
        self.assertIsNone(cap.latitude)
        self.assertIsNone(cap.longitude)
        self.assertEqual(cap.address, "")
        # the pictures taken on that visit are still good
        self.assertEqual(cap.files.count(), 1)
        self.assertEqual(BroilerFarmImage.objects.filter(farm=self.farm).count(), 1)
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

    # ------------------------------------------------- fill pending (+ button)

    def test_fill_completes_a_blank_location(self):
        self.add(latitude="", longitude="", address="")
        cap = FarmLocationCapture.objects.get()
        resp = self.client.post("/farm-location-capture/%d/complete/" % cap.id, {
            "latitude": "26.500000", "longitude": "83.500000", "address": "Found it"})
        self.assertEqual(resp.status_code, 200)
        cap.refresh_from_db()
        self.farm.refresh_from_db()
        print("RESULT fill blank       cap=%s farm=%s" % (cap.latitude, self.farm.farm_latitude))
        self.assertAlmostEqual(cap.latitude, 26.5, places=4)
        self.assertAlmostEqual(self.farm.farm_latitude, 26.5, places=4)

    def test_fill_cannot_overwrite_a_location_already_captured(self):
        self.add(latitude="26.100000", longitude="83.100000", address="First")
        cap = FarmLocationCapture.objects.get()
        resp = self.client.post("/farm-location-capture/%d/complete/" % cap.id, {
            "latitude": "99.000000", "longitude": "99.000000", "address": "Tampered"})
        cap.refresh_from_db()
        print("RESULT lock enforced    status=%s lat=%s address=%r"
              % (resp.status_code, cap.latitude, cap.address))
        self.assertAlmostEqual(cap.latitude, 26.1, places=4)
        self.assertEqual(cap.address, "First")
        self.assertEqual(resp.status_code, 400)      # nothing was pending

    def test_fill_cannot_replace_a_slot_already_holding_a_file(self):
        self.client.post("/farm-location-capture/add/", {
            "date": "2026-08-01", "farm": self.farm.id,
            "slot_pan": self.photo("first_pan.png")})
        cap = FarmLocationCapture.objects.get()
        self.client.post("/farm-location-capture/%d/complete/" % cap.id, {
            "slot_pan": self.photo("second_pan.png")})
        names = [f.file.name for f in cap.files.filter(kind="pan")]
        print("RESULT slot lock        %s" % names)
        self.assertEqual(len(names), 1)
        self.assertIn("first_pan", names[0])

    def test_fill_adds_to_a_slot_that_was_still_empty(self):
        self.add()
        cap = FarmLocationCapture.objects.get()
        self.client.post("/farm-location-capture/%d/complete/" % cap.id, {
            "slot_pan": self.photo("late_pan.png")})
        self.farmer.refresh_from_db()
        print("RESULT late slot filled %s" % self.farmer.pan_upload.name)
        self.assertIn("late_pan", self.farmer.pan_upload.name)

    def test_pictures_can_always_be_added(self):
        self.client.post("/farm-location-capture/add/", {
            "date": "2026-08-01", "farm": self.farm.id, "photos": self.photo("one.png")})
        cap = FarmLocationCapture.objects.get()
        self.client.post("/farm-location-capture/%d/complete/" % cap.id, {
            "photos": [self.photo("two.png"), self.photo("three.png")]})
        count = cap.files.filter(kind=FarmCaptureFile.KIND_PHOTO).count()
        print("RESULT pictures grow    %d" % count)
        self.assertEqual(count, 3)

    def test_register_offers_the_fill_button(self):
        html = self.client.get("/farm-location-capture/").content.decode()
        self.assertIn("act-fill", html)
        self.assertIn('id="fillModal"', html)
        print("RESULT + button present in the action column")

    # -------------------------------------------------- attachments on screen

    def test_edit_form_shows_each_file_under_its_own_slot(self):
        self.client.post("/farm-location-capture/add/", {
            "date": "2026-08-01", "farm": self.farm.id,
            "slot_pan": self.photo("pan_here.png"),
            "photos": self.photo("pic_here.png")})
        cap = FarmLocationCapture.objects.get()
        html = self.client.get("/farm-location-capture/%d/edit/" % cap.id).content.decode()

        # the PAN preview must sit inside the PAN slot, i.e. after that input
        # and before the next slot's input
        pan_input = html.index('name="slot_pan"')
        next_input = html.index('name="slot_aadhar_front"')
        print("RESULT pan preview under its own input: %s"
              % ("pan_here" in html[pan_input:next_input]))
        self.assertIn("pan_here", html[pan_input:next_input])
        self.assertIn("pic_here", html)
        # the old catch-all strip is gone
        self.assertNotIn("Already attached", html)

    def test_api_marks_which_attachments_are_images(self):
        self.client.post("/farm-location-capture/add/", {
            "date": "2026-08-01", "farm": self.farm.id,
            "slot_pan": self.photo("pan.png")})
        row = self.client.get("/farm_location_capture_api/").json()[0]
        pan = [f for f in row["files"] if f["kind"] == "pan"][0]
        print("RESULT api flags image  is_image=%s label=%r" % (pan["is_image"], pan["label"]))
        self.assertTrue(pan["is_image"])
        self.assertEqual(pan["label"], "PAN Card")

    def test_view_dialog_renders_documents_not_just_links(self):
        html = self.client.get("/farm-location-capture/").content.decode()
        self.assertIn("function thumb(", html)
        # documents in the dialog are everything that is not a farm picture
        self.assertIn('r.files.filter(f => f.kind !== "photo")', html)
        print("RESULT view dialog renders attachments")

    # ------------------------------------------------- address from the pin

    def test_form_looks_the_pin_up_as_an_address(self):
        html = self.client.get("/farm-location-capture/add/").content.decode()
        self.assertIn("fillAddressFrom", html)
        self.assertIn('id="address"', html)
        self.assertIn('id="address-note"', html)
        print("RESULT form looks up the pin")

    def test_fill_dialog_looks_the_pin_up_too(self):
        html = self.client.get("/farm-location-capture/").content.decode()
        self.assertIn("window.reverseGeocode", html)
        print("RESULT fill dialog looks up the pin")

    def test_address_is_still_saved_when_typed_by_hand(self):
        # The lookup is a convenience; a typed address must survive untouched.
        self.add(address="Plot 4, Lacchipur, near the canal")
        cap = FarmLocationCapture.objects.get()
        self.farm.refresh_from_db()
        print("RESULT typed address kept  %r" % cap.address)
        self.assertEqual(cap.address, "Plot 4, Lacchipur, near the canal")
        self.assertEqual(self.farm.farm_address, "Plot 4, Lacchipur, near the canal")

    def test_location_saves_even_with_no_address(self):
        # A failed or blocked lookup must not stop the pin being recorded.
        self.add(address="")
        cap = FarmLocationCapture.objects.get()
        print("RESULT pin without address lat=%s address=%r" % (cap.latitude, cap.address))
        self.assertAlmostEqual(cap.latitude, 26.7606, places=4)
        self.assertEqual(cap.address, "")

    # ------------------------------------------------ full location field set

    def test_state_district_area_save_and_reach_the_farm(self):
        self.client.post("/farm-location-capture/add/", {
            "date": "2026-08-01", "farm": self.farm.id,
            "latitude": "26.760600", "longitude": "83.373200",
            "state": "Uttar Pradesh", "district": "Gorakhpur",
            "area": "Lacchipur", "address": "Sonauli Road"})
        cap = FarmLocationCapture.objects.get()
        self.farm.refresh_from_db()
        print("RESULT capture  %s / %s / %s" % (cap.state, cap.district, cap.area))
        print("RESULT farm     %s / %s / %s / %s" % (
            self.farm.state, self.farm.district, self.farm.area, self.farm.farm_address))
        self.assertEqual(cap.state, "Uttar Pradesh")
        self.assertEqual(self.farm.state, "Uttar Pradesh")
        self.assertEqual(self.farm.district, "Gorakhpur")
        self.assertEqual(self.farm.area, "Lacchipur")
        self.assertEqual(self.farm.farm_address, "Sonauli Road")

    def test_a_capture_without_written_parts_does_not_wipe_the_farm(self):
        self.client.post("/farm-location-capture/add/", {
            "date": "2026-08-01", "farm": self.farm.id,
            "latitude": "26.100000", "longitude": "83.100000",
            "state": "Uttar Pradesh", "district": "Gorakhpur", "area": "Lacchipur"})
        # a later visit records only a pin
        self.client.post("/farm-location-capture/add/", {
            "date": "2026-09-01", "farm": self.farm.id,
            "latitude": "26.900000", "longitude": "83.900000"})
        self.farm.refresh_from_db()
        print("RESULT kept     %s / %s / %s  lat=%s" % (
            self.farm.state, self.farm.district, self.farm.area, self.farm.farm_latitude))
        self.assertAlmostEqual(self.farm.farm_latitude, 26.9, places=4)
        self.assertEqual(self.farm.state, "Uttar Pradesh")     # not wiped
        self.assertEqual(self.farm.area, "Lacchipur")

    def test_fill_dialog_completes_blank_written_parts_only(self):
        self.client.post("/farm-location-capture/add/", {
            "date": "2026-08-01", "farm": self.farm.id, "state": "Uttar Pradesh"})
        cap = FarmLocationCapture.objects.get()
        self.client.post("/farm-location-capture/%d/complete/" % cap.id, {
            "state": "Tampered", "district": "Gorakhpur", "area": "Lacchipur"})
        cap.refresh_from_db()
        print("RESULT after +  %s / %s / %s" % (cap.state, cap.district, cap.area))
        self.assertEqual(cap.state, "Uttar Pradesh")   # already filled, locked
        self.assertEqual(cap.district, "Gorakhpur")    # was blank, filled
        self.assertEqual(cap.area, "Lacchipur")

    def test_form_offers_the_whole_location_set(self):
        html = self.client.get("/farm-location-capture/add/").content.decode()
        for name in ('name="state"', 'name="district"', 'name="area"',
                     'name="address"', 'name="latitude"', 'name="longitude"'):
            self.assertIn(name, html)
        print("RESULT form carries every location field")


class DependentDropdownTests(TestCase):
    """Region -> Branch and friends must list each row once.

    The double-listing came from the browser, not the query: the change handler
    ran twice (Select2 raises its own change and main.js re-dispatches a native
    one), each run emptied the select straight away but appended in its reply,
    so both replies filled the emptied list.
    """

    def setUp(self):
        user = get_user_model().objects.create_superuser("dd", "d@x.com", "Str0ngPass!")
        self.client.force_login(user)
        self.region = Region.objects.create(description="Uttar Pradesh")
        self.branches = [
            Branch.objects.create(branch_name=name, region=self.region, prefix=name[:3])
            for name in ("BAHRAICH BRANCH", "VARANASI BRANCH", "AKBARPUR BRANCH")
        ]

    def test_endpoint_returns_each_branch_once(self):
        rows = self.client.get(
            reverse("get_branches_by_region"),
            {"region_id": self.region.id}).json()["branches"]
        names = [r["branch_name"] for r in rows]
        print("RESULT branches returned  %s" % names)
        self.assertEqual(len(names), 3)
        self.assertEqual(len(set(names)), 3)

    def test_cascades_rebuild_rather_than_append(self):
        """Guard the fix: a cascade that appends without emptying first is the
        exact shape that double-fills when its handler runs twice."""
        import re
        offenders = []
        for path in ("broiler/templates/broiler_farm.html",
                     "broiler/templates/broiler_line.html"):
            with open(path, encoding="utf-8") as fh:
                body = fh.read()
            for match in re.finditer(r"\$\.ajax\(\{(.{0,700}?)\}\);", body, re.S):
                block = match.group(1)
                if "append" in block and "empty" not in block:
                    offenders.append(path)
        print("RESULT append-without-rebuild: %s" % (offenders or "none"))
        self.assertEqual(offenders, [])


class BagWeightWarningTests(TestCase):
    """The feed ledger is measured in bags.

    An item with no Kg per Bag cannot be converted, so its columns read 0
    however much was bought — indistinguishable from no activity. The report
    names those items rather than leaving the zeros unexplained.
    """

    def setUp(self):
        u = get_user_model().objects.create_superuser("bw", "b@x.com", "Str0ngPass!")
        self.client.force_login(u)
        self.wh = Warehouse.objects.create(name="Akbarpur Warehouse")
        cat = ItemCategory.objects.create(name="Feed")
        self.item = Item.objects.create(
            description="Pre Starer Feed", category=cat,
            valuation_method="Weighted Average", standard_cost_per_unit=Decimal("50"),
            usage="Produced", source="Purchased", type="Raw Material",
            item_account="Expense")                     # deliberately no kg_per_bag
        supplier = Supplier.objects.create(name="Maharashtra Feeds Pvt Ltd")
        p = GeneralPurchase.objects.create(
            date=date(2026, 7, 21), supplier=supplier,
            calculation_based_on="Received Quantity")
        GeneralPurchaseItem.objects.create(
            purchase=p, item=self.item, farm_warehouse=self.wh,
            sent_qty=Decimal("1500"), rcv_qty=Decimal("1500"), free_qty=Decimal("0"),
            rate=Decimal("30"), discount_percent=Decimal("0"),
            discount_amount=Decimal("0"), gst_percent=Decimal("0"))

    def report(self):
        return self.client.get("/feed-dispatch-stock-report/", {
            "warehouse": self.wh.id, "from_date": "2026-01-01",
            "to_date": "2026-12-31", "submit": "1"}).content.decode()

    def test_missing_bag_weight_is_called_out(self):
        html = self.report()
        self.assertIn("have no Bag Capacity", html)
        self.assertIn("Pre Starer Feed", html)

    def test_no_warning_once_the_bag_weight_is_set(self):
        self.item.kg_per_bag = Decimal("50")
        self.item.save(update_fields=["kg_per_bag"])
        html = self.report()   # 1500 kg / 50
        self.assertNotIn("have no Bag Capacity", html)
        self.assertIn("30.00", html)
