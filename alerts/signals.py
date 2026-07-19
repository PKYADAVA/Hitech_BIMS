"""Signal receivers — thin adapters, no business logic.

Each receiver's only job is to capture facts (created? which fields changed?
what were the old values?) and delegate to :mod:`alerts.handlers`. Per-model
CRUD signals are connected dynamically from the registry; the auth signals are
connected once at import time.

Why ``pre_save`` matters: ``post_save`` alone cannot tell you the *old* values,
so we read the pre-save DB row in :func:`_pre_save` and stash a snapshot on the
instance, then diff against it in :func:`_post_save`.
"""
from __future__ import annotations

import logging

from django.contrib.auth.signals import (
    user_logged_in,
    user_logged_out,
    user_login_failed,
)
from django.db.models.signals import m2m_changed, post_delete, post_save, pre_save
from django.dispatch import receiver

from . import handlers
from .conf import config
from .diff import compute_diff, snapshot_fields
from .registry import registry
from .utils import model_label, to_jsonable

logger = logging.getLogger(__name__)

_BEFORE_ATTR = "_alerts_before"


# --------------------------------------------------------------------------- #
# Per-model CRUD receivers (dispatched by sender lookup in the registry)
# --------------------------------------------------------------------------- #
def _pre_save(sender, instance, **kwargs):
    """Capture the pre-save DB snapshot for diffing in post_save."""
    if instance.pk is None or instance._state.adding:
        instance.__dict__[_BEFORE_ATTR] = None
        return
    try:
        # _base_manager bypasses soft-delete/custom managers so we still see
        # the row even when it has been filtered out of the default queryset.
        old = sender._base_manager.filter(pk=instance.pk).first()
    except Exception:
        old = None
    instance.__dict__[_BEFORE_ATTR] = snapshot_fields(old) if old is not None else None


def _post_save(sender, instance, created, **kwargs):
    rule = registry.get_rule(sender)
    if rule is None:
        return
    try:
        if created:
            handlers.handle_create(rule, instance)
            return
        before_raw = instance.__dict__.pop(_BEFORE_ATTR, None)
        if before_raw is None:
            # No baseline (e.g. save() on a fetched-elsewhere instance); treat
            # as an update we can't diff — skip to honour SKIP_UNCHANGED_UPDATES.
            if not config.SKIP_UNCHANGED_UPDATES:
                handlers.handle_update(rule, instance, {}, {}, {})
            return
        after_raw = snapshot_fields(instance)
        diff = compute_diff(sender, before_raw, after_raw)
        if not diff and config.SKIP_UNCHANGED_UPDATES:
            return
        before = {k: to_jsonable(v) for k, v in before_raw.items()}
        after = {k: to_jsonable(v) for k, v in after_raw.items()}
        handlers.handle_update(rule, instance, diff, before, after)
    except Exception:
        logger.exception("alerts: post_save handling failed for %s", model_label(sender))


def _post_delete(sender, instance, **kwargs):
    rule = registry.get_rule(sender)
    if rule is None:
        return
    try:
        handlers.handle_delete(rule, instance)
    except Exception:
        logger.exception("alerts: post_delete handling failed for %s", model_label(sender))


def _m2m_changed(sender, instance, action, model, pk_set, **kwargs):
    rule = registry.get_rule(type(instance))
    if rule is None:
        return
    try:
        handlers.handle_m2m(rule, instance, action, model, pk_set)
    except Exception:
        logger.exception("alerts: m2m handling failed")


# --------------------------------------------------------------------------- #
# Connect / disconnect (called by the registry)
# --------------------------------------------------------------------------- #
def connect_model(rule) -> None:
    model = rule.model
    label = model_label(model)
    pre_save.connect(_pre_save, sender=model, dispatch_uid=f"alerts_pre_{label}", weak=False)
    post_save.connect(_post_save, sender=model, dispatch_uid=f"alerts_post_{label}", weak=False)
    post_delete.connect(_post_delete, sender=model, dispatch_uid=f"alerts_del_{label}", weak=False)
    if rule.track_m2m:
        for m2m in model._meta.local_many_to_many:
            through = getattr(model, m2m.name).through
            m2m_changed.connect(
                _m2m_changed,
                sender=through,
                dispatch_uid=f"alerts_m2m_{label}_{m2m.name}",
                weak=False,
            )


def disconnect_model(rule) -> None:
    model = rule.model
    label = model_label(model)
    pre_save.disconnect(sender=model, dispatch_uid=f"alerts_pre_{label}")
    post_save.disconnect(sender=model, dispatch_uid=f"alerts_post_{label}")
    post_delete.disconnect(sender=model, dispatch_uid=f"alerts_del_{label}")
    for m2m in model._meta.local_many_to_many:
        through = getattr(model, m2m.name).through
        m2m_changed.disconnect(sender=through, dispatch_uid=f"alerts_m2m_{label}_{m2m.name}")


# --------------------------------------------------------------------------- #
# Auth receivers (connected once, at import)
# --------------------------------------------------------------------------- #
@receiver(user_logged_in, dispatch_uid="alerts_user_logged_in")
def _on_login(sender, request, user, **kwargs):
    if config.ENABLE_AUTH_EVENTS:
        handlers.handle_login(user)


@receiver(user_logged_out, dispatch_uid="alerts_user_logged_out")
def _on_logout(sender, request, user, **kwargs):
    if config.ENABLE_AUTH_EVENTS:
        handlers.handle_logout(user)


@receiver(user_login_failed, dispatch_uid="alerts_user_login_failed")
def _on_login_failed(sender, credentials, **kwargs):
    if config.ENABLE_AUTH_EVENTS:
        handlers.handle_login_failed(credentials)
