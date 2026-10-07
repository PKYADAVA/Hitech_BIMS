"""LemIn AI WhatsApp Business API wrapper client.

This is the only module that knows the provider's wire format. It converts a
normalised (phone, template_name, language, components) call into an HTTP
request, validates the response and raises typed errors. API credentials
never leave this module and are never logged.

Response shape note: the LemIn AI docs for POST /api/v1/messages/template
promise a synchronous WhatsApp message ID (WAMID) on success, but do not
spell out the exact JSON field name. This client checks a few plausible
keys (``id``, ``wamid``, ``message_id``, nested under ``data``) and falls
back to storing the whole body as the "message id" is absent — this was
flagged in planning as something to confirm against a real send and adjust
once the actual response is seen.
"""

import logging

import requests

from ..conf import WhatsappConfig
from ..constants import (
    LEMINAI_CONTACT_LOOKUP_ENDPOINT,
    LEMINAI_SEND_TEMPLATE_ENDPOINT,
    WhatsappProviderName,
)
from ..dtos import WhatsappResult
from ..exceptions import (
    WhatsappConfigurationError,
    WhatsappPermanentError,
    WhatsappTransientError,
)
from ..validators import mask_phone
from .whatsapp_base import WhatsappProvider

logger = logging.getLogger("notification.whatsapp")

# HTTP statuses that indicate a retryable server-side condition.
_TRANSIENT_HTTP_STATUSES = frozenset({429, 500, 502, 503, 504})
# HTTP statuses that indicate bad credentials / authorisation.
_AUTH_HTTP_STATUSES = frozenset({401, 403})


class LeminaiProvider(WhatsappProvider):
    """Send WhatsApp template messages through the LemIn AI wrapper API."""

    name = WhatsappProviderName.LEMINAI

    def __init__(self, config: WhatsappConfig, session: requests.Session = None):
        self._config = config
        # Only a session we created is ours to close; an injected one (tests)
        # remains the caller's responsibility.
        self._owns_session = session is None
        self._session = session or requests.Session()

    def close(self) -> None:
        """Close the HTTP session (and its connection pool) if we own it."""
        if self._owns_session and self._session is not None:
            self._session.close()

    def send_template(self, phone: str, template_name: str, language: str,
                      components: list) -> WhatsappResult:
        self._ensure_configured()
        url = f"{self._config.base_url}{LEMINAI_SEND_TEMPLATE_ENDPOINT}"
        payload = {"to": phone, "template_name": template_name, "language": language}
        if components:
            payload["components"] = components

        try:
            response = self._session.post(
                url, json=payload,
                headers={"Authorization": f"Bearer {self._config.api_key}"},
                timeout=self._config.timeout,
            )
        except requests.Timeout as exc:
            raise WhatsappTransientError(
                f"WhatsApp request timed out after {self._config.timeout}s."
            ) from exc
        except requests.RequestException as exc:
            raise WhatsappTransientError("Network error contacting WhatsApp provider.") from exc

        return self._handle_response(phone, response)

    def lookup_contact(self, phone: str):
        """Return whether ``phone`` is already a saved LemIn AI contact.

        Not a real WhatsApp-presence check (see WhatsappProvider.lookup_contact
        for why) — GET /api/v1/contacts/lookup only knows about numbers this
        account has already messaged or saved. Returns ``True``/``False`` on
        a clean answer, ``None`` if the check itself couldn't be completed
        (network error, bad credentials, unexpected response) — never raises,
        since this is an advisory check that must not block a send.
        """
        try:
            self._ensure_configured()
        except WhatsappConfigurationError:
            return None

        url = f"{self._config.base_url}{LEMINAI_CONTACT_LOOKUP_ENDPOINT}"
        try:
            response = self._session.get(
                url, params={"phone": phone},
                headers={"Authorization": f"Bearer {self._config.api_key}"},
                timeout=self._config.timeout,
            )
        except requests.RequestException:
            logger.warning("WhatsApp contact lookup failed (network) recipient=%s", mask_phone(phone))
            return None

        if response.status_code == 404:
            return False
        if response.status_code == 200:
            return True
        logger.warning(
            "WhatsApp contact lookup unexpected status=%s recipient=%s",
            response.status_code, mask_phone(phone),
        )
        return None

    def _ensure_configured(self):
        if not self._config.api_key:
            raise WhatsappConfigurationError("Missing WhatsApp configuration: WHATSAPP_API_KEY")

    def _handle_response(self, phone, response):
        status_code = response.status_code
        if status_code in _AUTH_HTTP_STATUSES:
            raise WhatsappPermanentError(
                "WhatsApp provider rejected credentials.", error_code=str(status_code)
            )
        if status_code in _TRANSIENT_HTTP_STATUSES:
            raise WhatsappTransientError(
                f"WhatsApp provider returned HTTP {status_code}.", error_code=str(status_code)
            )

        try:
            body = response.json()
        except ValueError as exc:
            if status_code >= 400:
                raise WhatsappPermanentError(
                    f"WhatsApp provider returned HTTP {status_code}.",
                    error_code=str(status_code),
                ) from exc
            raise WhatsappPermanentError("WhatsApp provider returned a non-JSON response.") from exc

        if status_code >= 400:
            message = body.get("message") or body.get("error") or f"HTTP {status_code}"
            raise WhatsappPermanentError(
                str(message), error_code=str(status_code), provider_response=body
            )

        message_id = self._extract_message_id(body)
        logger.info(
            "WhatsApp sent recipient=%s provider=%s message_id=%s",
            mask_phone(phone), self.name, message_id,
        )
        return WhatsappResult.sent(
            recipient=phone,
            message_id=message_id,
            provider=self.name,
            provider_response=body,
        )

    @staticmethod
    def _extract_message_id(body):
        if not isinstance(body, dict):
            return None
        for key in ("id", "wamid", "message_id"):
            if body.get(key):
                return body[key]
        data = body.get("data")
        if isinstance(data, dict):
            for key in ("id", "wamid", "message_id"):
                if data.get(key):
                    return data[key]
        return None
