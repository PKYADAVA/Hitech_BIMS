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
    LEMINAI_CONVERSATION_ENDPOINT,
    LEMINAI_CREATE_CONTACT_ENDPOINT,
    LEMINAI_GROUPS_ENDPOINT,
    LEMINAI_MEDIA_LINK_ENDPOINT,
    LEMINAI_MESSAGE_STATUS_ENDPOINT,
    LEMINAI_SEND_SERVICE_MESSAGE_ENDPOINT,
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

    def send_text(self, phone: str, body: str) -> WhatsappResult:
        """Send a free-form text message via POST /api/v1/messages/service.

        Only succeeds inside the contact's 24-hour service window — outside
        it, Meta/LemIn AI return an error this client surfaces as a
        :class:`WhatsappPermanentError` (not retryable; waiting longer never
        helps, a template send is the only way to restart the conversation).
        """
        self._ensure_configured()
        url = f"{self._config.base_url}{LEMINAI_SEND_SERVICE_MESSAGE_ENDPOINT}"
        payload = {"to": phone, "type": "text", "text": {"body": body}}

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

    def get_status(self, provider_message_id: str):
        """Fetch the current delivery status for a previously sent message.

        ``provider_message_id`` is LemIn AI's own numeric id (returned as
        ``data.message_id`` on send, distinct from the WAMID) — the docs for
        GET /api/v1/messages/{id} say the id is "the message_id returned
        from the Send Template Message API".

        Returns the raw status string (e.g. "sent", "delivered", "read",
        "failed") on a clean 200, or ``None`` if the check itself couldn't
        be completed — never raises, since this is a best-effort refresh
        and must not block or break the page that triggered it.
        """
        try:
            self._ensure_configured()
        except WhatsappConfigurationError:
            return None

        url = f"{self._config.base_url}{LEMINAI_MESSAGE_STATUS_ENDPOINT.format(id=provider_message_id)}"
        try:
            response = self._session.get(
                url,
                headers={"Authorization": f"Bearer {self._config.api_key}"},
                timeout=self._config.timeout,
            )
        except requests.RequestException:
            logger.warning("WhatsApp status check failed (network) id=%s", provider_message_id)
            return None

        if response.status_code != 200:
            logger.warning("WhatsApp status check unexpected status=%s id=%s",
                           response.status_code, provider_message_id)
            return None
        try:
            body = response.json()
        except ValueError:
            return None

        data = body.get("data") if isinstance(body, dict) else None
        status = (data or body or {}).get("status") if isinstance(body, dict) else None
        return status, (data or body if isinstance(body, dict) else None)

    def get_conversation(self, phone: str, per_page: int = 50, page: int = 1, order: str = "asc"):
        """Fetch the message thread with ``phone`` — both inbound and
        outbound — from GET /api/v1/messages.

        Returns ``(messages, meta)`` where ``messages`` is the raw ``data``
        list (each entry's own shape varies by message ``type`` — this
        client doesn't normalise it, since the page rendering it already
        has to branch on type to display anything meaningful) and ``meta``
        is the pagination block, or ``None`` if the call couldn't be
        completed (network error, bad credentials, no conversation yet,
        contact not found) — never raises, since a conversation view must
        degrade to "nothing to show" rather than break the page.
        """
        try:
            self._ensure_configured()
        except WhatsappConfigurationError:
            return None

        url = f"{self._config.base_url}{LEMINAI_CONVERSATION_ENDPOINT}"
        try:
            response = self._session.get(
                url,
                params={"phone": phone, "per_page": per_page, "page": page, "order": order},
                headers={"Authorization": f"Bearer {self._config.api_key}"},
                timeout=self._config.timeout,
            )
        except requests.RequestException:
            logger.warning("WhatsApp conversation fetch failed (network) recipient=%s", mask_phone(phone))
            return None

        if response.status_code == 404:
            # Either the contact doesn't exist, or they exist but have no
            # conversation yet — both are "nothing to show", not an error.
            return [], {"current_page": 1, "last_page": 1, "per_page": per_page, "total": 0}
        if response.status_code != 200:
            logger.warning("WhatsApp conversation fetch unexpected status=%s recipient=%s",
                           response.status_code, mask_phone(phone))
            return None
        try:
            body = response.json()
        except ValueError:
            return None
        if not isinstance(body, dict):
            return None
        return body.get("data") or [], body.get("meta") or {}

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

    def create_contact(self, name: str, phone: str, custom_fields=None, groups=None):
        """Create (or restore/refresh) a LemIn AI contact.

        Per the docs: a previously-deleted contact with this phone number is
        silently restored and refreshed rather than erroring; a currently
        active contact with this phone number is rejected with HTTP 409.
        ``groups`` is a list of plain group names — unrecognised ones are
        created automatically, no IDs needed.

        Returns ``(success, data_or_error)``: on success, ``data_or_error``
        is the created contact's data dict; on failure (duplicate, bad
        request, network, config), it's a human-readable error string.
        Never raises — contact sync is an auxiliary action and must not
        crash the page that triggered it.
        """
        try:
            self._ensure_configured()
        except WhatsappConfigurationError as exc:
            return False, str(exc)

        url = f"{self._config.base_url}{LEMINAI_CREATE_CONTACT_ENDPOINT}"
        payload = {"name": name, "phone": phone}
        if custom_fields:
            payload["custom_fields"] = custom_fields
        if groups:
            payload["groups"] = groups

        try:
            response = self._session.post(
                url, json=payload,
                headers={"Authorization": f"Bearer {self._config.api_key}"},
                timeout=self._config.timeout,
            )
        except requests.RequestException:
            logger.warning("WhatsApp create-contact failed (network) recipient=%s", mask_phone(phone))
            return False, "Network error contacting WhatsApp provider."

        try:
            body = response.json()
        except ValueError:
            body = {}

        if response.status_code == 201:
            return True, body.get("data") or body
        if response.status_code == 409:
            return False, "This phone number is already a contact in WhatsApp (LemIn AI)."
        message = body.get("message") or body.get("error") or f"HTTP {response.status_code}"
        logger.warning("WhatsApp create-contact failed status=%s recipient=%s message=%s",
                       response.status_code, mask_phone(phone), message)
        return False, str(message)

    def get_groups(self):
        """Return the list of contact groups for this account, or ``None``
        if the call couldn't be completed. Never raises."""
        try:
            self._ensure_configured()
        except WhatsappConfigurationError:
            return None

        url = f"{self._config.base_url}{LEMINAI_GROUPS_ENDPOINT}"
        try:
            response = self._session.get(
                url,
                headers={"Authorization": f"Bearer {self._config.api_key}"},
                timeout=self._config.timeout,
            )
        except requests.RequestException:
            logger.warning("WhatsApp get-groups failed (network)")
            return None
        if response.status_code != 200:
            logger.warning("WhatsApp get-groups unexpected status=%s", response.status_code)
            return None
        try:
            body = response.json()
        except ValueError:
            return None
        return body.get("data") or []

    def get_media_link(self, media_id: str):
        """Return a temporary (30-day) signed download URL for an inbound
        WhatsApp media file, given the ``media_id`` from a conversation
        entry's ``payload`` — or ``None`` if the call couldn't be completed.
        The returned URL needs no API key (docs: "does not require the API
        key"), so it's safe to hand to a template for a plain client-side
        link. Never raises."""
        try:
            self._ensure_configured()
        except WhatsappConfigurationError:
            return None

        url = f"{self._config.base_url}{LEMINAI_MEDIA_LINK_ENDPOINT.format(mediaId=media_id)}"
        try:
            response = self._session.get(
                url,
                headers={"Authorization": f"Bearer {self._config.api_key}", "Accept": "application/json"},
                timeout=self._config.timeout,
            )
        except requests.RequestException:
            logger.warning("WhatsApp get-media-link failed (network) media_id=%s", media_id)
            return None
        if response.status_code != 200:
            logger.warning("WhatsApp get-media-link unexpected status=%s media_id=%s",
                           response.status_code, media_id)
            return None
        try:
            body = response.json()
        except ValueError:
            return None
        return body.get("data") or {}

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

        wamid, provider_message_id = self._extract_message_ids(body)
        logger.info(
            "WhatsApp sent recipient=%s provider=%s message_id=%s provider_message_id=%s",
            mask_phone(phone), self.name, wamid, provider_message_id,
        )
        return WhatsappResult.sent(
            recipient=phone,
            message_id=wamid,
            provider_message_id=provider_message_id,
            provider=self.name,
            provider_response=body,
        )

    @staticmethod
    def _extract_message_ids(body):
        """Return ``(wamid, provider_message_id)`` from a send response.

        These are two different identifiers LemIn AI hands back: the WAMID
        (the ``wamid.HBg...`` string Meta itself assigns, useful for display
        and matching against webhooks) and LemIn's own numeric ``message_id``
        (what GET /api/v1/messages/{id} — status polling — actually expects).
        A real response observed in testing nests both under ``data`` with
        no top-level fallback, but earlier integration planning noted the
        docs don't pin the exact shape, so both levels are checked.
        """
        if not isinstance(body, dict):
            return None, None
        containers = [body]
        data = body.get("data")
        if isinstance(data, dict):
            containers.append(data)
        wamid = None
        provider_message_id = None
        for container in containers:
            wamid = wamid or container.get("wamid") or container.get("id")
            provider_message_id = provider_message_id or container.get("message_id")
        return wamid, provider_message_id
