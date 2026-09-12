"""The SMS channel actually sends, and only to the people it should.

Alerthub modelled an SMS channel from the start and refused to use it, because
LIVE_CHANNELS had no transport behind it — while the notification app had a
working gateway with messages already sent through it. These cover the join,
and the three things that make it safe to have made.
"""
from __future__ import annotations

from unittest import mock

from django.contrib.auth.models import Group, User
from django.test import TestCase

from alerthub import sms
from alerthub.constants import Channel, LIVE_CHANNELS
from hr.models import Employee


class SmsChannelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.reachable = User.objects.create_user("has_phone", password="x")
        cls.unreachable = User.objects.create_user("no_phone", password="x")
        Employee.objects.create(full_name="Has Phone", user=cls.reachable,
                                personal_contact="6387629904")
        # An employee row with no number at all — the column is numeric, so
        # absent means NULL, not an empty string.
        Employee.objects.create(full_name="No Phone", user=cls.unreachable,
                                personal_contact=None)

    def test_sms_is_a_live_channel(self):
        self.assertIn(Channel.SMS, LIVE_CHANNELS)

    def test_a_number_is_found_through_the_employee_record(self):
        self.assertEqual(sms.phone_numbers_for([self.reachable]), ["6387629904"])

    def test_a_user_with_no_number_is_skipped_not_guessed_at(self):
        self.assertEqual(sms.phone_numbers_for([self.unreachable]), [])

    def test_a_user_with_no_employee_record_is_skipped(self):
        stranger = User.objects.create_user("stranger", password="x")
        self.assertEqual(sms.phone_numbers_for([stranger]), [])

    def test_nothing_is_sent_when_nobody_has_a_number(self):
        """No gateway call at all, rather than a call that sends nowhere."""
        with mock.patch("notification.services.sms_service.SmsService") as service:
            sent = sms.send_alert_sms(mock.Mock(pk=1, title="t", message="m"),
                                      [self.unreachable])
        self.assertEqual(sent, 0)
        service.assert_not_called()

    def test_a_dead_gateway_does_not_raise(self):
        """Alerting is a side effect of business work, never a condition of it."""
        with mock.patch("notification.services.sms_service.SmsService",
                        side_effect=RuntimeError("gateway down")):
            sent = sms.send_alert_sms(mock.Mock(pk=1, title="t", message="m"),
                                      [self.reachable])
        self.assertEqual(sent, 0)

    def test_the_message_carries_the_title_and_body(self):
        seen = {}

        class FakeService:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def send_sms(self, number, text, options=None):
                seen["number"], seen["text"] = number, text
                return mock.Mock(success=True)

        with mock.patch("notification.services.sms_service.SmsService", FakeService):
            sent = sms.send_alert_sms(
                mock.Mock(pk=1, title="Negative Stock", message="Akbarpur is -40"),
                [self.reachable])

        self.assertEqual(sent, 1)
        self.assertEqual(seen["number"], "6387629904")
        self.assertIn("Negative Stock", seen["text"])
        self.assertIn("Akbarpur is -40", seen["text"])

    def test_a_recipient_who_turned_sms_off_is_dropped(self):
        from alerthub.models import NotificationPreference

        NotificationPreference.objects.create(user=self.reachable, receive_sms=False)
        rule = mock.Mock()
        self.assertNotIn(self.reachable,
                         sms.sms_recipients(rule, [self.reachable, self.unreachable]))

    def test_a_recipient_who_wants_sms_is_kept(self):
        from alerthub.models import NotificationPreference

        NotificationPreference.objects.create(user=self.reachable, receive_sms=True)
        rule = mock.Mock()
        self.assertIn(self.reachable, sms.sms_recipients(rule, [self.reachable]))
