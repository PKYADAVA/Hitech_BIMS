"""The scheduler's way in to the idempotency cleanup.

The endpoint deletes rows, is named in a public repository, and has no user
behind it — so the token is the whole of its protection, and these tests are
mostly about that. The rest is the window: a key young enough to still be
retried must survive, because deleting it turns a duplicate into a second save.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from api.models import IdempotencyRecord

URL = "/tasks/purge-idempotency/"
TOKEN = "a-long-random-string"


class PurgeEndpointTestCase(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="scheduler", password="x", email="s@example.com")

    def key(self, name, age_days):
        record = IdempotencyRecord.objects.create(
            key=name, user=self.user, method="POST", path="/x/", status_code=200)
        # created_at is auto_now_add, so it has to be moved after the fact.
        IdempotencyRecord.objects.filter(pk=record.pk).update(
            created_at=timezone.now() - timedelta(days=age_days))
        return record

    def post(self, token=TOKEN, query=""):
        headers = {"HTTP_X_ALERT_SCAN_TOKEN": token} if token else {}
        return self.client.post(URL + query, **headers)


@override_settings(ALERT_SCAN_TOKEN=TOKEN)
class PurgeTests(PurgeEndpointTestCase):

    def test_keys_past_the_window_are_deleted(self):
        self.key("old", 30)
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["deleted"], 1)
        self.assertEqual(IdempotencyRecord.objects.count(), 0)

    def test_a_key_young_enough_to_be_retried_survives(self):
        """The one that matters. Delete it and the next duplicate is no longer
        recognised — it becomes a second save."""
        self.key("fresh", 1)
        self.post()
        self.assertEqual(IdempotencyRecord.objects.count(), 1)

    def test_the_window_can_be_widened(self):
        self.key("ten-days", 10)
        self.post(query="?days=30")
        self.assertEqual(IdempotencyRecord.objects.count(), 1)

    def test_a_nonsense_window_falls_back_rather_than_failing(self):
        """A scheduler that mistypes a number should still get its cleanup,
        and too generous a window only costs rows that live a little longer."""
        self.key("old", 30)
        response = self.post(query="?days=not-a-number")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["days"], 7)

    def test_zero_days_cannot_wipe_keys_still_in_use(self):
        """Guarding the obvious mistake: ?days=0 would take every key,
        including ones a client is retrying against right now."""
        self.key("fresh", 0)
        self.post(query="?days=0")
        self.assertEqual(IdempotencyRecord.objects.count(), 1)

    def test_it_reports_what_it_did(self):
        """So the scheduler's own log answers "is this working?" without
        anyone opening the app."""
        self.key("old", 30)
        self.key("fresh", 1)
        body = self.post().json()
        self.assertEqual((body["deleted"], body["remaining"]), (1, 1))

    def test_a_get_does_nothing(self):
        """It deletes things; a crawler following a link must not set it off."""
        self.key("old", 30)
        self.assertEqual(self.client.get(URL).status_code, 405)
        self.assertEqual(IdempotencyRecord.objects.count(), 1)


@override_settings(ALERT_SCAN_TOKEN=TOKEN)
class TokenTests(PurgeEndpointTestCase):

    def test_a_wrong_token_is_refused(self):
        self.key("old", 30)
        self.assertEqual(self.post(token="wrong").status_code, 404)
        self.assertEqual(IdempotencyRecord.objects.count(), 1)

    def test_no_token_is_refused(self):
        self.key("old", 30)
        self.assertEqual(self.post(token=None).status_code, 404)

    def test_a_wrong_token_looks_exactly_like_a_wrong_url(self):
        """404 rather than 403, so probing cannot tell "no such endpoint" from
        "right endpoint, wrong key"."""
        self.assertEqual(self.post(token="wrong").status_code, 404)
        self.assertEqual(self.client.post("/tasks/no-such-task/").status_code, 404)


class UnconfiguredTests(PurgeEndpointTestCase):
    """A deployment that was never given a token never asked for a scheduler."""

    @override_settings(ALERT_SCAN_TOKEN="")
    def test_the_endpoint_is_off_when_no_token_is_set(self):
        self.key("old", 30)
        self.assertEqual(self.post().status_code, 404)
        self.assertEqual(IdempotencyRecord.objects.count(), 1)

    @override_settings(ALERT_SCAN_TOKEN="")
    def test_an_empty_token_cannot_be_matched_by_sending_nothing(self):
        """The trap in a naive comparison: unset on the server and unset in the
        request would otherwise be equal."""
        self.assertEqual(self.post(token="").status_code, 404)
