"""A form that posts the ordinary way, saved once.

Fifty-three pages in this ERP post without any script behind them, and they
include the ones that file most of its documents: General Purchase, Chicks
Purchase, Supplier Payment, the credit and debit notes, Hatchery Expense, the
employee forms. A header cannot be attached to a plain form submit, so the key
that makes a save recognisable travels as a hidden field instead.

The two things worth pinning are both about *not* recognising too much.

A rejected save is answered by rendering the page again with the message on
it — a 200, not an error. Remember that and the person corrects the field,
presses save, and is handed back the complaint about what they have just
fixed. So only a redirect is remembered: it is what these views do when the
record was actually written.

And a replay has to carry the destination. These saves answer "go and look at
the list"; a stored status without its Location would send the browser
nowhere at all.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from api.models import IdempotencyRecord
from sales.models import Customer

ADD = "/customer/add/"


class FormKeyTests(TestCase):
    """Add Customer stands in for the family — a page that posts with no
    script behind it, redirects when the record is written, and re-renders
    itself with a message when it is not."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="clerk", password="x", email="c@example.com")
        self.client.force_login(self.user)

    def save(self, key=None, name="Ravi Traders", mobile="9990001111"):
        data = {"name": name, "address": "Akbarpur", "mobile": mobile,
                "contact_type": "Supplier & Customer"}
        if key:
            data["idempotency_key"] = key
        return self.client.post(ADD, data)

    def test_the_same_form_posted_twice_files_one_record(self):
        """The report this exists for: the answer is lost, the person presses
        save again, and the browser sends the same hidden field back.

        The second response has to be the *replay* and not a refusal. One
        record would also be the count if the key were ignored and the save
        merely bounced off the unique mobile number — which is a different
        thing entirely, and leaves the person looking at an error for a record
        that was filed.
        """
        self.save(key="form-1")
        second = self.save(key="form-1")
        self.assertEqual(Customer.objects.count(), 1)
        self.assertEqual(second.status_code, 302)
        self.assertEqual(second["Idempotent-Replay"], "true")

    def test_the_duplicate_is_sent_where_the_first_one_went(self):
        """A replay has to be a redirect, not a bare status. The person is
        sitting in front of a browser waiting to be taken somewhere."""
        first = self.save(key="form-1")
        second = self.save(key="form-1")
        self.assertEqual(second.status_code, first.status_code)
        self.assertEqual(second["Location"], first["Location"])

    def test_a_second_deliberate_save_still_lands(self):
        """Every render of the form carries its own key, so two real saves are
        two records."""
        self.save(key="form-1", name="First", mobile="9990001111")
        self.save(key="form-2", name="Second", mobile="9990002222")
        self.assertEqual(Customer.objects.count(), 2)

    def test_a_form_with_no_key_behaves_exactly_as_before(self):
        """A page that has not been given the hidden field — an old cached
        copy, say — must go on working rather than half-working. Two different
        parties, because the mobile number is unique and this is about the key
        being absent, not about the record being refused."""
        self.save(name="First", mobile="9990001111")
        self.save(name="Second", mobile="9990002222")
        self.assertEqual(Customer.objects.count(), 2)
        self.assertEqual(IdempotencyRecord.objects.count(), 0)


class RejectedSaveTests(TestCase):
    """The case that makes this narrower than the header version."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="clerk2", password="x", email="c2@example.com")
        self.client.force_login(self.user)

    def post(self, key, **fields):
        data = {"name": "Ravi Traders", "address": "Akbarpur",
                "mobile": "9990001111", "contact_type": "Supplier & Customer",
                "idempotency_key": key}
        data.update(fields)
        return self.client.post(ADD, data)

    def test_a_rejected_save_is_not_remembered(self):
        """It comes back as a 200 with the form and the message on it. Storing
        that would answer the corrected resubmit with the old complaint."""
        response = self.post("form-1", name="")      # the page requires a name
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Customer.objects.count(), 0)
        self.assertEqual(IdempotencyRecord.objects.count(), 0)

    def test_the_correction_is_then_saved_under_the_same_key(self):
        """The whole point of forgetting the rejection: the person fixes the
        field and presses save, and the page they are on still carries the key
        it was rendered with."""
        self.post("form-1", name="")
        self.post("form-1")
        self.assertEqual(Customer.objects.count(), 1)
        self.assertEqual(Customer.objects.get().name, "Ravi Traders")


class KeySourceTests(TestCase):
    """Where the middleware is willing to look for a key."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="clerk3", password="x", email="c3@example.com")
        self.client.force_login(self.user)

    def test_a_json_body_is_not_rummaged_through_for_a_key(self):
        """Only a form body is read. A JSON caller says so in a header, and
        parsing every posted body looking for a field would be a cost paid on
        every write to catch a case that cannot happen."""
        import json

        from api.middleware import _key_of

        request = self.client.post(
            ADD, data=json.dumps({"idempotency_key": "sneaky"}),
            content_type="application/json").wsgi_request
        self.assertEqual(_key_of(request), ("", False))

    def test_the_header_wins_when_both_are_present(self):
        """A script that sets the header means it, and the field may be a
        leftover from the page it was rendered into."""
        from api.middleware import _key_of

        request = self.client.post(
            ADD, {"name": "X", "address": "A", "mobile": "9990009999",
                  "contact_type": "Supplier & Customer",
                  "idempotency_key": "from-the-form"},
            HTTP_IDEMPOTENCY_KEY="from-the-header").wsgi_request
        self.assertEqual(_key_of(request), ("from-the-header", False))

    def test_a_read_is_never_searched_for_a_key(self):
        from api.middleware import _key_of

        request = self.client.get(ADD).wsgi_request
        self.assertEqual(_key_of(request), ("", False))
