"""Sales transaction write endpoints for the mobile API v1.

Two shapes, both reusing the web posting logic:

* **Sales Invoice** — the web view is form-POST + redirect, so we reuse its
  posting helpers (``_apply_posted_invoice`` / ``_save_invoice_items``, which
  compute per-line taxable + GST and the net amount) via a small request shim.
* **Sales Receipt** — the web ``SalesReceiptAPI`` is already a JSON API, so we
  delegate to it directly (injecting the JWT user), reusing its whole
  create/update/delete path verbatim.

Mounted under ``/api/v1/sales/<txn>/save[/<id>]`` by ``api/urls.py``.
"""
from __future__ import annotations

import json

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import ProtectedError
from django.http import Http404 as DjangoHttp404
from django.urls import path
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.viewsets import V1ViewMixin

from . import views as web
from .models import SalesInvoice, SalesReceipt


def _s(v) -> str:
    if v is None:
        return ""
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


def _load_invoice(o) -> dict:
    return {
        "header": {
            "date": _s(o.date), "customer": _s(o.customer_id),
            "reference_no": o.reference_no or "", "place_of_supply": o.place_of_supply or "",
            "vehicle_no": o.vehicle_no or "", "other_charges_amount": _s(o.other_charges_amount),
            "remarks": o.remarks or "",
        },
        "items": [{
            "item": _s(i.item_id), "uom": i.uom or "", "quantity": _s(i.quantity),
            "free_qty": _s(i.free_qty), "rate": _s(i.rate),
            "discount_percent": _s(i.discount_percent), "gst_percent": _s(i.gst_percent),
            "batch_no": i.batch_no or "", "hsn_sac": i.hsn_sac or "",
        } for i in o.items.all()],
    }


def _load_receipt(o) -> dict:
    return {
        "header": {"date": _s(o.date), "location": _s(o.location_id)},
        "items": [{
            "customer": _s(o.customer_id), "mode": o.mode or "Cash",
            "receipt_account": _s(o.receipt_account_id), "amount": _s(o.amount),
            "reference_no": o.reference_no or "", "remarks": o.remarks or "",
        }],
    }


class _ShimRequest:
    """Stand-in Django request for the invoice posting helpers (they read
    ``.POST`` and ``.POST['items_json']`` only)."""

    def __init__(self, post: dict, user):
        self.POST = post
        self.FILES = {}
        self.user = user
        self.method = "POST"


def _messages(exc: DjangoValidationError) -> str:
    return " ".join(exc.messages) if hasattr(exc, "messages") else str(exc)


# --- Sales Invoice: reuse the web posting helpers via a shim ---------------

def _write_invoice(request, instance=None) -> Response:
    data = dict(request.data)
    items = data.pop("items", None)
    post = {k: ("" if v is None else v) for k, v in data.items()}
    post["items_json"] = json.dumps(items or [])
    shim = _ShimRequest(post, request.user)

    inst = instance or SalesInvoice(
        created_by=request.user if request.user.is_authenticated else None)
    try:
        web._apply_posted_invoice(inst, shim)
        if not inst.customer_id:
            raise DjangoValidationError("Select a customer.")
        inst.full_clean(exclude=["invoice_no"])
        with transaction.atomic():
            inst.save()
            web._save_invoice_items(inst, shim)
            if not inst.items.exists():
                raise DjangoValidationError("Add at least one item.")
    except DjangoValidationError as exc:
        raise ValidationError(_messages(exc))
    return Response({"id": inst.id, "message": "Sales Invoice saved."}, status=201)


class SalesInvoiceWriteView(V1ViewMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        instance = SalesInvoice.objects.prefetch_related("items").filter(pk=pk).first()
        if not instance:
            raise NotFound("Sales Invoice not found.")
        return Response(_load_invoice(instance))

    def post(self, request):
        return _write_invoice(request)

    def put(self, request, pk):
        instance = SalesInvoice.objects.filter(pk=pk).first()
        if not instance:
            raise NotFound("Sales Invoice not found.")
        return _write_invoice(request, instance=instance)

    def delete(self, request, pk):
        instance = SalesInvoice.objects.filter(pk=pk).first()
        if not instance:
            raise NotFound("Sales Invoice not found.")
        try:
            instance.delete()
        except ProtectedError:
            raise ValidationError("Cannot delete: this invoice is referenced elsewhere.")
        return Response({"deleted": True})


# --- Sales Receipt: delegate to the existing JSON web API ------------------

def _delegate(bound_method, request, *args) -> Response:
    django_request = request._request
    django_request.user = request.user
    try:
        resp = bound_method(django_request, *args)
    except DjangoHttp404 as exc:
        raise NotFound(str(exc) or "Receipt not found.")
    payload = json.loads(resp.content or b"{}")
    if resp.status_code >= 400:
        detail = payload.get("error") if isinstance(payload, dict) else None
        raise ValidationError(detail or payload or "Could not save.")
    return Response(payload, status=resp.status_code)


class SalesReceiptWriteView(V1ViewMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        instance = SalesReceipt.objects.filter(pk=pk).first()
        if not instance:
            raise NotFound("Receipt not found.")
        return Response(_load_receipt(instance))

    def post(self, request):
        return _delegate(web.SalesReceiptAPI().post, request)

    def put(self, request, pk):
        return _delegate(web.SalesReceiptAPI().put, request, pk)

    def delete(self, request, pk):
        return _delegate(web.SalesReceiptAPI().delete, request, pk)


def write_urls() -> list:
    views = [("invoices", SalesInvoiceWriteView), ("receipts", SalesReceiptWriteView)]
    urls = []
    for suffix, view in views:
        urls.append(path(f"sales/{suffix}/save", view.as_view(), name=f"sales-{suffix}-save-new"))
        urls.append(path(f"sales/{suffix}/save/<int:pk>", view.as_view(), name=f"sales-{suffix}-save"))
    return urls
