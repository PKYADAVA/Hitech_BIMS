"""In-memory provider for local development and tests.

Records every "sent" message on the instance and never performs network I/O,
so it is safe to use when ``SMS_MOCK`` is enabled or inside the test suite.
"""

import logging
import uuid

from ..constants import SmsProviderName
from ..dtos import SmsResult
from ..validators import mask_phone
from .base import SmsProvider

logger = logging.getLogger("notification.sms")


class MockSmsProvider(SmsProvider):
    """A provider that pretends to send and remembers what it was given."""

    name = SmsProviderName.MOCK

    def __init__(self, *_args, **_kwargs):
        self.outbox = []

    def send(self, phone: str, message: str, options: dict = None) -> SmsResult:
        message_id = f"mock-{uuid.uuid4().hex[:16]}"
        self.outbox.append({
            "phone": phone, "message": message,
            "message_id": message_id, "options": options or {},
        })
        logger.info(
            "SMS mock-sent recipient=%s provider=%s message_id=%s",
            mask_phone(phone), self.name, message_id,
        )
        return SmsResult.sent(
            recipient=phone,
            message_id=message_id,
            provider=self.name,
            provider_response={"mock": True},
        )
