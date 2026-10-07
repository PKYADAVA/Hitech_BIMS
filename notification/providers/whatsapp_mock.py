"""In-memory WhatsApp provider for local development and tests.

Records every "sent" message on the instance and never performs network I/O,
so it is safe to use when ``WHATSAPP_MOCK`` is enabled or inside the test
suite. Mirrors :class:`~notification.providers.mock.MockSmsProvider`.
"""

import logging
import uuid

from ..constants import WhatsappProviderName
from ..dtos import WhatsappResult
from ..validators import mask_phone
from .whatsapp_base import WhatsappProvider

logger = logging.getLogger("notification.whatsapp")


class MockWhatsappProvider(WhatsappProvider):
    """A provider that pretends to send and remembers what it was given."""

    name = WhatsappProviderName.MOCK

    def __init__(self, *_args, **_kwargs):
        self.outbox = []

    def send_template(self, phone: str, template_name: str, language: str,
                      components: list) -> WhatsappResult:
        message_id = f"mock-wamid-{uuid.uuid4().hex[:16]}"
        self.outbox.append({
            "phone": phone, "template_name": template_name, "language": language,
            "components": components, "message_id": message_id,
        })
        logger.info(
            "WhatsApp mock-sent recipient=%s template=%s provider=%s message_id=%s",
            mask_phone(phone), template_name, self.name, message_id,
        )
        return WhatsappResult.sent(
            recipient=phone,
            message_id=message_id,
            provider=self.name,
            provider_response={"mock": True},
        )
