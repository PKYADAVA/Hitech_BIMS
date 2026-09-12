"""What an error report is allowed to carry off this server.

A production 500 used to leave no trace anywhere reachable. The page said
"Server Error (500)", the console logs sit behind the platform dashboard, and
working out what had happened meant eliminating theories one at a time against
a database nobody could see. The answer, when it finally came, was a single
line of traceback.

So errors are reported now — and this ERP holds Aadhaar and PAN numbers, bank
details and salaries, which decides how. An event says where and what, never
who or with which values. These tests are the whole of that promise: the
scrubber runs on every event before it leaves the process, and what it removes
is what nobody outside this building should ever hold.

It is tested without a DSN on purpose. The part worth testing is precisely the
part that only ever runs in production, and a test that needed reporting to be
switched on would never run at all.
"""
from django.test import SimpleTestCase

from Hitech_BIMS.settings import SENTRY_SENSITIVE_HEADERS, scrub_event


def event(**request):
    return {"request": dict(request), "user": {"id": 7, "username": "akash"},
            "exception": {"values": [{"type": "IntegrityError"}]}}


class ScrubbingTests(SimpleTestCase):

    def test_the_posted_body_never_leaves(self):
        """The form body is where an Aadhaar number, a PAN, a salary and a
        bank account all live at once."""
        scrubbed = scrub_event(event(
            data={"aadhar": "1234 5678 9012", "pan_tin": "ABCDE1234F",
                  "account_no": "50100123456789"}))
        self.assertNotIn("data", scrubbed["request"])
        self.assertNotIn("1234 5678 9012", str(scrubbed))

    def test_cookies_never_leave(self):
        """A session id is not a detail about a request, it is a live
        credential — anyone holding it is signed in as that person."""
        scrubbed = scrub_event(event(cookies={"sessionid": "abc123"}))
        self.assertNotIn("cookies", scrubbed["request"])
        self.assertNotIn("abc123", str(scrubbed))

    def test_the_headers_that_authenticate_are_stripped(self):
        scrubbed = scrub_event(event(headers={
            "Authorization": "Bearer a.real.token",
            "Cookie": "sessionid=abc123",
            "X-Csrftoken": "tok",
            "X-Alert-Scan-Token": "the-scheduler-secret",
        }))
        for name, value in scrubbed["request"]["headers"].items():
            self.assertEqual(value, "[stripped]", name)
        self.assertNotIn("a.real.token", str(scrubbed))
        self.assertNotIn("the-scheduler-secret", str(scrubbed))

    def test_a_header_is_stripped_whatever_case_it_arrives_in(self):
        """WSGI and HTTP/2 disagree about capitalisation, and a check that
        only knows one spelling protects only half the time."""
        scrubbed = scrub_event(event(headers={"authorization": "Bearer x",
                                              "COOKIE": "sessionid=y"}))
        self.assertEqual(set(scrubbed["request"]["headers"].values()), {"[stripped]"})

    def test_ordinary_headers_are_kept(self):
        """Scrubbing everything would leave an event that locates nothing."""
        scrubbed = scrub_event(event(headers={"User-Agent": "Chrome",
                                              "Content-Type": "application/json"}))
        self.assertEqual(scrubbed["request"]["headers"]["User-Agent"], "Chrome")

    def test_the_query_string_never_leaves(self):
        """Ids in a query are harmless; what a report was filtered by is not,
        and the path is what locates a bug either way."""
        scrubbed = scrub_event(event(query_string="from_date=2026-01-01&mobile=9990001111"))
        self.assertNotIn("query_string", scrubbed["request"])

    def test_who_it_happened_to_never_leaves(self):
        """A stack trace and a URL are enough to find a bug. A name attached
        to it is a record of what a particular person was doing."""
        self.assertNotIn("user", scrub_event(event()))

    def test_the_url_and_the_exception_are_kept(self):
        """The point of reporting at all. Strip these and the report says
        only that something, somewhere, went wrong."""
        scrubbed = scrub_event(event(url="https://hitechfarms.co.in/customer/add/",
                                     method="POST"))
        self.assertEqual(scrubbed["request"]["url"],
                         "https://hitechfarms.co.in/customer/add/")
        self.assertEqual(scrubbed["request"]["method"], "POST")
        self.assertEqual(scrubbed["exception"]["values"][0]["type"], "IntegrityError")

    def test_an_event_with_no_request_does_not_crash_the_scrubber(self):
        """A management command or a signal raises with no request at all, and
        an exception in here would lose the report entirely."""
        self.assertEqual(scrub_event({"exception": {"values": []}}),
                         {"exception": {"values": []}})

    def test_every_sensitive_header_is_named_in_title_case(self):
        """The lookup compares `name.title()`, so an entry spelled any other
        way would silently never match."""
        for name in SENTRY_SENSITIVE_HEADERS:
            self.assertEqual(name, name.title(), name)


class ConfigurationTests(SimpleTestCase):
    """Off unless asked for, and never chatty about people when on."""

    def test_reporting_is_off_without_a_dsn(self):
        """A developer machine and a fresh checkout report nothing at all."""
        from django.conf import settings

        self.assertEqual(settings.SENTRY_DSN, "")

    def test_the_sdk_is_pinned_in_requirements(self):
        """It is imported inside a conditional, so a missing dependency would
        not show up until the first deployment that sets a DSN."""
        import io

        with io.open("requirements.txt", encoding="utf-8") as fh:
            self.assertIn("sentry-sdk", fh.read())
