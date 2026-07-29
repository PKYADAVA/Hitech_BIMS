"""Inventory transaction write endpoints for the mobile API v1.

These deliberately **reuse the web module's document APIs verbatim**
(``inventory.views``): each mobile view injects the JWT-authenticated user onto
the underlying request and delegates to the same ``post``/``put``/``delete``
methods the web forms call. Every create/edit therefore runs the identical
stock-posting, running-balance recompute, line-item replacement, and validation
as the web — no second (drift-prone) copy of the posting logic lives here.

Mounted under ``/api/v1/inventory/<txn>/save[/<id>]`` by ``api/urls.py``.
"""
from __future__ import annotations

import json

from django.http import Http404 as DjangoHttp404
from django.urls import path
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.viewsets import V1ViewMixin

from . import views as web
from .models import (
    InventoryAdjustment,
    MedicineTransfer,
    StockIssue,
    StockReceive,
    StockTransfer,
)


def _s(v) -> str:
    """Serialize an id/decimal/date to a plain string for the form ('' if None)."""
    if v is None:
        return ""
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


# --- Edit loaders: an existing record → the mobile form's field shape -------

def _load_stock_transfer(o) -> dict:
    return {
        "header": {
            "date": _s(o.date), "dc_no": o.dc_no or "",
            "from_type": o.from_location_type or "warehouse",
            "from_id": _s(o.from_warehouse_id or o.from_farm_id),
            "from_batch": _s(o.from_batch_id),
            "to_type": o.to_location_type or "warehouse",
            "to_id": _s(o.to_warehouse_id or o.to_farm_id),
            "to_batch": _s(o.to_batch_id),
            "vehicle_no": o.vehicle_no or "", "driver_name": o.driver_name or "",
        },
        "items": [{
            "item": _s(o.item_id), "quantity": _s(o.quantity),
            "rate": _s(o.rate), "remarks": o.remarks or "",
        }],
    }


def _load_medicine_transfer(o) -> dict:
    return {
        "header": {
            "date": _s(o.date), "dc_no": o.dc_no or "",
            "from_type": o.from_location_type or "warehouse",
            "from_id": _s(o.from_warehouse_id or o.from_farm_id),
            "from_batch": _s(o.from_batch_id),
            "to_type": o.to_location_type or "warehouse",
            "to_id": _s(o.to_warehouse_id or o.to_farm_id),
            "to_batch": _s(o.to_batch_id),
            "vehicle_no": o.vehicle_no or "", "driver_name": o.driver_name or "",
            "transport_cost": _s(o.transport_cost), "paid_by": _s(o.paid_by_id),
        },
        "items": [{
            "item": _s(i.item_id), "quantity": _s(i.quantity),
            "rate": _s(i.rate), "remarks": i.remarks or "",
        } for i in o.items.all()],
    }


def _load_adjustment(o) -> dict:
    return {
        "header": {
            "date": _s(o.date), "bill_no": o.bill_no or "",
            "loc_type": o.location_type or "warehouse",
            "loc_id": _s(o.warehouse_id or o.farm_id),
            "loc_batch": _s(o.batch_id),
            "chart_of_account": _s(o.chart_of_account_id),
        },
        "items": [{
            "item": _s(i.item_id), "adjustment_type": i.adjustment_type,
            "quantity": _s(i.quantity), "rate": _s(i.rate), "remarks": i.remarks or "",
        } for i in o.items.all()],
    }


def _load_line_location_doc(o) -> dict:
    """Stock issue / receive: header account + per-line location items."""
    return {
        "header": {"date": _s(o.date), "chart_of_account": _s(o.chart_of_account_id)},
        "items": [{
            "item": _s(i.item_id),
            "loc_type": i.location_type or "warehouse",
            "loc_id": _s(i.warehouse_id or i.farm_id),
            "loc_batch": _s(i.batch_id),
            "quantity": _s(i.quantity), "rate": _s(i.rate), "remarks": i.remarks or "",
        } for i in o.items.all()],
    }


def _delegate(bound_method, request, *args) -> Response:
    """Run a web ``*API`` view method as the mobile user, then envelope its
    ``JsonResponse`` as a DRF ``Response`` (turning its 4xx ``{"error": …}``
    into a DRF ``ValidationError`` so the mobile app shows it inline)."""
    # The web views read ``json.loads(request.body)`` and ``request.user``; hand
    # them the raw Django request with the authenticated user attached. We never
    # touch ``request.data`` here, so the body stream stays readable downstream.
    django_request = request._request
    django_request.user = request.user
    try:
        resp = bound_method(django_request, *args)
    except DjangoHttp404 as exc:
        raise NotFound(str(exc) or "Record not found.")

    payload = json.loads(resp.content or b"{}")
    if resp.status_code >= 400:
        detail = payload.get("error") if isinstance(payload, dict) else None
        raise ValidationError(detail or payload or "Could not save.")
    return Response(payload, status=resp.status_code)


def _make_write_view(web_api_cls, model, loader):
    """A mobile create/update/delete view delegating to one web document API,
    plus a GET that returns an existing record in the mobile form's field shape."""

    class _WriteView(V1ViewMixin, APIView):
        permission_classes = [IsAuthenticated]

        def get(self, request, pk):
            obj = (model.objects.prefetch_related("items").filter(pk=pk).first()
                   if hasattr(model, "items") else model.objects.filter(pk=pk).first())
            if not obj:
                raise NotFound(f"{model.__name__} not found.")
            return Response(loader(obj))

        def post(self, request):
            return _delegate(web_api_cls().post, request)

        def put(self, request, pk):
            return _delegate(web_api_cls().put, request, pk)

        def delete(self, request, pk):
            return _delegate(web_api_cls().delete, request, pk)

    _WriteView.__name__ = f"{web_api_cls.__name__}WriteView"
    return _WriteView


StockTransferWriteView = _make_write_view(web.StockTransferAPI, StockTransfer, _load_stock_transfer)
MedicineTransferWriteView = _make_write_view(web.MedicineTransferAPI, MedicineTransfer, _load_medicine_transfer)
InventoryAdjustmentWriteView = _make_write_view(web.InventoryAdjustmentAPI, InventoryAdjustment, _load_adjustment)
StockIssueWriteView = _make_write_view(web.StockIssueAPI, StockIssue, _load_line_location_doc)
StockReceiveWriteView = _make_write_view(web.StockReceiveAPI, StockReceive, _load_line_location_doc)

# Resource path suffix → write view (POST create, PUT/DELETE by id).
_WRITE_VIEWS = [
    ("stock-transfers", StockTransferWriteView),
    ("medicine-transfers", MedicineTransferWriteView),
    ("adjustments", InventoryAdjustmentWriteView),
    ("stock-issues", StockIssueWriteView),
    ("stock-receives", StockReceiveWriteView),
]


def write_urls() -> list:
    """URL patterns for the inventory transaction write endpoints."""
    urls = []
    for suffix, view in _WRITE_VIEWS:
        urls.append(path(f"inventory/{suffix}/save", view.as_view(),
                         name=f"inventory-{suffix}-save-new"))
        urls.append(path(f"inventory/{suffix}/save/<int:pk>", view.as_view(),
                         name=f"inventory-{suffix}-save"))
    return urls
