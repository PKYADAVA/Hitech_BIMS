"""Opt-in manager/queryset for auditing bulk operations.

**Why this exists:** Django emits ``post_save``/``post_delete`` per *instance*
saved through ``Model.save()``. The bulk paths deliberately bypass that for
performance, so **no signal fires** for:

* ``Model.objects.bulk_create([...])``
* ``Model.objects.bulk_update([...], fields)``
* ``queryset.update(...)``
* ``queryset.delete()``

There is no signal hook to retrofit, so the only correct alternative is to
override these methods. A model opts in explicitly::

    from alerts.managers import AlertableManager

    class Invoice(models.Model):
        ...
        objects = AlertableManager()

After that, the four bulk methods each emit a single summarising bulk alert
(``ENABLE_BULK_EVENTS`` gates this). Per-row diffs are intentionally *not*
produced for bulk paths — that would defeat the performance win — so bulk
alerts record counts and the operation, not field-level before/after.
"""
from __future__ import annotations

from django.db import models

from .conf import config
from .constants import Action


class AlertableQuerySet(models.QuerySet):
    def update(self, **kwargs):
        count = super().update(**kwargs)
        if config.ENABLE_BULK_EVENTS and count:
            from .handlers import handle_bulk

            handle_bulk(
                self.model,
                Action.BULK_UPDATE,
                count,
                metadata={"fields": sorted(kwargs.keys())},
            )
        return count

    def delete(self):
        count_before = self.count()
        result = super().delete()
        if config.ENABLE_BULK_EVENTS and count_before:
            from .handlers import handle_bulk

            handle_bulk(self.model, Action.BULK_DELETE, count_before)
        return result


class AlertableManager(models.Manager.from_queryset(AlertableQuerySet)):
    """Manager whose ``bulk_create``/``bulk_update`` also emit bulk alerts."""

    def bulk_create(self, objs, *args, **kwargs):
        created = super().bulk_create(objs, *args, **kwargs)
        if config.ENABLE_BULK_EVENTS and created:
            from .handlers import handle_bulk

            handle_bulk(self.model, Action.BULK_CREATE, len(created))
        return created

    def bulk_update(self, objs, fields, *args, **kwargs):
        result = super().bulk_update(objs, fields, *args, **kwargs)
        count = len(objs) if hasattr(objs, "__len__") else 0
        if config.ENABLE_BULK_EVENTS and count:
            from .handlers import handle_bulk

            handle_bulk(
                self.model,
                Action.BULK_UPDATE,
                count,
                metadata={"fields": sorted(fields)},
            )
        return result
