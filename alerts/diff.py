"""Field-level change detection.

Two responsibilities:

1. :func:`snapshot_fields` — read the *current* concrete field values of an
   instance into a plain dict. Called in ``pre_save`` (against the DB copy) to
   capture "before", and again in ``post_save`` against the saved instance to
   get "after".
2. :func:`compute_diff` — compare before/after and return only the fields that
   actually changed, each as ``{"old": ..., "new": ..., "label": ...}``.

Noise fields (``updated_at`` etc.) are dropped so we never raise an alert for
a save that only bumped a timestamp.
"""
from __future__ import annotations

from typing import Any, Optional

from django.db import models

from .conf import config
from .utils import to_jsonable


def _tracked_fields(model: type[models.Model], ignore: set[str]) -> list[models.Field]:
    """Concrete, non-m2m fields worth diffing (skips the configured noise)."""
    fields = []
    for field in model._meta.concrete_fields:  # excludes m2m, includes FKs
        if field.name in ignore or field.attname in ignore:
            continue
        fields.append(field)
    return fields


def snapshot_fields(
    instance: models.Model, ignore: Optional[set[str]] = None
) -> dict[str, Any]:
    """Raw (un-serialised) attname -> value map for the instance's fields.

    FK values are read via ``attname`` (``customer_id``) so we compare the raw
    id without triggering a database fetch of the related object.
    """
    ignore = ignore if ignore is not None else set(config.IGNORE_FIELDS)
    values: dict[str, Any] = {}
    for field in _tracked_fields(type(instance), ignore):
        values[field.attname] = getattr(instance, field.attname, None)
    return values


def compute_diff(
    model: type[models.Model],
    before: dict[str, Any],
    after: dict[str, Any],
    ignore: Optional[set[str]] = None,
) -> dict[str, dict[str, Any]]:
    """Return ``{field_name: {old, new, label}}`` for changed fields only."""
    ignore = ignore if ignore is not None else set(config.IGNORE_FIELDS)
    # attname -> verbose label, resolved once.
    labels = {
        f.attname: str(getattr(f, "verbose_name", f.name)).title()
        for f in model._meta.concrete_fields
    }
    diff: dict[str, dict[str, Any]] = {}
    keys = set(before) | set(after)
    for key in keys:
        if key in ignore:
            continue
        old = before.get(key)
        new = after.get(key)
        if old == new:
            continue
        # Present FK columns under the relation name (``customer`` not
        # ``customer_id``) for readable messages.
        display_key = key[:-3] if key.endswith("_id") else key
        diff[display_key] = {
            "old": to_jsonable(old),
            "new": to_jsonable(new),
            "label": labels.get(key, display_key.replace("_", " ").title()),
        }
    return diff


def has_changes(diff: dict) -> bool:
    return bool(diff)
