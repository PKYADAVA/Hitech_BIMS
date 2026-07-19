"""App configuration.

``ready()`` is the single wiring point: it imports the signal module (which
registers the auth receivers) and asks the registry to connect model signals.
Nothing heavy — no DB access, no importing of Channels/Celery — happens here,
so app startup stays fast and side-effect free.
"""
from __future__ import annotations

import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class AlertsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "alerts"
    verbose_name = "Alerts & Audit"

    def ready(self) -> None:
        # Importing signals binds the login/logout/password receivers.
        from . import signals  # noqa: F401  (import for side effects)
        from .registry import registry

        try:
            registry.autodiscover()
            registry.connect()
        except Exception:  # never let audit wiring break app startup
            logger.exception("alerts: failed to connect model signals")
