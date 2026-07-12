"""Tests for the SmsService orchestration: gating, validation, retries, errors."""

from django.test import SimpleTestCase

from notification.constants import SmsStatus
from notification.exceptions import SmsPermanentError, SmsTransientError
from notification.providers.base import SmsProvider
from notification.dtos import SmsResult
from notification.services.sms_service import SmsService
from notification.tests.factories import make_config


class _StubProvider(SmsProvider):
    """Configurable provider stub that records calls."""

    name = "stub"

    def __init__(self, behaviours):
        # behaviours: list of callables or exceptions applied per attempt.
        self._behaviours = list(behaviours)
        self.calls = 0
        self.last_options = None

    def send(self, phone, message, options=None):
        self.calls += 1
        self.last_options = options
        behaviour = self._behaviours[min(self.calls - 1, len(self._behaviours) - 1)]
        if isinstance(behaviour, Exception):
            raise behaviour
        return behaviour


def _ok(phone):
    return SmsResult.sent(recipient=phone, message_id="ok", provider="stub")


class SmsServiceTests(SimpleTestCase):
    def test_disabled_returns_disabled_status_without_calling_provider(self):
        provider = _StubProvider([_ok("919876543210")])
        service = SmsService(config=make_config(enabled=False), provider=provider)
        result = service.send_sms("919876543210", "hi")
        self.assertFalse(result.success)
        self.assertEqual(result.status, SmsStatus.DISABLED)
        self.assertEqual(provider.calls, 0)

    def test_invalid_phone_returns_invalid_without_calling_provider(self):
        provider = _StubProvider([_ok("x")])
        service = SmsService(config=make_config(), provider=provider)
        result = service.send_sms("not-a-number", "hi")
        self.assertEqual(result.status, SmsStatus.INVALID)
        self.assertEqual(provider.calls, 0)

    def test_successful_send(self):
        provider = _StubProvider([_ok("919876543210")])
        service = SmsService(config=make_config(), provider=provider)
        result = service.send_sms("9876543210", "hi")
        self.assertTrue(result.success)
        self.assertEqual(result.status, SmsStatus.SENT)
        self.assertEqual(provider.calls, 1)

    def test_retries_transient_then_succeeds(self):
        provider = _StubProvider([SmsTransientError("busy"), _ok("919876543210")])
        service = SmsService(config=make_config(max_retries=2), provider=provider)
        result = service.send_sms("9876543210", "hi")
        self.assertTrue(result.success)
        self.assertEqual(provider.calls, 2)

    def test_transient_exhausts_retries_and_fails(self):
        provider = _StubProvider([SmsTransientError("busy")])
        service = SmsService(config=make_config(max_retries=2), provider=provider)
        result = service.send_sms("9876543210", "hi")
        self.assertFalse(result.success)
        self.assertEqual(result.status, SmsStatus.FAILED)
        self.assertEqual(provider.calls, 3)  # 1 initial + 2 retries

    def test_permanent_error_is_not_retried(self):
        provider = _StubProvider([SmsPermanentError("bad number", error_code="015")])
        service = SmsService(config=make_config(max_retries=2), provider=provider)
        result = service.send_sms("9876543210", "hi")
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "015")
        self.assertEqual(provider.calls, 1)

    def test_unexpected_exception_is_contained(self):
        provider = _StubProvider([RuntimeError("boom")])
        service = SmsService(config=make_config(), provider=provider)
        result = service.send_sms("9876543210", "hi")
        self.assertFalse(result.success)
        self.assertIn("Unexpected error", result.error)

    def test_mock_mode_uses_mock_provider(self):
        service = SmsService(config=make_config(mock=True))
        result = service.send_sms("9876543210", "hi")
        self.assertTrue(result.success)
        self.assertEqual(result.status, SmsStatus.SENT)
        self.assertTrue(result.message_id.startswith("mock-"))
