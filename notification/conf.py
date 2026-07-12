"""Centralised access to SMS configuration.

All settings are read from ``django.conf.settings`` in exactly one place so the
rest of the subsystem never touches Django settings directly. This keeps the
provider and service layers easy to test with overridden configuration.
"""

from dataclasses import dataclass

from django.conf import settings

from .constants import SmsProviderName


@dataclass(frozen=True)
class SmsConfig:  # pylint: disable=too-many-instance-attributes
    """Resolved, validated SMS configuration."""

    enabled: bool
    mock: bool
    provider: str
    timeout: int
    max_retries: int
    retry_backoff: float
    default_country_code: str
    max_length: int
    # SMSGatewayHub credentials/routing.
    base_url: str
    api_key: str
    sender_id: str
    route: str
    channel: str
    dcs: str
    entity_id: str
    dlt_template_id: str


def load_config() -> SmsConfig:
    """Build an :class:`SmsConfig` from the current Django settings."""

    return SmsConfig(
        enabled=bool(getattr(settings, "SMS_ENABLED", False)),
        mock=bool(getattr(settings, "SMS_MOCK", False)),
        provider=getattr(settings, "SMS_PROVIDER", SmsProviderName.SMSGATEWAYHUB),
        timeout=int(getattr(settings, "SMS_TIMEOUT", 10)),
        max_retries=int(getattr(settings, "SMS_MAX_RETRIES", 2)),
        retry_backoff=float(getattr(settings, "SMS_RETRY_BACKOFF", 0.5)),
        default_country_code=str(getattr(settings, "SMS_DEFAULT_COUNTRY_CODE", "91")),
        max_length=int(getattr(settings, "SMS_MAX_LENGTH", 1000)),
        base_url=getattr(settings, "SMS_GATEWAYHUB_BASE_URL",
                         "https://www.smsgatewayhub.com").rstrip("/"),
        api_key=getattr(settings, "SMS_GATEWAYHUB_API_KEY", ""),
        sender_id=getattr(settings, "SMS_GATEWAYHUB_SENDER_ID", ""),
        route=str(getattr(settings, "SMS_GATEWAYHUB_ROUTE", "1")),
        channel=str(getattr(settings, "SMS_GATEWAYHUB_CHANNEL", "2")),
        dcs=str(getattr(settings, "SMS_GATEWAYHUB_DCS", "0")),
        entity_id=getattr(settings, "SMS_GATEWAYHUB_ENTITY_ID", ""),
        dlt_template_id=getattr(settings, "SMS_GATEWAYHUB_DLT_TEMPLATE_ID", ""),
    )
