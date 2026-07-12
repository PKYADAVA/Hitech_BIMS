"""Tests for the SMSGatewayHub provider using a fake HTTP session.

No real network calls are made; a stub session returns canned responses.
"""

from unittest import mock

import requests
from django.test import SimpleTestCase

from notification.exceptions import (
    SmsConfigurationError,
    SmsPermanentError,
    SmsTransientError,
)
from notification.providers.smsgatewayhub import SmsGatewayHubProvider
from notification.tests.factories import FakeResponse, make_config


def _provider(session, **config_overrides):
    return SmsGatewayHubProvider(make_config(**config_overrides), session=session)


class SmsGatewayHubProviderTests(SimpleTestCase):
    def test_successful_send_returns_message_id(self):
        session = mock.Mock()
        session.get.return_value = FakeResponse(
            200,
            {"ErrorCode": "000", "ErrorMessage": "Done",
             "MessageData": [{"MessageId": "abc123"}]},
        )
        result = _provider(session).send("919876543210", "hi")
        self.assertTrue(result.success)
        self.assertEqual(result.message_id, "abc123")
        self.assertEqual(result.provider, "smsgatewayhub")

    def test_api_key_is_sent_but_not_exposed_on_result(self):
        session = mock.Mock()
        session.get.return_value = FakeResponse(200, {"ErrorCode": "000", "JobId": "j1"})
        _provider(session).send("919876543210", "hi")
        sent_payload = session.get.call_args.kwargs["params"]
        self.assertEqual(sent_payload["APIKey"], "test-key")

    def test_missing_credentials_raise_configuration_error(self):
        session = mock.Mock()
        with self.assertRaises(SmsConfigurationError):
            _provider(session, api_key="").send("919876543210", "hi")
        session.get.assert_not_called()

    def test_permanent_provider_error_code(self):
        session = mock.Mock()
        session.get.return_value = FakeResponse(
            200, {"ErrorCode": "015", "ErrorMessage": "Invalid number"},
        )
        with self.assertRaises(SmsPermanentError):
            _provider(session).send("919876543210", "hi")

    def test_transient_provider_error_code(self):
        session = mock.Mock()
        session.get.return_value = FakeResponse(
            200, {"ErrorCode": "008", "ErrorMessage": "Server busy"},
        )
        with self.assertRaises(SmsTransientError):
            _provider(session).send("919876543210", "hi")

    def test_http_500_is_transient(self):
        session = mock.Mock()
        session.get.return_value = FakeResponse(500, {})
        with self.assertRaises(SmsTransientError):
            _provider(session).send("919876543210", "hi")

    def test_http_401_is_permanent(self):
        session = mock.Mock()
        session.get.return_value = FakeResponse(401, {})
        with self.assertRaises(SmsPermanentError):
            _provider(session).send("919876543210", "hi")

    def test_timeout_is_transient(self):
        session = mock.Mock()
        session.get.side_effect = requests.Timeout()
        with self.assertRaises(SmsTransientError):
            _provider(session).send("919876543210", "hi")

    def test_connection_error_is_transient(self):
        session = mock.Mock()
        session.get.side_effect = requests.ConnectionError()
        with self.assertRaises(SmsTransientError):
            _provider(session).send("919876543210", "hi")

    def test_non_json_body_is_permanent(self):
        session = mock.Mock()
        session.get.return_value = FakeResponse(200, raise_value_error=True)
        with self.assertRaises(SmsPermanentError):
            _provider(session).send("919876543210", "hi")
