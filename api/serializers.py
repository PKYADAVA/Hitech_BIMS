"""Serializer factory — the DRY core for domain resources.

Instead of hand-writing a ``ModelSerializer`` per model (20+ across broiler and
hatchery alone, each nearly identical), domain modules call
:func:`serializer_factory`. It builds a ``ModelSerializer`` with:

* ``fields = "__all__"`` (or an explicit ``fields``/``exclude``),
* audit/lock fields forced read-only so clients can't spoof them,
* file/image fields rendered as **absolute URLs** (DRF does this when the
  request is in context — which the base viewset always provides), fixing the
  relative-media-URL problem the audit flagged.

A model needing a bespoke representation (nested children, computed fields) can
still declare its own serializer and pass it to ``register_model`` — the
factory is the default, not a straitjacket.
"""
from __future__ import annotations

from typing import Optional

from rest_framework import serializers

# Fields that must never be client-writable if the model has them.
_FORCE_READ_ONLY = frozenset(
    {"created_at", "updated_at", "created_on", "updated_on", "created_by",
     "modified_by", "deleted_at", "deleted_by", "is_locked"}
)


def serializer_factory(
    model,
    *,
    fields: Optional[list[str]] = None,
    exclude: Optional[list[str]] = None,
    read_only: Optional[list[str]] = None,
) -> type[serializers.ModelSerializer]:
    """Return a ``ModelSerializer`` subclass for ``model``."""
    model_field_names = {f.name for f in model._meta.get_fields()}
    forced = (_FORCE_READ_ONLY & model_field_names) | set(read_only or [])

    meta_attrs: dict = {"model": model}
    if fields is not None:
        meta_attrs["fields"] = fields
    elif exclude is not None:
        meta_attrs["exclude"] = exclude
    else:
        meta_attrs["fields"] = "__all__"
    # Only mark as read-only the forced fields that are actually serialized.
    if "fields" in meta_attrs and meta_attrs["fields"] != "__all__":
        forced = forced & set(meta_attrs["fields"])
    if forced:
        meta_attrs["read_only_fields"] = sorted(forced)

    meta = type("Meta", (), meta_attrs)
    return type(f"{model.__name__}Serializer", (serializers.ModelSerializer,), {"Meta": meta})
