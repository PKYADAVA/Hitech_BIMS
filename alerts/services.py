"""Service layer — where all the actual work happens.

Signals stay dumb: they capture facts and call these services. This keeps
business logic testable in isolation and honours the "no logic in signals"
rule from the spec. Two public services plus a couple of free functions:

* :class:`AuditService`  — write immutable :class:`~alerts.models.AuditLog` rows.
* :class:`AlertService`  — write :class:`~alerts.models.Alert` rows and fan the
  notification out to channels (async where configured).
* :func:`emit_event`     — public entry point for *custom* business events
  (approvals, file uploads, "document published", …) from anywhere in the app.
* :func:`deliver_to_channels` — the fan-out, called inline or from a task.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from django.db import transaction

from .conf import config
from .constants import Action, EventType, Severity
from .context import capture_snapshot, get_extra_meta
from .models import Alert, AuditLog

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Message templates
# --------------------------------------------------------------------------- #
DEFAULT_TEMPLATES: dict[str, str] = {
    Action.CREATE: "{actor} created {model} {object}",
    Action.UPDATE: "{actor} updated {model} {object}{changes}",
    Action.DELETE: "{actor} deleted {model} {object}",
    Action.BULK_CREATE: "{actor} bulk-created {model} ({count} records)",
    Action.BULK_UPDATE: "{actor} bulk-updated {model} ({count} records)",
    Action.BULK_DELETE: "{actor} bulk-deleted {model} ({count} records)",
    Action.SOFT_DELETE: "{actor} archived {model} {object}",
    Action.RESTORE: "{actor} restored {model} {object}",
    Action.STATUS_CHANGE: "{actor} changed {model} {object}: {changes}",
    Action.APPROVE: "{actor} approved {model} {object}",
    Action.REJECT: "{actor} rejected {model} {object}",
    Action.LOGIN: "{actor} logged in",
    Action.LOGOUT: "{actor} logged out",
    Action.LOGIN_FAILED: "Failed login attempt for {object}",
    Action.PASSWORD_CHANGE: "{actor} changed the password for {object}",
    Action.FILE_UPLOAD: "{actor} uploaded a file to {model} {object}",
    Action.FILE_DELETE: "{actor} deleted a file from {model} {object}",
    Action.CUSTOM: "{actor}: {title}",
}

# Default severity per action when a rule/caller does not override it.
DEFAULT_SEVERITY: dict[str, str] = {
    Action.DELETE: Severity.WARNING,
    Action.BULK_DELETE: Severity.WARNING,
    Action.SOFT_DELETE: Severity.WARNING,
    Action.REJECT: Severity.WARNING,
    Action.LOGIN_FAILED: Severity.ERROR,
    Action.PASSWORD_CHANGE: Severity.WARNING,
    Action.APPROVE: Severity.SUCCESS,
    Action.RESTORE: Severity.SUCCESS,
    Action.CREATE: Severity.SUCCESS,
}


# A single field's value in a change clause is capped well below the full
# message limit so one long value (encoded polylines, blobs, long remarks)
# can't blow the message up into a wall of gibberish.
_CHANGE_VALUE_MAX = 60


def _short_repr(value: Any) -> str:
    """repr() of a value, truncated so huge text fields stay readable."""
    text = repr(value)
    if len(text) > _CHANGE_VALUE_MAX:
        text = text[: _CHANGE_VALUE_MAX - 1] + "…"
    return text


def _format_changes(changed_fields: dict) -> str:
    """Render a compact, human ``Status changed from Pending to Approved`` clause."""
    if not changed_fields:
        return ""
    parts = []
    for info in changed_fields.values():
        label = info.get("label", "field")
        old = _short_repr(info.get("old"))
        new = _short_repr(info.get("new"))
        parts.append(f"{label} from {old} to {new}")
    return " (" + "; ".join(parts) + ")"


# --------------------------------------------------------------------------- #
# Event DTO
# --------------------------------------------------------------------------- #
@dataclass
class AlertEvent:
    """Everything needed to render + persist an alert. Built by handlers."""

    action: str
    model_name: str = ""
    object_id: str = ""
    object_display: str = ""
    event_type: str = ""
    severity: Optional[str] = None
    title: str = ""
    message: str = ""
    changed_fields: dict = field(default_factory=dict)
    before: dict = field(default_factory=dict)
    after: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    count: int = 1
    audit: bool = True
    verbose_model: str = ""

    def resolved_severity(self) -> str:
        return self.severity or DEFAULT_SEVERITY.get(self.action, Severity.INFO)


def _render_message(event: AlertEvent, actor_label: str) -> tuple[str, str]:
    """Return ``(title, message)`` from templates + event context."""
    templates = {**DEFAULT_TEMPLATES, **(config.TEMPLATES or {})}
    template = templates.get(event.action, "{actor} performed {action} on {model} {object}")
    ctx = {
        "actor": actor_label or "System",
        "model": event.verbose_model or event.model_name.split(".")[-1],
        "object": event.object_display or (f"#{event.object_id}" if event.object_id else ""),
        "id": event.object_id,
        "action": event.action,
        "count": event.count,
        "title": event.title,
        "changes": _format_changes(event.changed_fields),
    }
    try:
        message = template.format(**ctx).strip()
    except (KeyError, IndexError):
        message = f"{ctx['actor']} performed {event.action} on {ctx['model']} {ctx['object']}"
    title = event.title or message
    return title.strip(), message


# --------------------------------------------------------------------------- #
# Services
# --------------------------------------------------------------------------- #
class AuditService:
    """Writes append-only audit rows."""

    @staticmethod
    def record(event: AlertEvent, snapshot) -> Optional[AuditLog]:
        if not config.ENABLE_AUDIT or not event.audit:
            return None
        extra = get_extra_meta()
        return AuditLog.objects.create(
            event_type=event.event_type or event.action,
            action=event.action,
            model_name=event.model_name,
            object_id=str(event.object_id or "")[:64],
            object_display=(event.object_display or "")[:255],
            performed_by_id=snapshot.user_id,
            actor_label=snapshot.username or "system",
            before=event.before,
            after=event.after,
            changed_fields=event.changed_fields,
            reason=str(extra.get("reason", ""))[:255],
            ip_address=snapshot.ip_address,
            user_agent=snapshot.user_agent,
            request_id=snapshot.request_id,
            metadata={**event.metadata, **{k: v for k, v in extra.items() if k != "reason"}},
        )


class AlertService:
    """Writes the Alert feed row and hands notification to the channels."""

    @staticmethod
    def create(event: AlertEvent) -> Optional[Alert]:
        if not config.ENABLE_ALERTS:
            return None

        snapshot = capture_snapshot()
        actor_label = snapshot.username or "System"
        title, message = _render_message(event, actor_label)
        severity = event.resolved_severity()
        extra = get_extra_meta()

        alert = Alert.objects.create(
            event_type=event.event_type or event.action,
            action=event.action,
            severity=severity,
            model_name=event.model_name,
            object_id=str(event.object_id or "")[:64],
            object_display=(event.object_display or "")[:255],
            title=title[:255],
            message=message,
            performed_by_id=snapshot.user_id,
            actor_label=actor_label,
            ip_address=snapshot.ip_address,
            browser=snapshot.browser,
            device=snapshot.device,
            os=snapshot.os,
            session_id=snapshot.session_id,
            request_id=snapshot.request_id,
            changed_fields=event.changed_fields,
            metadata={**event.metadata, **extra},
        )

        # Fan out to channels *after* the surrounding transaction commits, so a
        # rolled-back save never emits a phantom email/websocket notification.
        payload = _alert_payload(alert)
        transaction.on_commit(lambda: _dispatch(payload))
        return alert


def _alert_payload(alert: Alert) -> dict[str, Any]:
    """Flat, JSON-safe dict handed to channels/tasks (never the ORM object)."""
    return {
        "id": alert.pk,
        "event_type": alert.event_type,
        "action": alert.action,
        "severity": alert.severity,
        "model_name": alert.model_name,
        "object_id": alert.object_id,
        "object_display": alert.object_display,
        "title": alert.title,
        "message": alert.message,
        "actor_label": alert.actor_label,
        "performed_by_id": alert.performed_by_id,
        "changed_fields": alert.changed_fields,
        "created_at": alert.created_at.isoformat(),
    }


def _dispatch(payload: dict[str, Any]) -> None:
    from .tasks import enqueue

    enqueue(payload)


def deliver_to_channels(payload: dict[str, Any]) -> None:
    """Iterate configured channels, isolating failures per-channel.

    Called inline or from the Celery task; a single misbehaving channel is
    logged and skipped so the rest still deliver.
    """
    from .channels import get_channels

    for channel in get_channels():
        try:
            channel.deliver(payload)
        except Exception:
            logger.exception("alerts: channel %s failed to deliver", channel.name)


# --------------------------------------------------------------------------- #
# Orchestration + public API
# --------------------------------------------------------------------------- #
def process_event(event: AlertEvent) -> Optional[Alert]:
    """Persist audit + alert for one event. The single funnel all paths use."""
    try:
        # The nested atomic() is a savepoint: if the audit/alert INSERT
        # fails while the caller is already inside a transaction, only this
        # savepoint rolls back — without it, the caller's whole transaction
        # is poisoned and the except below can't actually protect anything.
        with transaction.atomic():
            snapshot = capture_snapshot()
            AuditService.record(event, snapshot)
            return AlertService.create(event)
    except Exception:
        # Auditing must never break the business operation that triggered it.
        logger.exception("alerts: failed to process event %s", event.action)
        return None


def emit_event(
    *,
    action: str = Action.CUSTOM,
    event_type: str = EventType.DOCUMENT_PUBLISHED,
    instance=None,
    title: str = "",
    message: str = "",
    severity: Optional[str] = None,
    metadata: Optional[dict] = None,
    changed_fields: Optional[dict] = None,
) -> Optional[Alert]:
    """Public helper for custom business events (approvals, uploads, etc.).

    Example::

        from alerts.services import emit_event
        from alerts.constants import Action, EventType

        emit_event(action=Action.APPROVE, event_type=EventType.ORDER_APPROVED,
                   instance=order, title=f"Order {order.number} approved")
    """
    from .utils import model_label, object_display, verbose_model_name

    event = AlertEvent(
        action=action,
        event_type=event_type,
        title=title,
        message=message,
        severity=severity,
        metadata=metadata or {},
        changed_fields=changed_fields or {},
    )
    if instance is not None:
        event.model_name = model_label(type(instance))
        event.object_id = str(instance.pk)
        event.object_display = object_display(instance)
        event.verbose_model = verbose_model_name(type(instance))
    return process_event(event)
