"""Saving a customer whose mobile is already somebody's phone number.

`Customer.phone` is unique, appears on no form, and exists only as a mirror of
`mobile`. The mirror was assigned in save() — after full_clean() — so the one
thing that could reject it, uniqueness, was never checked against the value
actually being written. Postgres refused the insert, nothing caught the
IntegrityError, and Add Customer answered with a bare 500.

It took a placeholder to expose it. Someone typed "-" for a mobile, and a
party already on file happened to carry "-" in the phone column, left there by
an import or an older edit where the two fields could still diverge. A
placeholder is precisely the value that gets typed twice.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.models import Customer


class CustomerPhoneMirrorTests(TestCase):
    """The model rule, tested without going through the form."""

    def test_the_mobile_is_mirrored_into_the_phone_when_it_is_free(self):
        """The behaviour worth keeping: screens that read `phone` on an older
        record still find the number where they expect it."""
        c = Customer.objects.create(name="Ravi Traders", mobile="9990001111",
                                    address="Akbarpur")
        self.assertEqual(c.phone, "9990001111")

    def test_the_mirror_stands_aside_when_another_party_holds_that_number(self):
        """The fix. `phone` is nullable and carries nothing anyone typed, so
        leaving it empty costs nothing — the number is in `mobile`, which is
        what every screen and every message reads."""
        Customer.objects.create(name="Legacy Party", mobile="9990001111",
                                address="Old", phone="-")
        new = Customer.objects.create(name="New Party", mobile="-", address="New")
        self.assertIsNone(new.phone)
        self.assertEqual(new.mobile, "-")

    def test_a_phone_given_explicitly_is_never_overwritten(self):
        c = Customer.objects.create(name="Ravi Traders", mobile="9990001111",
                                    address="Akbarpur", phone="05271234567")
        self.assertEqual(c.phone, "05271234567")

    def test_saving_a_record_again_does_not_disturb_its_phone(self):
        """The mirror runs on every save, so it has to be idempotent — an edit
        must not clear a number that is already right."""
        c = Customer.objects.create(name="Ravi Traders", mobile="9990001111",
                                    address="Akbarpur")
        c.name = "Ravi Traders & Sons"
        c.save()
        c.refresh_from_db()
        self.assertEqual(c.phone, "9990001111")

    def test_more_than_one_party_may_end_up_without_a_phone(self):
        """Postgres does not collide NULLs, which is what makes standing aside
        a workable answer rather than one that fails on the second party to
        need it."""
        Customer.objects.create(name="Legacy A", mobile="9990001111",
                                address="Old", phone="-")
        Customer.objects.create(name="Legacy B", mobile="9990002222",
                                address="Old", phone="NA")
        Customer.objects.create(name="Second", mobile="-", address="B")
        Customer.objects.create(name="Third", mobile="NA", address="C")
        self.assertEqual(Customer.objects.filter(phone__isnull=True).count(), 2)

    def test_a_mobile_nobody_holds_is_still_mirrored(self):
        """Standing aside is per-value, not a blanket retreat: only the number
        that is actually taken loses its mirror."""
        Customer.objects.create(name="Legacy", mobile="9990001111",
                                address="Old", phone="-")
        taken = Customer.objects.create(name="Takes Dash", mobile="-", address="B")
        free = Customer.objects.create(name="Takes Own", mobile="9995554444", address="C")
        self.assertIsNone(taken.phone)
        self.assertEqual(free.phone, "9995554444")


class AddCustomerPageTests(TestCase):
    """The page that returned the 500."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="sales_admin", password="x", email="s@example.com")
        self.client.force_login(self.user)
        self.url = reverse("customer_add")

    def post(self, **fields):
        data = {"name": "New Party", "address": "-", "mobile": "-",
                "contact_type": "Supplier & Customer"}
        data.update(fields)
        return self.client.post(self.url, data)

    def test_a_dash_for_a_mobile_no_longer_crashes_the_page(self):
        """The report, reproduced: a party already carrying "-" as its phone,
        and someone adding another with "-" as its mobile."""
        Customer.objects.create(name="Legacy Party", mobile="9990001111",
                                address="Old", phone="-")
        response = self.post()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Customer.objects.filter(name="New Party").exists())

    def test_the_customer_keeps_what_was_actually_typed(self):
        """Not crashing is not enough — the record has to carry the value the
        person entered."""
        Customer.objects.create(name="Legacy Party", mobile="9990001111",
                                address="Old", phone="-")
        self.post()
        made = Customer.objects.get(name="New Party")
        self.assertEqual(made.mobile, "-")
        self.assertEqual(made.address, "-")

    def test_a_genuinely_duplicate_mobile_is_still_refused(self):
        """The uniqueness that means something is untouched, and it is
        refused with a message on the form rather than a 500."""
        Customer.objects.create(name="First", mobile="9990001111", address="A")
        response = self.post(mobile="9990001111")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists", status_code=200)

    def test_an_ordinary_customer_still_saves(self):
        response = self.post(mobile="9998887777", address="Akbarpur")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Customer.objects.get(name="New Party").phone, "9998887777")
