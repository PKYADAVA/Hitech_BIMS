"""Handlers translate raw signal facts into :class:`AlertEvent`s.

This is the layer that knows the *semantics*: that a save which flipped
``is_deleted`` is really a soft-delete, that a change to ``status`` is a status
transition, that a password write on the user model is a credential change.
Signals call these functions; the functions build an event and hand it to
:func:`alerts.services.process_event`. No persistence logic lives here.
"""
from __future__ import annotations

from typing import Optional

from .constants import (
    SOFT_DELETE_BOOL_FIELDS,
    SOFT_DELETE_DATE_FIELDS,
    STATUS_FIELD_NAMES,
    Action,
)
from .services import AlertEvent, process_event
from .utils import model_label, object_display, verbose_model_name

# action -> event_type suffix, combined with the model's prefix.
_EVENT_SUFFIX = {
    Action.CREATE: "created",
    Action.UPDATE: "updated",
    Action.DELETE: "deleted",
    Action.SOFT_DELETE: "soft_deleted",
    Action.RESTORE: "restored",
    Action.STATUS_CHANGE: "status_changed",
    Action.BULK_CREATE: "bulk_created",
    Action.BULK_UPDATE: "bulk_updated",
    Action.BULK_DELETE: "bulk_deleted",
}


def _event_type(rule, action: str) -> str:
    return f"{rule.prefix()}_{_EVENT_SUFFIX.get(action, action)}"


def _base_event(rule, instance, action: str) -> AlertEvent:
    return AlertEvent(
        action=action,
        model_name=model_label(type(instance)),
        object_id=str(instance.pk),
        object_display=object_display(instance),
        event_type=_event_type(rule, action),
        severity=rule.severity if rule.severity != "info" else None,
        verbose_model=verbose_model_name(type(instance)),
        audit=rule.audit,
    )


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #
def handle_create(rule, instance) -> None:
    if not rule.track_create:
        return
    event = _base_event(rule, instance, Action.CREATE)
    process_event(event)


def _classify_update(instance, diff: dict) -> str:
    """Refine a generic UPDATE into soft-delete / restore / status change."""
    for f in SOFT_DELETE_BOOL_FIELDS & diff.keys():
        info = diff[f]
        return Action.SOFT_DELETE if info["new"] else Action.RESTORE
    for f in SOFT_DELETE_DATE_FIELDS & diff.keys():
        info = diff[f]
        return Action.SOFT_DELETE if info["new"] else Action.RESTORE
    if STATUS_FIELD_NAMES & diff.keys():
        return Action.STATUS_CHANGE
    if "password" in diff:
        return Action.PASSWORD_CHANGE
    return Action.UPDATE


def handle_update(rule, instance, diff: dict, before: dict, after: dict) -> None:
    if not rule.track_update or not diff:
        return
    action = _classify_update(instance, diff)
    event = _base_event(rule, instance, action)
    event.event_type = _event_type(rule, action)
    event.changed_fields = diff
    event.before = before
    event.after = after
    process_event(event)


def handle_delete(rule, instance) -> None:
    if not rule.track_delete:
        return
    event = _base_event(rule, instance, Action.DELETE)
    # Snapshot the row being destroyed so the audit "before" survives it.
    from .diff import snapshot_fields
    from .utils import to_jsonable

    event.before = {k: to_jsonable(v) for k, v in snapshot_fields(instance).items()}
    process_event(event)


def handle_m2m(rule, instance, action_word: str, model, pk_set) -> None:
    if not rule.track_m2m or action_word not in ("post_add", "post_remove", "post_clear"):
        return
    verb = {"post_add": "added", "post_remove": "removed", "post_clear": "cleared"}[action_word]
    event = _base_event(rule, instance, Action.UPDATE)
    event.metadata = {
        "m2m": verb,
        "related_model": model_label(model) if model else "",
        "related_ids": sorted(str(pk) for pk in (pk_set or [])),
    }
    event.changed_fields = {
        "relations": {
            "label": "Relations",
            "old": "",
            "new": f"{verb} {len(pk_set or [])} item(s)",
        }
    }
    process_event(event)


# --------------------------------------------------------------------------- #
# Bulk (see services / managers — signals do not fire for these)
# --------------------------------------------------------------------------- #
def handle_bulk(model, action: str, count: int, metadata: Optional[dict] = None) -> None:
    from .registry import registry

    rule = registry.get_rule(model)
    prefix = rule.prefix() if rule else model._meta.model_name
    event = AlertEvent(
        action=action,
        model_name=model_label(model),
        event_type=f"{prefix}_{_EVENT_SUFFIX.get(action, action)}",
        verbose_model=verbose_model_name(model),
        count=count,
        metadata=metadata or {},
        severity=(rule.severity if rule and rule.severity != "info" else None),
        audit=(rule.audit if rule else True),
    )
    process_event(event)


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
def handle_login(user) -> None:
    process_event(
        AlertEvent(
            action=Action.LOGIN,
            event_type="login",
            model_name="auth.User",
            object_id=str(user.pk),
            object_display=user.get_username(),
            audit=True,
        )
    )


def handle_logout(user) -> None:
    if user is None:
        return
    process_event(
        AlertEvent(
            action=Action.LOGOUT,
            event_type="logout",
            model_name="auth.User",
            object_id=str(user.pk),
            object_display=user.get_username(),
            audit=True,
        )
    )


def handle_login_failed(credentials: dict) -> None:
    username = credentials.get("username", "") if credentials else ""
    process_event(
        AlertEvent(
            action=Action.LOGIN_FAILED,
            event_type="login_failed",
            model_name="auth.User",
            object_display=username,
            title=f"Failed login attempt for {username or 'unknown user'}",
        )
    )
