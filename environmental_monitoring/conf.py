"""Centralised access to Environmental Monitoring configuration.

Operational tuning (poll cadence, offline window) is read from
``django.conf.settings`` in exactly one place, mirroring
``notification/conf.py``'s ``SmsConfig``/``load_config`` pattern. The Tapo
account credentials and default alert thresholds are both DB-backed master
records instead (see :class:`~environmental_monitoring.models.TapoAccount`
and :class:`~environmental_monitoring.models.AlertThresholdDefaults`),
editable from the ERP UI under Environmental Monitoring, so operators can
change them without editing .env or restarting the server.
"""

from dataclasses import dataclass

from django.conf import settings


@dataclass(frozen=True)
class EnvMonitoringConfig:
    """Resolved Environmental Monitoring configuration."""

    tapo_username: str
    tapo_password: str
    poll_interval_seconds: int
    offline_after_minutes: int
    default_temp_min: float
    default_temp_max: float
    default_humidity_min: float
    default_humidity_max: float
    default_battery_low_pct: int


def load_config() -> EnvMonitoringConfig:
    """Build an :class:`EnvMonitoringConfig` from the DB master records and Django settings."""
    from .models import AlertThresholdDefaults, TapoAccount

    account = TapoAccount.get_solo()
    thresholds = AlertThresholdDefaults.get_solo()

    return EnvMonitoringConfig(
        tapo_username=account.email,
        tapo_password=account.password,
        poll_interval_seconds=int(getattr(settings, "ENV_MONITORING_POLL_INTERVAL_SECONDS", 60)),
        offline_after_minutes=int(getattr(settings, "ENV_MONITORING_OFFLINE_AFTER_MINUTES", 15)),
        default_temp_min=float(thresholds.temp_min),
        default_temp_max=float(thresholds.temp_max),
        default_humidity_min=float(thresholds.humidity_min),
        default_humidity_max=float(thresholds.humidity_max),
        default_battery_low_pct=int(thresholds.battery_low_pct),
    )
