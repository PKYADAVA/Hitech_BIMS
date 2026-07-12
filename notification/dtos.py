"""Structured data returned by the SMS subsystem."""

from dataclasses import dataclass, field
from typing import Optional

from .constants import SmsStatus


@dataclass(frozen=True)
class SmsResult:  # pylint: disable=too-many-instance-attributes
    """Immutable outcome of an SMS send attempt.

    Business code inspects ``success``/``status`` and never needs to parse a
    provider payload directly. ``provider_response`` is retained for logging
    and troubleshooting only.
    """

    success: bool
    status: str
    recipient: str
    message_id: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    provider: Optional[str] = None
    provider_response: Optional[dict] = field(default=None, repr=False)

    @classmethod
    def sent(cls, recipient, message_id=None, provider=None, provider_response=None):
        return cls(
            success=True,
            status=SmsStatus.SENT,
            recipient=recipient,
            message_id=message_id,
            provider=provider,
            provider_response=provider_response,
        )

    @classmethod
    def failed(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        cls, recipient, error, status=SmsStatus.FAILED, error_code=None,
        provider=None, provider_response=None,
    ):
        return cls(
            success=False,
            status=status,
            recipient=recipient,
            error=error,
            error_code=error_code,
            provider=provider,
            provider_response=provider_response,
        )
