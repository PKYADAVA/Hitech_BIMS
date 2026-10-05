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

from api.permissions import MatrixPermission
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
    """Everything on the row, because that is where the form renders it.

    A stock transfer's phone form carries date, DC number, both locations and
    the logistics on the row, as the web grid does — one sheet moves different
    items between different pairs of stores. This returned them under "header"
    instead, so opening a transfer to edit it showed From Location and To
    Location empty on a record that plainly had both, and saving would have
    sent those blanks back. Nothing reads a header for this document now.
    """
    return {
        "header": {},
        "items": [{
            "date": _s(o.date), "dc_no": o.dc_no or "",
            "item": _s(o.item_id), "quantity": _s(o.quantity),
            "rate": _s(o.rate),
            "from_type": o.from_location_type or "warehouse",
            "from_id": _s(o.from_warehouse_id or o.from_farm_id),
            "from_batch": _s(o.from_batch_id),
            "to_type": o.to_location_type or "warehouse",
            "to_id": _s(o.to_warehouse_id or o.to_farm_id),
            "to_batch": _s(o.to_batch_id),
            "vehicle_no": o.vehicle_no or "", "driver_name": o.driver_name or "",
            "remarks": o.remarks or "",
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
    #
    # A caller may pass a stand-in instead — a web view that reads
    # ``request.POST`` cannot be handed a JSON request, because ``POST`` is
    # empty for a JSON body and reading it after DRF has parsed one raises.
    # Such a shim is already the Django request, so there is nothing to unwrap.
    django_request = getattr(request, "_request", request)
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
    urls.extend(_transfer_charge_urls())
    return urls


# --------------------------------------------------------------------------
# Transfer Charges — same delegation shape as account.api_write, matrix-gated
# on the web register's own tab rather than bare IsAuthenticated: unlike the
# five write views above (gated only by login), a Transfer Charge has its own
# tab in the Web-Access matrix, so the phone is held to it too.
# --------------------------------------------------------------------------

from .models import TransferChargeHeader  # noqa: E402
from .services import transfer_charges as tc_service  # noqa: E402


def _tc_delegate(bound_method, request, *args) -> Response:
    """``_delegate``, but for the plain Django views Transfer Charges uses
    (``@login_required`` functions and a non-DRF ``View``) rather than a web
    ``*API`` class's bound method -- same envelope either way."""
    django_request = getattr(request, "_request", request)
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


class _TransferChargeView(V1ViewMixin, APIView):
    permission_classes = [IsAuthenticated, MatrixPermission]
    tab_code = "transfer_charge_list"


class TransferChargeListView(_TransferChargeView):
    """The register's rows — the same filters the web list page takes."""

    def get(self, request):
        return _tc_delegate(web.TransferChargeAPI().get, request)


class TransferChargeMastersView(_TransferChargeView):
    """Everything the Add Transfer Charges screen's pickers hold.

    Branches and farms come scoped the way Petty Expense's own masters are —
    through ``farms_for``/``branches_for`` — because a Transfer Charge is also
    gated by Web-Access farm/branch scope, not by the (unscoped) matrix tab
    alone.
    """

    def get(self, request):
        from broiler.models import Branch, BroilerFarm
        from user.services.scoping import branches_for, farms_for

        return Response({
            "charge_types": web._charge_type_options(),
            "branches": list(branches_for(request.user, Branch.objects.order_by("branch_name"))
                             .values("id", "branch_name")),
            "farms": list(farms_for(request.user, BroilerFarm.objects.order_by("farm_name"))
                          .values("id", "farm_name", "branch_id")),
            "statuses": [c[0] for c in TransferChargeHeader.STATUS_CHOICES],
            "treatments": [c[0] for c in TransferChargeHeader.TREATMENT_CHOICES],
            "payment_modes": [c[0] for c in TransferChargeHeader.PAYMENT_MODE_CHOICES],
            "allocation_methods": [c[0] for c in web.TransferChargeLine.METHOD_CHOICES],
            "scopes": [c[0] for c in web.TransferChargeLine.SCOPE_CHOICES],
            "bank_cash_accounts": list(web.BankCashMaster.objects.order_by("name")
                                       .values("id", "name", "is_cash")),
            "payable_accounts": tc_service.payable_accounts(),
        })


class TransferChargeDetailView(_TransferChargeView):
    def get(self, request, pk):
        return _tc_delegate(web.TransferChargeAPI().get, request, pk)

    def delete(self, request, pk):
        return _tc_delegate(web.TransferChargeAPI().delete, request, pk)


class TransferChargeSaveView(_TransferChargeView):
    """Save a draft, submit for approval, or save and post, exactly as the
    web form's three buttons do -- ``submit_for_approval``/``action: "post"``
    in the body are the web form's own flags, carried through unchanged."""

    def post(self, request, pk=None):
        if pk is None:
            return _tc_delegate(web.TransferChargeAPI().post, request)
        return _tc_delegate(web.TransferChargeAPI().put, request, pk)


class TransferChargeStockTransferLookupView(_TransferChargeView):
    """Trip search: a Stock Transfer row group by ``dc_no`` + date, exactly
    as the web Add screen's Step 1 picker searches it."""

    def get(self, request):
        return _tc_delegate(web.transfer_charge_stock_transfer_lookup, request)


class TransferChargeNextNumberView(_TransferChargeView):
    def get(self, request):
        return _tc_delegate(web.transfer_charge_next_number_preview, request)


class TransferChargeAllocatePreviewView(_TransferChargeView):
    """Live allocation math for a Common line, straight from the engine --
    never recomputed here, so the screen can never show a number the save
    would not also produce."""

    def post(self, request):
        return _tc_delegate(web.transfer_charge_allocate_preview, request)


class TransferChargePostView(_TransferChargeView):
    def post(self, request, pk):
        return _tc_delegate(web.transfer_charge_post, request, pk)


class TransferChargeCancelView(_TransferChargeView):
    def post(self, request, pk):
        return _tc_delegate(web.transfer_charge_cancel, request, pk)


class TransferChargeAttachView(_TransferChargeView):
    """Bills, Bilty/LR and toll receipts, photographed at the counter --
    multipart, so the request goes through unparsed and the web view reads
    ``request.FILES`` itself, same as Petty Expense's own attach view."""

    def get(self, request, pk):
        return _tc_delegate(web.transfer_charge_attachments, request, pk)

    def post(self, request, pk):
        return _tc_delegate(web.transfer_charge_attachments, request, pk)

    def delete(self, request, pk, attachment_id):
        return _tc_delegate(web.transfer_charge_attachment_delete, request, pk, attachment_id)


def _transfer_charge_urls() -> list:
    return [
        path("inventory/transfer-charges/rows", TransferChargeListView.as_view(),
             name="inventory-transfer-charges-rows"),
        path("inventory/transfer-charges/masters", TransferChargeMastersView.as_view(),
             name="inventory-transfer-charges-masters"),
        path("inventory/transfer-charges/next-number", TransferChargeNextNumberView.as_view(),
             name="inventory-transfer-charges-next-number"),
        path("inventory/transfer-charges/stock-transfer-lookup",
             TransferChargeStockTransferLookupView.as_view(),
             name="inventory-transfer-charges-stock-transfer-lookup"),
        path("inventory/transfer-charges/allocate-preview",
             TransferChargeAllocatePreviewView.as_view(),
             name="inventory-transfer-charges-allocate-preview"),
        path("inventory/transfer-charges/save", TransferChargeSaveView.as_view(),
             name="inventory-transfer-charges-save-new"),
        path("inventory/transfer-charges/save/<int:pk>", TransferChargeSaveView.as_view(),
             name="inventory-transfer-charges-save"),
        path("inventory/transfer-charges/<int:pk>", TransferChargeDetailView.as_view(),
             name="inventory-transfer-charges-detail"),
        path("inventory/transfer-charges/<int:pk>/post", TransferChargePostView.as_view(),
             name="inventory-transfer-charges-post"),
        path("inventory/transfer-charges/<int:pk>/cancel", TransferChargeCancelView.as_view(),
             name="inventory-transfer-charges-cancel"),
        path("inventory/transfer-charges/<int:pk>/attach", TransferChargeAttachView.as_view(),
             name="inventory-transfer-charges-attach"),
        path("inventory/transfer-charges/<int:pk>/attach/<int:attachment_id>",
             TransferChargeAttachView.as_view(),
             name="inventory-transfer-charges-detach"),
    ]
