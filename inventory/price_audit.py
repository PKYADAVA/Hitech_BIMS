"""Change log for the Item Price List — every price created, edited or deleted,
by whom, and where from.

Recorded from model signals rather than in the views, so the price list page,
a bulk revision, an upload, the mobile API and the admin all leave the same
trail. The user comes from the request the alerts middleware publishes
(alerts.context). Where the change came from is named by the caller with
price_change(), or otherwise read off the request path.
"""
import contextvars
from contextlib import contextmanager
from decimal import Decimal

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .models import Item, ItemPriceList, ItemPriceListAudit

SOURCE_PAGE = "Price List"
SOURCE_BULK = "Bulk Revision"
SOURCE_UPLOAD = "Upload"
SOURCE_API = "Mobile / API"
SOURCE_ADMIN = "Admin"
SOURCE_SYSTEM = "System"

_change = contextvars.ContextVar("item_price_change", default=None)


@contextmanager
def price_change(source, note=""):
    """Name where the price changes made inside this block come from."""
    token = _change.set({"source": source, "note": (note or "")[:255]})
    try:
        yield
    finally:
        _change.reset(token)


def _request_and_user():
    from alerts.context import get_current_request, get_current_user
    return get_current_request(), get_current_user()


def _where(request):
    named = _change.get()
    if named:
        return named
    path = getattr(request, "path", "") or ""
    if path.startswith("/api/"):
        return {"source": SOURCE_API, "note": ""}
    if path.startswith("/admin/"):
        return {"source": SOURCE_ADMIN, "note": ""}
    if request is None:
        return {"source": SOURCE_SYSTEM, "note": ""}
    return {"source": SOURCE_PAGE, "note": ""}


def _money(value):
    if value in (None, ""):
        return None
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _values(entry):
    from inventory.services.price_list import parse_date
    return {"item_id": entry.item_id, "price": _money(entry.price),
            "effective_date": parse_date(entry.effective_date)}


def _write(action, entry_id, item_id, old=None, new=None):
    request, user = _request_and_user()
    where = _where(request)
    item = Item.objects.filter(id=item_id).only("item_code", "description").first()
    user_id = getattr(user, "pk", None)
    ItemPriceListAudit.objects.create(
        price_entry_ref=entry_id,
        item_ref=item_id,
        item_label=(str(item) if item else "")[:255],
        action=action,
        old_price=(old or {}).get("price"),
        new_price=(new or {}).get("price"),
        old_effective_date=(old or {}).get("effective_date"),
        new_effective_date=(new or {}).get("effective_date"),
        source=where["source"],
        note=where["note"],
        user_id=user_id,
        user_label=((user.get_full_name() or user.get_username()) if user_id else "")[:150],
    )


@receiver(pre_save, sender=ItemPriceList, dispatch_uid="item_price_audit_before")
def _remember_before(sender, instance, raw=False, **kwargs):
    instance._price_audit_before = None
    if raw or not instance.pk:
        return
    old = (sender.objects.filter(pk=instance.pk)
           .values("item_id", "price", "effective_date").first())
    if old:
        instance._price_audit_before = {"item_id": old["item_id"],
                                        "price": _money(old["price"]),
                                        "effective_date": old["effective_date"]}


@receiver(post_save, sender=ItemPriceList, dispatch_uid="item_price_audit_after")
def _record_save(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    now = _values(instance)
    before = getattr(instance, "_price_audit_before", None)
    if created or before is None:
        _write("create", instance.pk, instance.item_id, new=now)
    elif before != now:
        _write("update", instance.pk, instance.item_id, old=before, new=now)


@receiver(post_delete, sender=ItemPriceList, dispatch_uid="item_price_audit_delete")
def _record_delete(sender, instance, **kwargs):
    _write("delete", instance.pk, instance.item_id, old=_values(instance))
