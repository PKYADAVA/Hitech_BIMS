"""A lifting recorded on the phone, and what the desk can check afterwards.

A bird sale is the one broiler transaction nobody at the branch witnesses: the
birds leave the farm and the branch is billed for whatever the weighbridge slip
says. The phone form therefore stamps where the lifting happened and
photographs the truck, the birds and the slip.

These cover the three places that can quietly stop being true:

* the evidence survives the round trip and reaches the register, and a sale
  typed up at a desk — which has neither camera nor GPS — still saves;
* the batch a sale is filed against is the one the form asked for, not one the
  server re-derives (the API used to overwrite it);
* the customer's outstanding balance the phone shows is the same figure the
  web form shows, because both come from the Customer Balance report.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from broiler.models import (Branch, BirdSale, BirdSalePhoto, BroilerBatch,
                            BroilerFarm, Farmer, Region, Supervisor)
from hr.models import Employee
from sales.models import Customer

#: The smallest thing Pillow will open as an image — the tests are about the
#: rows and the wiring, not about JPEG.
ONE_PIXEL_GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!"
    b"\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00"
    b"\x00\x02\x02D\x01\x00;"
)


def a_photo(name="truck.gif"):
    return SimpleUploadedFile(name, ONE_PIXEL_GIF, content_type="image/gif")


class BirdSaleEvidenceTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region, prefix="AKB")
        supervisor = Supervisor.objects.create(branch=branch, name="R. Verma")
        self.farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=supervisor, farmer=self.farmer, region=region,
            line="L1", farm_name="Green Valley Farm", farm_capacity=9000)
        self.other_farm = BroilerFarm.objects.create(
            branch=branch, supervisor=supervisor, farmer=self.farmer, region=region,
            line="L1", farm_name="Other Farm", farm_capacity=5000)
        self.customer = Customer.objects.create(name="Metro Poultry")
        self.employee = Employee.objects.create(full_name="Suraj Yadav")

        User = get_user_model()
        self.user = User.objects.create_superuser("bse_user", "bse@x.com", "Str0ngPass!")
        self.client.force_login(self.user)

    def batch(self, farm, name, days_ago=30):
        return BroilerBatch.objects.create(
            broiler_farm=farm, batch_name=name,
            start_date=self.today - timedelta(days=days_ago))

    def a_sale(self, **kw):
        defaults = dict(
            date=self.today, sale_type="customer", customer=self.customer,
            farm=self.farm, birds=1250, net_weight=Decimal("2625.00"),
            rate=Decimal("102.00"), lifting_supervisor=self.employee,
            vehicle="UP53AB1234", driver="Ramesh Kumar")
        defaults.update(kw)
        return BirdSale.objects.create(**defaults)

    # ---- the pin and the pictures ------------------------------------------

    def test_a_desk_sale_saves_with_no_evidence_at_all(self):
        """The web form has no camera and no GPS, and must keep working."""
        sale = self.a_sale()
        self.assertFalse(sale.has_location)
        self.assertEqual(sale.photos.count(), 0)

    def test_the_pin_and_photos_reach_the_register(self):
        sale = self.a_sale(lift_latitude=26.85, lift_longitude=80.95,
                           lift_place="Green Valley Farm, Sitapur, UP")
        for kind in BirdSalePhoto.REQUIRED_KINDS:
            BirdSalePhoto.objects.create(sale=sale, kind=kind, image=a_photo(f"{kind}.gif"))

        from broiler.views import _bird_sale_to_dict

        row = _bird_sale_to_dict(BirdSale.objects.prefetch_related("photos").get(pk=sale.pk))
        self.assertEqual(row["lift_latitude"], 26.85)
        self.assertEqual(row["lift_longitude"], 80.95)
        self.assertEqual(row["lift_place"], "Green Valley Farm, Sitapur, UP")
        self.assertEqual([p["kind"] for p in row["photos"]],
                         ["birds", "truck", "weighbridge"])   # Meta.ordering by kind
        self.assertTrue(all(p["url"] for p in row["photos"]))

    def test_the_register_offers_a_way_to_look_at_the_evidence(self):
        """Captured but unviewable is the same as not captured."""
        from django.urls import reverse

        page = self.client.get(reverse("bird_sale_list")).content.decode()
        self.assertIn("Evidence", page)
        self.assertIn("evidenceModal", page)
        self.assertIn("evidenceCell", page)

    def test_the_edit_form_shows_what_the_phone_captured(self):
        from django.urls import reverse

        sale = self.a_sale(lift_latitude=26.85, lift_longitude=80.95,
                           lift_place="Green Valley Farm, Sitapur, UP")
        BirdSalePhoto.objects.create(sale=sale, kind="weighbridge", image=a_photo("wb.gif"))

        page = self.client.get(reverse("bird_sale_edit", args=[sale.id])).content.decode()
        self.assertIn("Lifting Evidence", page)
        self.assertIn("Green Valley Farm, Sitapur, UP", page)
        self.assertIn("Weighbridge Slip", page)
        self.assertIn("google.com/maps?q=26.85,80.95", page)

    def test_a_desk_sale_grows_no_empty_evidence_card(self):
        from django.urls import reverse

        sale = self.a_sale()
        page = self.client.get(reverse("bird_sale_edit", args=[sale.id])).content.decode()
        self.assertNotIn("Lifting Evidence", page)

    def test_the_lifting_report_carries_the_evidence_column(self):
        """The register shows it per sale; the Lifting Report is where the desk
        reconciles a day's billing, so it has to be checkable there too."""
        from django.urls import reverse

        sale = self.a_sale(lift_latitude=26.85, lift_longitude=80.95,
                           lift_place="Green Valley Farm, Sitapur, UP")
        BirdSalePhoto.objects.create(sale=sale, kind="truck", image=a_photo("t.gif"))
        BirdSalePhoto.objects.create(sale=sale, kind="weighbridge", image=a_photo("w.gif"))

        page = self.client.get(reverse("lifting_report"),
                               {"from_date": self.today.isoformat(),
                                "to_date": self.today.isoformat()}).content.decode()
        self.assertIn("Uploaded Image", page)
        self.assertIn("liftPhotosModal", page)
        self.assertIn("google.com/maps?q=26.85,80.95", page)
        # Both photos travel on the button, labelled.
        self.assertIn("Truck Photo|Weighbridge Slip", page)

    def test_a_desk_lifting_shows_a_dash_rather_than_empty_controls(self):
        from django.urls import reverse

        self.a_sale()
        page = self.client.get(reverse("lifting_report"),
                               {"from_date": self.today.isoformat(),
                                "to_date": self.today.isoformat()}).content.decode()
        self.assertIn("Uploaded Image", page)
        # `data-urls` is only ever on the camera button; the class name also
        # appears in the page's own click handler, so it proves nothing.
        self.assertNotIn("data-urls", page)
        self.assertIn("lr-evidence", page)

    def test_deleting_a_photo_takes_its_file_with_it(self):
        sale = self.a_sale()
        photo = BirdSalePhoto.objects.create(sale=sale, kind="truck", image=a_photo())
        storage, name = photo.image.storage, photo.image.name
        self.assertTrue(storage.exists(name))
        photo.delete()
        self.assertFalse(storage.exists(name))

    def test_the_api_caps_photos_per_kind(self):
        """The phone counts what is on its own screen; the server counts what
        it holds, which differs after a retry or a second device."""
        from broiler.api import BirdSalePhotoSerializer

        sale = self.a_sale()
        for i in range(BirdSalePhoto.MAX_PER_KIND):
            BirdSalePhoto.objects.create(sale=sale, kind="truck", image=a_photo(f"t{i}.gif"))

        ser = BirdSalePhotoSerializer(data={"sale": sale.id, "kind": "truck",
                                            "image": a_photo("over.gif")})
        self.assertFalse(ser.is_valid())
        self.assertIn("image", ser.errors)

        # A different kind on the same sale is unaffected.
        ok = BirdSalePhotoSerializer(data={"sale": sale.id, "kind": "birds",
                                           "image": a_photo("b.gif")})
        self.assertTrue(ok.is_valid(), ok.errors)

    # ---- the total, and the rounding that gets it there ---------------------

    def test_round_off_is_derived_rather_than_typed(self):
        """It used to be an editable box, so the same weighment came to a
        different figure depending on who keyed it in."""
        sale = self.a_sale(net_weight=Decimal("2625.55"), rate=Decimal("102.00"))
        raw = Decimal("2625.55") * Decimal("102.00")          # 267806.10
        self.assertEqual(sale.amount, Decimal("267806"))       # billed to the rupee
        self.assertEqual(sale.round_off, Decimal("267806") - raw)
        self.assertEqual(sale.amount - sale.round_off, raw)    # nothing lost

    def test_a_value_sent_for_round_off_is_ignored(self):
        """The column is `editable=False`, so neither form can set it."""
        from broiler.views import _apply_bird_sale

        instance = BirdSale(entry_by=self.user)
        _apply_bird_sale(instance, {
            "date": self.today.isoformat(), "sale_type": "customer",
            "customer": self.customer.id, "farm": self.farm.id,
            "birds": "100", "net_weight": "10.50", "rate": "100.00",
            "round_off": "-999.00", "amount": "1.00",
        })
        instance.save()
        self.assertEqual(instance.amount, Decimal("1050"))
        self.assertEqual(instance.round_off, Decimal("0.00"))

    def test_rounding_goes_up_at_the_half(self):
        sale = self.a_sale(net_weight=Decimal("1.005"), rate=Decimal("1000.00"))
        self.assertEqual(sale.amount, Decimal("1005"))

    # ---- which batch the sale is filed against -----------------------------

    def test_the_chosen_batch_is_kept_when_a_farm_runs_two(self):
        """The form asks which flock; the answer used to be thrown away.

        `validate` overwrote `batch` with the farm's active batch whatever the
        client sent, so a two-flock farm's sale was filed against whichever one
        sorted first — from a picker the supervisor had just answered.
        """
        from broiler.api import BirdSaleSerializer

        first = self.batch(self.farm, "BR2607", days_ago=40)
        second = self.batch(self.farm, "BR2608", days_ago=10)

        ser = BirdSaleSerializer(data={
            "date": self.today.isoformat(), "sale_type": "customer",
            "customer": self.customer.id, "farm": self.farm.id, "batch": second.id,
            "birds": 100, "net_weight": "200.00", "rate": "100.00",
        })
        self.assertTrue(ser.is_valid(), ser.errors)
        self.assertEqual(ser.validated_data["batch"], second)
        self.assertNotEqual(second, first)

    def test_a_batch_from_another_farm_is_refused(self):
        """The id arrives from a phone, so it is checked rather than trusted."""
        from broiler.api import BirdSaleSerializer

        mine = self.batch(self.farm, "BR2607")
        theirs = self.batch(self.other_farm, "BR9999")

        ser = BirdSaleSerializer(data={
            "date": self.today.isoformat(), "sale_type": "customer",
            "customer": self.customer.id, "farm": self.farm.id, "batch": theirs.id,
            "birds": 100, "net_weight": "200.00", "rate": "100.00",
        })
        self.assertTrue(ser.is_valid(), ser.errors)
        self.assertEqual(ser.validated_data["batch"], mine)

    def test_one_open_batch_still_needs_no_answer(self):
        from broiler.api import BirdSaleSerializer

        only = self.batch(self.farm, "BR2607")
        ser = BirdSaleSerializer(data={
            "date": self.today.isoformat(), "sale_type": "customer",
            "customer": self.customer.id, "farm": self.farm.id,
            "birds": 100, "net_weight": "200.00", "rate": "100.00",
        })
        self.assertTrue(ser.is_valid(), ser.errors)
        self.assertEqual(ser.validated_data["batch"], only)

    # ---- what the phone is told a customer owes ----------------------------

    def test_the_phone_reads_the_same_balance_as_the_web_form(self):
        """Two endpoints, one calculation — the Customer Balance report's.

        The figure a supervisor is shown at the farm gate deciding whether to
        load a lorry must be the figure the branch judges that customer by.
        """
        from django.urls import reverse

        web = self.client.get(reverse("customer_ledger_balance"),
                              {"customer": self.customer.id})
        self.assertEqual(web.status_code, 200)

        phone = self.client.get("/api/v1/sales/customer-balance",
                                {"customer": self.customer.id})
        self.assertEqual(phone.status_code, 200)

        body = phone.json()["data"]
        self.assertEqual(body["label"], web.json()["label"])
        self.assertEqual(body["balance"], web.json()["balance"])

    def test_an_unknown_customer_answers_blank_rather_than_erroring(self):
        """The picker is cleared as often as it is set, and a form that shows
        an error box every time is a form people stop reading."""
        resp = self.client.get("/api/v1/sales/customer-balance", {"customer": ""})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["label"], "")
