"""Hatchery document write endpoints for the mobile API v1.

Same approach as ``inventory.api_write``: each mobile view delegates to the
web module's own document ``*API`` (``hatchery.views``), so a phone save runs
the identical header+item-row validation and replacement the web form does —
no second copy of that logic here.

Mounted under ``/api/v1/hatchery/<txn>/save[/<id>]`` by ``api/urls.py``.
"""
from __future__ import annotations

from django.urls import path

from inventory.api_write import _make_write_view, _s

from . import views as web
from .models import EggPurchase


def _load_egg_purchase(o) -> dict:
    """An existing egg purchase in the shape the phone's form fields use."""
    return {
        "transaction_no": o.transaction_no or "",
        "date": _s(o.date),
        "supplier": _s(o.supplier_id),
        "warehouse": _s(o.warehouse_id),
        "dc_no": o.dc_no or "",
        "vehicle": o.vehicle or "",
        "driver": o.driver or "",
        "freight_type": o.freight_type or "Exclude",
        "payment_mode": o.payment_mode or "pay_later",
        "pay_account": _s(o.pay_account_id),
        "freight_account": _s(o.freight_account_id),
        "freight_amount": _s(o.freight_amount),
        "tcs_applicable": bool(o.tcs_applicable),
        "tcs_percent": _s(o.tcs_percent),
        "remarks": o.remarks or "",
        "items": [{
            "item": _s(row.item_id),
            "sent_qty": _s(row.sent_qty),
            "rcv_qty": _s(row.rcv_qty),
            "free_qty": _s(row.free_qty),
            "no_of_boxes": _s(row.no_of_boxes),
            "rate": _s(row.rate),
            "discount_percent": _s(row.discount_percent),
            "discount_amount": _s(row.discount_amount),
        } for row in o.items.all()],
    }


EggPurchaseWriteView = _make_write_view(web.EggPurchaseAPI, EggPurchase, _load_egg_purchase)


def write_urls() -> list:
    """URL patterns for the hatchery document write endpoints."""
    return [
        path("hatchery/egg-purchases/save", EggPurchaseWriteView.as_view(),
             name="hatchery-egg-purchases-save-new"),
        path("hatchery/egg-purchases/save/<int:pk>", EggPurchaseWriteView.as_view(),
             name="hatchery-egg-purchases-save"),
    ]
