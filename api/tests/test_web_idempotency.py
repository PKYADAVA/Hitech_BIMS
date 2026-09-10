"""A save the ERP's own pages ask to be performed once.

Holding the button stops the second press. It does nothing about the presses
that never reach the button — a refresh and "resend", a request that timed out
on the browser's side after the server had already filed it — and those arrive
as second, genuine requests.

So the ERP's scripted saves now carry the same Idempotency-Key header the
phone's outbox uses, answered by the same middleware. These tests are about
the half of that which is new: that a browser session, not just a bearer
token, is recognised, and that a replay comes back as what it was.
"""
import json

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from api.models import IdempotencyRecord
from broiler.models import Region

WEB_PATH = "/create-region/"


class WebIdempotencyTests(TestCase):
    """Region is the subject because it is the plainest write the ERP has: one
    required field, no stock movement, nothing to set up."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_superuser(
            username="web_user", password="x", email="w@example.com")
        self.client.force_login(self.user)

    def save(self, key=None, name="East"):
        """Posted the way the page posts it — form-encoded, which is what the
        ERP's own endpoints read."""
        headers = {"HTTP_IDEMPOTENCY_KEY": key} if key else {}
        return self.client.post(WEB_PATH, data={"description": name}, **headers)

    def test_a_keyed_save_is_performed_once(self):
        """The whole point: the same key twice files one region."""
        first = self.save(key="press-1")
        second = self.save(key="press-1")
        self.assertEqual(first.status_code, second.status_code)
        self.assertEqual(Region.objects.count(), 1)

    def test_the_second_answer_is_the_first_one(self):
        """A duplicate has to look like success, not like an error. The page
        that sent it is waiting for the id it would have got."""
        first = self.save(key="press-1")
        second = self.save(key="press-1")
        self.assertEqual(second.content, first.content)
        self.assertEqual(second["Idempotent-Replay"], "true")

    def test_a_replay_comes_back_as_what_it_was(self):
        """The stored body is JSON and has to be served as JSON — the script
        waiting on it will try to parse it."""
        self.save(key="press-1")
        replay = self.save(key="press-1")
        self.assertIn("application/json", replay["Content-Type"])
        self.assertIsInstance(json.loads(replay.content), dict)

    def test_a_different_key_is_a_different_save(self):
        """Two deliberate saves from the same page must both land, which is
        why the key is retired once its answer arrives."""
        self.save(key="press-1", name="East")
        self.save(key="press-2", name="West")
        self.assertEqual(Region.objects.count(), 2)

    def test_a_save_with_no_key_is_untouched(self):
        """Plain form posts cannot carry a header, so they must go on working
        exactly as before rather than being half-covered."""
        self.save()
        self.save()
        self.assertEqual(Region.objects.count(), 2)
        self.assertEqual(IdempotencyRecord.objects.count(), 0)

    def test_a_key_is_recorded_against_the_person_who_used_it(self):
        """Scoped to the user, so one person's stored answer can never be
        served to another."""
        self.save(key="press-1")
        record = IdempotencyRecord.objects.get()
        self.assertEqual(record.user, self.user)
        self.assertEqual(record.path, WEB_PATH)

    def test_one_persons_key_is_not_another_persons(self):
        other = get_user_model().objects.create_superuser(
            username="web_user_2", password="x", email="w2@example.com")
        self.save(key="press-1", name="East")
        self.client.force_login(other)
        self.save(key="press-1", name="West")
        self.assertEqual(Region.objects.count(), 2)

    def test_a_signed_out_visitor_is_not_given_a_replay(self):
        """Nothing keyed should be recorded for a request that has no one
        behind it — the view will refuse it anyway."""
        self.client.logout()
        self.save(key="press-1")
        self.assertEqual(IdempotencyRecord.objects.count(), 0)


class ReplayContentTypeTests(TestCase):
    """What a stored answer is served as, read back off the body."""

    def test_json_is_recognised(self):
        from api.middleware import _content_type_of

        self.assertIn("application/json", _content_type_of('{"id": 4}'))
        self.assertIn("application/json", _content_type_of('  [1, 2]'))

    def test_html_is_not_served_as_json(self):
        """A caller that one day answers in HTML gets it back as HTML rather
        than as JSON it never sent."""
        from api.middleware import _content_type_of

        self.assertIn("text/html", _content_type_of("<html><body>Saved"))

    def test_an_empty_body_does_not_claim_to_be_json(self):
        from api.middleware import _content_type_of

        self.assertIn("text/plain", _content_type_of(""))
        self.assertIn("text/plain", _content_type_of(None))
