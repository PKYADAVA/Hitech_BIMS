"""Saving a customer whose mobile is already somebody's phone number.

`Customer.phone` appears on no form and exists only as a mirror of `mobile`,
filled in by save(). It used to carry a unique index as well, and because the
mirror is assigned after full_clean(), nothing ever validated the value being
written: Postgres refused the insert, the IntegrityError went uncaught, and Add
Customer answered with a bare 500.

It took a placeholder to expose it. Someone typed "-" for a mobile while a
party already on file carried "-" in its phone column, left there by an import
or an older edit where the two fields could diverge. A placeholder is precisely
the value that gets typed twice.

The index is gone now (0017): a derived column that nobody types added no rule
worth keeping, and `mobile` carries the uniqueness that means something. These
tests describe what is left — a mirror that simply works, and a duplicate
mobile that is still refused on the form.
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

    def test_a_mobile_already_held_as_someone_elses_phone_is_still_mirrored(self):
        """The case that used to be a 500. Two parties may now share a phone
        value, which costs nothing: the number that identifies a party is its
        mobile, and that is still unique."""
        Customer.objects.create(name="Legacy Party", mobile="9990001111",
                                address="Old", phone="-")
        new = Customer.objects.create(name="New Party", mobile="-", address="New")
        self.assertEqual(new.mobile, "-")
        self.assertEqual(new.phone, "-")
        self.assertEqual(Customer.objects.filter(phone="-").count(), 2)

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

    def test_every_party_ends_up_with_the_number_it_was_given(self):
        """The point of removing the index rather than working around it: no
        record is left with an empty phone for a reason that has nothing to do
        with the party, which is what the Customer List report shows."""
        Customer.objects.create(name="Legacy A", mobile="9990001111",
                                address="Old", phone="-")
        Customer.objects.create(name="Second", mobile="-", address="B")
        Customer.objects.create(name="Third", mobile="NA", address="C")
        self.assertFalse(Customer.objects.filter(phone__isnull=True).exists())


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
        self.assertEqual(made.phone, "-")

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
