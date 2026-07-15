"""Centralised access to SMS configuration.

All settings are read from ``django.conf.settings`` in exactly one place so the
rest of the subsystem never touches Django settings directly. This keeps the
provider and service layers easy to test with overridden configuration.
"""

from dataclasses import dataclass, replace

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
    """Build an :class:`SmsConfig` from Django settings, overlaid with the
    :class:`~notification.models.SmsSettings` master row when one exists.

    The DB row is authoritative for the enabled/mock switches; its text
    fields override the environment only when non-blank, so a blank API key
    in the master keeps using the ``.env`` credential.
    """

    config = _load_env_config()
    row = _load_db_settings()
    if row is None:
        return config
    return replace(
        config,
        enabled=row.enabled,
        mock=row.mock,
        api_key=row.api_key or config.api_key,
        sender_id=row.sender_id or config.sender_id,
        entity_id=row.entity_id or config.entity_id,
        default_country_code=row.default_country_code or config.default_country_code,
    )


def _load_db_settings():
    """Return the SmsSettings singleton row, or ``None`` when unavailable
    (row never created, table missing mid-migration, etc.)."""

    try:
        from .models import SmsSettings  # local import: avoid circulars at load time

        return SmsSettings.objects.filter(pk=1).first()
    except Exception:  # pylint: disable=broad-except
        return None


def _load_env_config() -> SmsConfig:
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
