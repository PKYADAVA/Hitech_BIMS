"""Shared test helpers for the notification app."""

from notification.conf import SmsConfig


def make_config(**overrides):
    """Build an :class:`SmsConfig` with safe test defaults.

    ``retry_backoff`` defaults to 0 so retry tests never actually sleep.
    """

    defaults = {
        "enabled": True,
        "mock": False,
        "provider": "smsgatewayhub",
        "timeout": 5,
        "max_retries": 2,
        "retry_backoff": 0.0,
        "default_country_code": "91",
        "max_length": 1000,
        "base_url": "https://sms.example.com",
        "api_key": "test-key",
        "sender_id": "HITECH",
        "route": "1",
        "channel": "2",
        "dcs": "0",
        "entity_id": "",
        "dlt_template_id": "",
    }
    defaults.update(overrides)
    return SmsConfig(**defaults)


class FakeResponse:
    """Minimal stand-in for ``requests.Response``."""

    def __init__(self, status_code=200, json_data=None, raise_value_error=False):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self._raise_value_error = raise_value_error

    def json(self):
        if self._raise_value_error:
            raise ValueError("no json")
        return self._json_data
