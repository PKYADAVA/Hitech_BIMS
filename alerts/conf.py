"""Typed, cached accessor for the module's configuration.

The whole module reads its behaviour from ``settings.ALERT_SETTINGS`` through
this single object, mirroring the ``notification/conf.py`` convention already
used in this project: nothing else imports ``django.conf.settings`` for alert
config, so defaults live in exactly one place and tests can override cleanly.
"""
from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.signals import setting_changed
from django.dispatch import receiver

from .constants import DEFAULT_IGNORE_APP_LABELS, DEFAULT_IGNORE_FIELDS

DEFAULTS: dict[str, Any] = {
    # --- scope -----------------------------------------------------------
    # When True every concrete model (minus IGNORE_APP_LABELS / IGNORE_MODELS)
    # is audited automatically, so newly-added apps need zero wiring. When
    # False only models added via the registry / @register_alert are tracked.
    "TRACK_ALL_MODELS": True,
    "IGNORE_MODELS": [],          # ["app_label.ModelName", ...]
    "IGNORE_APP_LABELS": [],      # merged with DEFAULT_IGNORE_APP_LABELS
    "IGNORE_FIELDS": [],          # merged with DEFAULT_IGNORE_FIELDS
    # --- features --------------------------------------------------------
    "ENABLE_AUDIT": True,         # write immutable AuditLog rows
    "ENABLE_ALERTS": True,        # write Alert rows (feed/notifications)
    "ENABLE_BULK_EVENTS": True,   # emit alerts for bulk_* manager helpers
    "ENABLE_AUTH_EVENTS": True,   # login / logout / password change
    "SKIP_UNCHANGED_UPDATES": True,  # no alert when a save changes nothing
    # --- notification channels ------------------------------------------
    # Channel dotted-paths; Database + Log are safe defaults. Email/WebSocket/
    # Slack/Teams are opt-in and no-op cleanly if their infra is absent.
    "CHANNELS": [
        "alerts.channels.DatabaseChannel",
        "alerts.channels.LogChannel",
    ],
    "ENABLE_EMAIL": False,
    "ENABLE_WEBSOCKET": False,
    "ENABLE_SLACK": False,
    "ENABLE_TEAMS": False,
    "EMAIL_RECIPIENTS": [],       # explicit list, or empty -> managers/admins
    "EMAIL_MIN_SEVERITY": "error",
    "SLACK_WEBHOOK_URL": "",
    "TEAMS_WEBHOOK_URL": "",
    # --- async -----------------------------------------------------------
    # "auto" uses Celery if importable, else runs inline. Force with
    # "celery" / "inline". Kept an abstraction so workers can be added later
    # without touching call sites.
    "ASYNC_BACKEND": "auto",
    # --- message templates ----------------------------------------------
    # Override per-action wording without touching code. Placeholders:
    # {actor} {model} {object} {id} {changes}. Missing keys fall back to
    # alerts.services.DEFAULT_TEMPLATES.
    "TEMPLATES": {},
    # --- retention / api -------------------------------------------------
    "DEFAULT_PAGE_SIZE": 25,
    "MAX_DISPLAY_LENGTH": 140,    # truncation for object_display / messages
}


class AlertConfig:
    """Lazily-resolved, cached view over ``settings.ALERT_SETTINGS``."""

    def __init__(self) -> None:
        self._cache: dict[str, Any] | None = None

    def _resolve(self) -> dict[str, Any]:
        if self._cache is None:
            merged = dict(DEFAULTS)
            merged.update(getattr(settings, "ALERT_SETTINGS", {}) or {})
            # Merge (not replace) the framework-noise defaults so callers only
            # ever need to list their *additional* exclusions.
            merged["IGNORE_APP_LABELS"] = set(DEFAULT_IGNORE_APP_LABELS) | set(
                merged.get("IGNORE_APP_LABELS", [])
            )
            merged["IGNORE_FIELDS"] = set(DEFAULT_IGNORE_FIELDS) | set(
                merged.get("IGNORE_FIELDS", [])
            )
            merged["IGNORE_MODELS"] = {m.lower() for m in merged.get("IGNORE_MODELS", [])}
            self._cache = merged
        return self._cache

    def __getattr__(self, name: str) -> Any:
        try:
            return self._resolve()[name]
        except KeyError as exc:  # pragma: no cover - defensive
            raise AttributeError(name) from exc

    def reload(self) -> None:
        """Drop the cache so the next access re-reads settings (used in tests)."""
        self._cache = None


config = AlertConfig()


@receiver(setting_changed)
def _reload_on_setting_change(sender, setting, **kwargs):  # pragma: no cover
    if setting == "ALERT_SETTINGS":
        config.reload()
