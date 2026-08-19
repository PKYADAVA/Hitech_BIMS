"""The scan's way in from an outside scheduler.

The URL sits in a public repository, so the token is the only thing protecting
it and these tests are about that rather than about the scan, which has its own
tests. The endpoint must be inert until it is deliberately configured, must
tell a prober nothing, and must never do work on a GET.
"""
from django.test import TestCase, override_settings
from django.urls import reverse

TOKEN = "a-long-random-token-value-0123456789"
HEADER = "HTTP_X_ALERT_SCAN_TOKEN"


class TriggerAuthTests(TestCase):
    def setUp(self):
        self.url = reverse("alerthub:run_alert_scan")

    # ---- off unless configured ---------------------------------------------

    @override_settings(ALERT_SCAN_TOKEN="")
    def test_with_no_token_configured_the_endpoint_does_not_exist(self):
        """A deployment that was never given a token never opted in, and must
        not be scannable by anyone who guesses the path."""
        self.assertEqual(self.client.post(self.url).status_code, 404)

    @override_settings(ALERT_SCAN_TOKEN="   ")
    def test_a_whitespace_token_counts_as_unset(self):
        """An environment variable set to empty is a misconfiguration, not a
        password that happens to be blank."""
        self.assertEqual(
            self.client.post(self.url, **{HEADER: "   "}).status_code, 404)

    # ---- what a prober learns ----------------------------------------------

    @override_settings(ALERT_SCAN_TOKEN=TOKEN)
    def test_a_wrong_token_is_refused_exactly_like_a_wrong_url(self):
        """404 rather than 403: probing must not distinguish "no such
        endpoint" from "right endpoint, wrong key"."""
        response = self.client.post(self.url, **{HEADER: "not-the-token"})
        self.assertEqual(response.status_code, 404)

    @override_settings(ALERT_SCAN_TOKEN=TOKEN)
    def test_a_missing_token_is_refused(self):
        self.assertEqual(self.client.post(self.url).status_code, 404)

    @override_settings(ALERT_SCAN_TOKEN=TOKEN)
    def test_a_prefix_of_the_token_is_not_enough(self):
        """The comparison is constant-time, so a right first byte buys
        nothing; this is the behaviour that guarantees."""
        self.assertEqual(
            self.client.post(self.url, **{HEADER: TOKEN[:-1]}).status_code, 404)
        self.assertEqual(
            self.client.post(self.url, **{HEADER: TOKEN + "x"}).status_code, 404)

    # ---- what it will and will not do --------------------------------------

    @override_settings(ALERT_SCAN_TOKEN=TOKEN)
    def test_a_get_never_scans_even_with_the_right_token(self):
        """It does work, so a crawler following a link must not set it off."""
        response = self.client.get(self.url, **{HEADER: TOKEN})
        self.assertEqual(response.status_code, 405)

    @override_settings(ALERT_SCAN_TOKEN=TOKEN)
    def test_the_right_token_runs_a_scan_and_reports_what_happened(self):
        """The scheduler's log should say what the run did without anyone
        having to open the app."""
        response = self.client.post(self.url, **{HEADER: TOKEN})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertIn("rule(s)", body["summary"])
        for key in ("rules_run", "alerts", "failed", "skipped_no_detector"):
            self.assertIn(key, body)

    @override_settings(ALERT_SCAN_TOKEN=TOKEN)
    def test_it_does_not_need_a_csrf_token(self):
        """There is no session and no user — a machine with a shared secret
        cannot have fetched a CSRF cookie first."""
        from django.test import Client

        strict = Client(enforce_csrf_checks=True)
        self.assertEqual(
            strict.post(self.url, **{HEADER: TOKEN}).status_code, 200)

    @override_settings(ALERT_SCAN_TOKEN=TOKEN)
    def test_it_does_not_require_a_logged_in_user(self):
        """Nobody is behind this request; requiring a login would make it
        unusable by the only thing that will ever call it."""
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(
            self.client.post(self.url, **{HEADER: TOKEN}).status_code, 200)
