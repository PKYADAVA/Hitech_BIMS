"""SMSGatewayHub gateway client.

This is the only module that knows the provider's wire format. It converts a
normalised ``(phone, message)`` pair into an HTTP request, validates the
response and raises typed errors. API credentials never leave this module and
are never logged.
"""

import logging

import requests

from ..conf import SmsConfig
from ..constants import (
    GATEWAYHUB_SENDSMS_ENDPOINT,
    GATEWAYHUB_SUCCESS_CODE,
    GATEWAYHUB_TRANSIENT_ERROR_CODES,
    SmsProviderName,
)
from ..dtos import SmsResult
from ..exceptions import (
    SmsConfigurationError,
    SmsPermanentError,
    SmsTransientError,
)
from ..validators import mask_phone
from .base import SmsProvider

logger = logging.getLogger("notification.sms")

# HTTP statuses that indicate a retryable server-side condition.
_TRANSIENT_HTTP_STATUSES = frozenset({429, 500, 502, 503, 504})
# HTTP statuses that indicate bad credentials / authorisation.
_AUTH_HTTP_STATUSES = frozenset({401, 403})


class SmsGatewayHubProvider(SmsProvider):
    """Send SMS through the SMSGatewayHub JSON API."""

    name = SmsProviderName.SMSGATEWAYHUB

    def __init__(self, config: SmsConfig, session: requests.Session = None):
        self._config = config
        self._session = session or requests.Session()

    def send(self, phone: str, message: str, options: dict = None) -> SmsResult:
        self._ensure_configured()
        url = f"{self._config.base_url}{GATEWAYHUB_SENDSMS_ENDPOINT}"
        params = self._build_payload(phone, message, options or {})

        try:
            response = self._session.get(url, params=params, timeout=self._config.timeout)
        except requests.Timeout as exc:
            raise SmsTransientError(f"SMS request timed out after "
                                    f"{self._config.timeout}s.") from exc
        except requests.RequestException as exc:
            raise SmsTransientError("Network error contacting SMS provider.") from exc

        return self._handle_response(phone, response)

    def _ensure_configured(self):
        missing = [
            name for name, value in (
                ("SMS_GATEWAYHUB_API_KEY", self._config.api_key),
                ("SMS_GATEWAYHUB_SENDER_ID", self._config.sender_id),
            ) if not value
        ]
        if missing:
            raise SmsConfigurationError(
                "Missing SMS configuration: " + ", ".join(missing)
            )

    def _build_payload(self, phone, message, options):
        payload = {
            "APIKey": self._config.api_key,
            "senderid": self._config.sender_id,
            "channel": self._config.channel,
            "DCS": self._config.dcs,
            "flashsms": 0,
            "number": phone,
            "text": message,
            "route": self._config.route,
        }
        # DLT fields are mandatory for Indian traffic when provisioned. A
        # per-message template ID (from the SmsTemplate being sent) wins over
        # the global default, since each DLT template has its own ID.
        if self._config.entity_id:
            payload["EntityId"] = self._config.entity_id
        dlt_template_id = options.get("dlt_template_id") or self._config.dlt_template_id
        if dlt_template_id:
            payload["dlttemplateid"] = dlt_template_id
        return payload

    def _handle_response(self, phone, response):
        status_code = response.status_code
        if status_code in _AUTH_HTTP_STATUSES:
            raise SmsPermanentError(
                "SMS provider rejected credentials.", error_code=str(status_code)
            )
        if status_code in _TRANSIENT_HTTP_STATUSES:
            raise SmsTransientError(
                f"SMS provider returned HTTP {status_code}.", error_code=str(status_code)
            )
        if status_code >= 400:
            raise SmsPermanentError(
                f"SMS provider returned HTTP {status_code}.", error_code=str(status_code)
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise SmsPermanentError("SMS provider returned a non-JSON response.") from exc

        return self._interpret_body(phone, body)

    def _interpret_body(self, phone, body):
        error_code = str(body.get("ErrorCode", "")).strip()
        error_message = body.get("ErrorMessage", "Unknown provider response")

        if error_code == GATEWAYHUB_SUCCESS_CODE:
            message_id = self._extract_message_id(body)
            logger.info(
                "SMS sent recipient=%s provider=%s message_id=%s code=%s",
                mask_phone(phone), self.name, message_id, error_code,
            )
            return SmsResult.sent(
                recipient=phone,
                message_id=message_id,
                provider=self.name,
                provider_response=body,
            )

        if error_code in GATEWAYHUB_TRANSIENT_ERROR_CODES:
            raise SmsTransientError(error_message, error_code=error_code, provider_response=body)
        raise SmsPermanentError(error_message, error_code=error_code, provider_response=body)

    @staticmethod
    def _extract_message_id(body):
        data = body.get("MessageData") or body.get("Data")
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict):
                return first.get("MessageId") or first.get("MessageID")
        return body.get("JobId")
