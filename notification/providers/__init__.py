"""SMS provider implementations.

Each provider translates a normalised ``(phone, message)`` pair into a call
against a specific gateway and returns a :class:`~notification.dtos.SmsResult`
or raises an :class:`~notification.exceptions.SmsProviderError`. Adding a new
provider (Twilio, MSG91, AWS SNS, ...) means adding one module here and
registering it in the service-layer factory — no business code changes.
"""

from .base import SmsProvider

__all__ = ["SmsProvider"]
