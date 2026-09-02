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
from .models import EggPurchase, HatchSetting


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


def _load_hatch_setting(o) -> dict:
    """An existing hatch setting in the shape the phone's form fields use,
    including its three independently-repeatable row groups."""
    return {
        "setting_no": o.setting_no,
        "batch_flock_no": o.batch_flock_no or "",
        "supplier_name": o.supplier_name or "",
        "primary_machine_nos": o.primary_machine_nos or "",
        "avg_egg_weight": o.avg_egg_weight or "",
        "received_date": _s(o.received_date),
        "received_time": _s(o.received_time),
        "setting_date": _s(o.setting_date),
        "transfer_date": _s(o.transfer_date),
        "hatch_date": _s(o.hatch_date),
        "push_time": _s(o.push_time),
        "received_qty": _s(o.received_qty),
        "breakage_qty": _s(o.breakage_qty),
        "crack_qty": _s(o.crack_qty),
        "setting_qty": _s(o.setting_qty),
        "setter_temperature": o.setter_temperature or "",
        "setter_humidity": o.setter_humidity or "",
        "hatcher_temperature": o.hatcher_temperature or "",
        "hatcher_humidity": o.hatcher_humidity or "",
        "avg_chick_weight": o.avg_chick_weight or "",
        "medicine_vaccine": o.medicine_vaccine or "",
        "packing_boxes_used": _s(o.packing_boxes_used),
        "remarks": o.remarks or "",
        "prepared_by": o.prepared_by or "",
        "verified_by": o.verified_by or "",
        "egg_intakes": [{
            "sub_lot_flock": r.sub_lot_flock or "",
            "setter_no": r.setter_no,
            "no_trays": _s(r.no_trays),
            "tray_size": _s(r.tray_size),
            "total_eggs": _s(r.total_eggs),
        } for r in o.egg_intakes.all()],
        "hatcher_outputs": [{
            "hatcher_no": r.hatcher_no,
            "infertile_qty": _s(r.infertile_qty),
            "early_dead_qty": _s(r.early_dead_qty),
            "blasting_qty": _s(r.blasting_qty),
            "transfer_qty": _s(r.transfer_qty),
            "dead_in_shell_qty": _s(r.dead_in_shell_qty),
            "culls_malf_qty": _s(r.culls_malf_qty),
            "saleable_chicks": _s(r.saleable_chicks),
        } for r in o.hatcher_outputs.all()],
        "sales_lines": [{
            "trader_customer_name": r.trader_customer_name,
            "chicks_sold": _s(r.chicks_sold),
            "discount_percent": _s(r.discount_percent),
            "free_chicks": _s(r.free_chicks),
            "billed_chicks": _s(r.billed_chicks),
            "rate": _s(r.rate),
            "total_amount": _s(r.total_amount),
            "payment_status": r.payment_status,
            "delivery_notes": r.delivery_notes or "",
        } for r in o.sales_lines.all()],
    }


HatchSettingWriteView = _make_write_view(web.HatchSettingAPI, HatchSetting, _load_hatch_setting)


def write_urls() -> list:
    """URL patterns for the hatchery document write endpoints."""
    return [
        path("hatchery/egg-purchases/save", EggPurchaseWriteView.as_view(),
             name="hatchery-egg-purchases-save-new"),
        path("hatchery/egg-purchases/save/<int:pk>", EggPurchaseWriteView.as_view(),
             name="hatchery-egg-purchases-save"),
        path("hatchery/hatch-settings/save", HatchSettingWriteView.as_view(),
             name="hatchery-hatch-settings-save-new"),
        path("hatchery/hatch-settings/save/<int:pk>", HatchSettingWriteView.as_view(),
             name="hatchery-hatch-settings-save"),
    ]
