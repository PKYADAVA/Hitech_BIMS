"""Pluggable notification channels.

A channel takes a payload (the fields needed to build/deliver a notification)
and delivers it somewhere: the database feed, the log, email, a websocket,
Slack, Teams… New channels are added by subclassing :class:`BaseChannel` and
listing the dotted path in ``ALERT_SETTINGS["CHANNELS"]`` — no other code
changes. Every channel is failure-isolated by the dispatcher (see services),
so a broken webhook never breaks the originating request.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from django.core.mail import send_mail
from django.utils.module_loading import import_string

from .conf import config
from .constants import Severity

logger = logging.getLogger(__name__)

_SEVERITY_ORDER = {
    Severity.INFO: 0,
    Severity.SUCCESS: 1,
    Severity.WARNING: 2,
    Severity.ERROR: 3,
    Severity.CRITICAL: 4,
}


def severity_rank(value: str) -> int:
    return _SEVERITY_ORDER.get(value, 0)


class BaseChannel:
    """Interface every channel implements.

    ``enabled`` lets a channel opt out cheaply (e.g. email disabled by config)
    so the dispatcher can skip it without constructing a message.
    """

    name = "base"

    def enabled(self) -> bool:
        return True

    def deliver(self, payload: dict[str, Any], alert: Optional[Any] = None) -> None:
        raise NotImplementedError


class DatabaseChannel(BaseChannel):
    """Persists the :class:`~alerts.models.Alert` row (the in-app feed).

    This is the primary channel; the Alert instance is created by the service
    and passed in, so this channel is a no-op placeholder that simply confirms
    persistence happened. Kept as a channel for symmetry and so it can be
    disabled to run audit-only.
    """

    name = "database"

    def deliver(self, payload, alert=None):
        # The Alert row is created transactionally by AlertService before
        # channels fan out; nothing to do here beyond acknowledging it.
        return None


class LogChannel(BaseChannel):
    """Writes every alert to the standard logging pipeline."""

    name = "log"

    def deliver(self, payload, alert=None):
        level = logging.WARNING if severity_rank(payload.get("severity", "info")) >= 2 else logging.INFO
        logger.log(
            level,
            "ALERT %s | %s | by=%s | obj=%s",
            payload.get("event_type"),
            payload.get("title"),
            payload.get("actor_label") or "system",
            payload.get("object_display"),
        )


class EmailChannel(BaseChannel):
    """Emails high-severity alerts to configured recipients."""

    name = "email"

    def enabled(self) -> bool:
        return bool(config.ENABLE_EMAIL)

    def _recipients(self) -> list[str]:
        recipients = list(config.EMAIL_RECIPIENTS)
        if recipients:
            return recipients
        # Fall back to Django ADMINS/MANAGERS.
        from django.conf import settings

        return [email for _name, email in (settings.MANAGERS or settings.ADMINS or [])]

    def deliver(self, payload, alert=None):
        if severity_rank(payload.get("severity", "info")) < severity_rank(config.EMAIL_MIN_SEVERITY):
            return
        recipients = self._recipients()
        if not recipients:
            logger.debug("alerts.email: no recipients configured; skipping")
            return
        from django.conf import settings

        send_mail(
            subject=f"[{payload.get('severity', 'info').upper()}] {payload.get('title')}",
            message=payload.get("message") or payload.get("title") or "",
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None) or settings.EMAIL_HOST_USER,
            recipient_list=recipients,
            fail_silently=True,
        )


class WebSocketChannel(BaseChannel):
    """Broadcasts alerts over Django Channels, if it is installed.

    Import of ``channels`` is deferred to ``deliver`` so the module stays
    importable in a project without Channels (as this one currently is). When
    Channels is added later, set ``ENABLE_WEBSOCKET=True`` and configure a
    channel layer — no code change required here (see ``consumers.py``).
    """

    name = "websocket"

    def enabled(self) -> bool:
        return bool(config.ENABLE_WEBSOCKET)

    def deliver(self, payload, alert=None):
        try:
            from asgiref.sync import async_to_sync
            from channels.layers import get_channel_layer
        except Exception:
            logger.debug("alerts.websocket: channels not installed; skipping")
            return
        layer = get_channel_layer()
        if layer is None:
            return
        # Per-user group + a global admin group (see AlertConsumer).
        groups = ["alerts_all"]
        if payload.get("performed_by_id"):
            groups.append(f"alerts_user_{payload['performed_by_id']}")
        message = {"type": "alert.message", "content": payload}
        for group in groups:
            async_to_sync(layer.group_send)(group, message)


class SlackChannel(BaseChannel):
    name = "slack"

    def enabled(self) -> bool:
        return bool(config.ENABLE_SLACK and config.SLACK_WEBHOOK_URL)

    def deliver(self, payload, alert=None):
        self._post_webhook(config.SLACK_WEBHOOK_URL, {"text": self._format(payload)})

    @staticmethod
    def _format(payload) -> str:
        return f":bell: *{payload.get('title')}*\n{payload.get('message') or ''}"

    @staticmethod
    def _post_webhook(url: str, body: dict) -> None:
        try:
            import requests

            requests.post(url, json=body, timeout=5)
        except Exception:
            logger.exception("alerts: webhook post failed")


class TeamsChannel(SlackChannel):
    name = "teams"

    def enabled(self) -> bool:
        return bool(config.ENABLE_TEAMS and config.TEAMS_WEBHOOK_URL)

    def deliver(self, payload, alert=None):
        card = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "summary": payload.get("title"),
            "title": payload.get("title"),
            "text": payload.get("message") or "",
        }
        self._post_webhook(config.TEAMS_WEBHOOK_URL, card)


_channel_cache: Optional[list[BaseChannel]] = None


def get_channels() -> list[BaseChannel]:
    """Instantiate configured channels once, keeping only the enabled ones."""
    global _channel_cache
    if _channel_cache is None:
        channels: list[BaseChannel] = []
        for path in config.CHANNELS:
            try:
                channels.append(import_string(path)())
            except Exception:
                logger.exception("alerts: could not load channel %s", path)
        _channel_cache = channels
    return [c for c in _channel_cache if c.enabled()]


def reset_channel_cache() -> None:
    """Test hook — force re-instantiation after settings override."""
    global _channel_cache
    _channel_cache = None
