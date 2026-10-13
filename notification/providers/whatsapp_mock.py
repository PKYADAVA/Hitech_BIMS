"""In-memory WhatsApp provider for local development and tests.

Records every "sent" message on the instance and never performs network I/O,
so it is safe to use when ``WHATSAPP_MOCK`` is enabled or inside the test
suite. Mirrors :class:`~notification.providers.mock.MockSmsProvider`.
"""

import logging
import uuid

from ..constants import WhatsappProviderName
from ..dtos import WhatsappResult
from ..exceptions import WhatsappPermanentError
from ..validators import mask_phone
from .whatsapp_base import WhatsappProvider

logger = logging.getLogger("notification.whatsapp")


class MockWhatsappProvider(WhatsappProvider):
    """A provider that pretends to send and remembers what it was given."""

    name = WhatsappProviderName.MOCK

    def __init__(self, *_args, **_kwargs):
        self.outbox = []
        self.contacts = []
        self.groups = {"Customers": 0, "Suppliers": 0, "Farmers": 0}

    def lookup_contact(self, phone: str):
        """Mock contacts are never pre-known — always answers False (not
        found), which is a harmless, informative default for local testing."""
        return False

    def create_contact(self, name: str, phone: str, custom_fields=None, groups=None):
        """Mocked contact creation — records on this instance, mirrors the
        real duplicate-409 rule for an already-known phone number."""
        if any(c["phone"] == phone for c in self.contacts):
            return False, "This phone number is already a contact in WhatsApp (LemIn AI)."
        contact = {
            "contact_id": len(self.contacts) + 1, "name": name, "phone": phone,
            "subscribed": True, "custom_fields": custom_fields or [],
            "groups": [{"id": 0, "name": g} for g in (groups or [])],
        }
        self.contacts.append(contact)
        for g in (groups or []):
            self.groups[g] = self.groups.get(g, 0) + 1
        return True, contact

    def get_groups(self):
        """Mocked group list — derived from this instance's own recorded
        groups/contact counts."""
        return [{"id": i, "name": name, "contact_count": count}
                for i, (name, count) in enumerate(self.groups.items(), start=1)]

    def get_media_link(self, media_id: str):
        """Mocked media link — a fake but well-shaped signed URL, so the
        Download action is exercisable in mock mode without a real
        gateway or real inbound media."""
        return {
            "media_id": media_id,
            "download_url": f"https://app.leminai.com/mock-media/{media_id}",
            "expires_at": "2026-12-31T23:59:59.000000Z",
        }

    def send_template(self, phone: str, template_name: str, language: str,
                      components: list) -> WhatsappResult:
        message_id = f"mock-wamid-{uuid.uuid4().hex[:16]}"
        provider_message_id = f"mock-{uuid.uuid4().int % 10**7}"
        self.outbox.append({
            "phone": phone, "template_name": template_name, "language": language,
            "components": components, "message_id": message_id,
            "provider_message_id": provider_message_id, "status": "sent",
        })
        logger.info(
            "WhatsApp mock-sent recipient=%s template=%s provider=%s message_id=%s",
            mask_phone(phone), template_name, self.name, message_id,
        )
        return WhatsappResult.sent(
            recipient=phone,
            message_id=message_id,
            provider_message_id=provider_message_id,
            provider=self.name,
            provider_response={"mock": True},
        )

    def send_text(self, phone: str, body: str) -> WhatsappResult:
        """Mocked service-message send — stands in for the real 24h-window
        rule with a simple, deterministic check: succeeds only for a number
        that has at least one prior outbound send in this instance's
        outbox ("known"), raises the same permanent error a real
        outside-window attempt would otherwise. Lets both the success and
        the outside-window paths be exercised without a real gateway."""
        if not any(m["phone"] == phone for m in self.outbox):
            raise WhatsappPermanentError(
                "Outside the 24-hour customer service window. A template message "
                "is required to (re)start the conversation.",
                error_code="outside_session_window",
            )
        message_id = f"mock-wamid-{uuid.uuid4().hex[:16]}"
        provider_message_id = f"mock-{uuid.uuid4().int % 10**7}"
        self.outbox.append({
            "phone": phone, "template_name": "", "language": "", "components": [],
            "message_id": message_id, "provider_message_id": provider_message_id,
            "status": "sent", "body": body,
        })
        logger.info("WhatsApp mock-sent (text) recipient=%s provider=%s message_id=%s",
                   mask_phone(phone), self.name, message_id)
        return WhatsappResult.sent(
            recipient=phone, message_id=message_id, provider_message_id=provider_message_id,
            provider=self.name, provider_response={"mock": True},
        )

    def get_status(self, provider_message_id: str):
        """Mocked status check — looks up the matching outbox entry and
        always reports "delivered", so the Refresh flow is exercisable in
        mock mode without a real gateway."""
        entry = next((m for m in self.outbox if m["provider_message_id"] == provider_message_id), None)
        if entry is None:
            return None
        return "delivered", {"mock": True, "status": "delivered"}

    def get_conversation(self, phone: str, per_page: int = 50, page: int = 1, order: str = "asc"):
        """Mocked conversation — synthesizes a thread from this instance's
        own outbox (every outbound send recorded) plus one canned inbound
        reply, so the conversation view is exercisable in mock mode without
        a real gateway or real inbound traffic."""
        sent = [m for m in self.outbox if m["phone"] == phone]
        if not sent:
            return [], {"current_page": 1, "last_page": 1, "per_page": per_page, "total": 0}
        messages = [
            {
                "id": 1, "direction": "inbound", "type": "text", "status": "delivered",
                "wamid": "mock-inbound-wamid", "template_category": None,
                "payload": {"type": "text", "text": {"body": "(mock) Thanks, got it!"}},
                "error_data": None, "created_at": "2026-01-01T00:00:00.000000Z",
            },
            {
                "id": 2, "direction": "inbound", "type": "image", "status": "delivered",
                "wamid": "mock-inbound-image-wamid", "template_category": None,
                "payload": {"type": "image", "image": {
                    "id": "mock-media-id-1", "caption": "Proof of delivery",
                }},
                "error_data": None, "created_at": "2026-01-01T00:05:00.000000Z",
            },
        ]
        for i, m in enumerate(sent, start=3):
            messages.append({
                "id": i, "direction": "outbound", "type": "template", "status": "sent",
                "wamid": m["message_id"], "template_category": "UTILITY",
                "payload": {
                    "type": "template",
                    # Mirrors a real conversation entry's shape: a server-
                    # rendered "_display.body" alongside the template's own
                    # name/params — see _whatsapp_message_preview, which
                    # reads _display.body first.
                    "_display": {"body": f"(mock rendering of {m['template_name']})"},
                    "template": {"name": m["template_name"], "language": {"code": m["language"]}},
                },
                "error_data": None, "created_at": "2026-01-01T00:00:00.000000Z",
            })
        if order == "desc":
            messages = list(reversed(messages))
        return messages, {"current_page": 1, "last_page": 1, "per_page": per_page, "total": len(messages)}
