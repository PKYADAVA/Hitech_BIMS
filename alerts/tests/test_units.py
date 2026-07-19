"""Pure-function unit tests: utils, diff, message templating (no DB needed)."""
from __future__ import annotations

from django.test import SimpleTestCase, TestCase

from alerts.constants import Action
from alerts.diff import compute_diff, has_changes
from alerts.handlers import _classify_update
from alerts.services import AlertEvent, _format_changes, _render_message
from alerts.utils import get_client_ip, parse_user_agent, to_jsonable, truncate


class UserAgentTests(SimpleTestCase):
    def test_chrome_on_windows(self):
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML) Chrome/120 Safari/537.36"
        browser, os_name, device = parse_user_agent(ua)
        self.assertEqual(browser, "Chrome")
        self.assertEqual(os_name, "Windows 10/11")
        self.assertEqual(device, "Desktop")

    def test_safari_iphone_is_mobile(self):
        ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Version/17 Mobile Safari/604"
        browser, os_name, device = parse_user_agent(ua)
        self.assertEqual(browser, "Safari")
        self.assertEqual(device, "Mobile")

    def test_empty_ua(self):
        self.assertEqual(parse_user_agent(""), ("", "", ""))


class ClientIPTests(SimpleTestCase):
    class _Req:
        def __init__(self, meta):
            self.META = meta

    def test_forwarded_for_wins(self):
        req = self._Req({"HTTP_X_FORWARDED_FOR": "1.2.3.4, 5.6.7.8", "REMOTE_ADDR": "9.9.9.9"})
        self.assertEqual(get_client_ip(req), "1.2.3.4")

    def test_remote_addr_fallback(self):
        req = self._Req({"REMOTE_ADDR": "9.9.9.9"})
        self.assertEqual(get_client_ip(req), "9.9.9.9")


class SerialisationTests(SimpleTestCase):
    def test_to_jsonable_handles_decimal_and_date(self):
        import datetime
        import decimal

        self.assertEqual(to_jsonable(decimal.Decimal("1.5")), "1.5")
        self.assertEqual(to_jsonable(datetime.date(2026, 1, 1)), "2026-01-01")

    def test_truncate(self):
        self.assertEqual(truncate("abc", 10), "abc")
        self.assertTrue(truncate("a" * 50, 10).endswith("…"))


class DiffTests(TestCase):
    def test_detects_changed_ignores_unchanged(self):
        from django.contrib.auth.models import User

        before = {"username": "old", "email": "a@x.com"}
        after = {"username": "new", "email": "a@x.com"}
        diff = compute_diff(User, before, after)
        self.assertIn("username", diff)
        self.assertNotIn("email", diff)
        self.assertEqual(diff["username"], {"old": "old", "new": "new", "label": "Username"})

    def test_ignore_fields_excluded(self):
        from django.contrib.auth.models import User

        diff = compute_diff(User, {"last_login": "a"}, {"last_login": "b"})
        self.assertFalse(has_changes(diff))

    def test_fk_column_reported_under_relation_name(self):
        from django.contrib.auth.models import User

        diff = compute_diff(User, {"group_id": 1}, {"group_id": 2})
        self.assertIn("group", diff)


class ClassifyUpdateTests(SimpleTestCase):
    def test_soft_delete_and_restore(self):
        self.assertEqual(
            _classify_update(None, {"is_deleted": {"old": False, "new": True}}),
            Action.SOFT_DELETE,
        )
        self.assertEqual(
            _classify_update(None, {"deleted_at": {"old": "x", "new": None}}),
            Action.RESTORE,
        )

    def test_status_change(self):
        self.assertEqual(
            _classify_update(None, {"status": {"old": "P", "new": "A"}}),
            Action.STATUS_CHANGE,
        )

    def test_plain_update(self):
        self.assertEqual(
            _classify_update(None, {"name": {"old": "a", "new": "b"}}), Action.UPDATE
        )


class TemplateTests(SimpleTestCase):
    def test_status_change_message(self):
        event = AlertEvent(
            action=Action.STATUS_CHANGE,
            model_name="sales.Order",
            verbose_model="Order",
            object_display="#7",
            changed_fields={"status": {"label": "Status", "old": "Pending", "new": "Approved"}},
        )
        _title, message = _render_message(event, "alice")
        self.assertIn("Status from 'Pending' to 'Approved'", message)
        self.assertIn("alice", message)

    def test_format_changes_empty(self):
        self.assertEqual(_format_changes({}), "")
