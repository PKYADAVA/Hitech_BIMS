"""Purchase transaction write endpoints for the mobile API v1.

The web purchase views are form-POST + redirect (not JSON APIs), so we can't
delegate to them wholesale like the inventory ones. Instead we reuse their
**posting helpers verbatim** — ``_apply_posted_*_fields`` and ``_save_*`` (which
read ``request.POST`` / ``request.POST['items_json']`` and compute net amounts) —
by handing them a tiny request shim carrying the mobile JSON as ``.POST``. All
field application, line-item persistence, and net-amount computation therefore
stay identical to the web; only the HTTP envelope differs.

Mounted under ``/api/v1/purchase/<txn>/save[/<id>]`` by ``api/urls.py``.
"""
from __future__ import annotations

import json

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import ProtectedError
from django.urls import path
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.viewsets import V1ViewMixin

from . import views as web
from .models import ChicksPurchase, GeneralPurchase, SupplierPayment


class _ShimRequest:
    """Minimal stand-in for the Django request the web posting helpers expect:
    they only ever touch ``.POST.get(...)`` and ``.FILES.get(...)``."""

    def __init__(self, post: dict, user, files=None):
        self.POST = post
        self.FILES = files if files is not None else {}
        self.user = user
        self.method = "POST"


def _s(v) -> str:
    if v is None:
        return ""
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


# --- Edit loaders: an existing record → the mobile form's field shape -------

def _load_general_purchase(o) -> dict:
    return {
        "header": {
            "purchase_no": o.purchase_no or "",
            "date": _s(o.date), "supplier": _s(o.supplier_id),
            "bill_no": o.bill_no or "", "dc_no": o.dc_no or "",
            "vehicle_no": o.vehicle_no or "", "driver_name": o.driver_name or "",
            "driver_mobile": o.driver_mobile or "",
            "calculation_based_on": o.calculation_based_on or "Sent Quantity",
            "payment_terms": o.payment_terms or "Cash",
            # "Extra" was retired as a value; a header with none recorded is
            # one where nobody said there was any carriage.
            "freight_type": o.freight_type or "No Freight",
            "freight_settlement": o.freight_settlement or "In Purchase Bill",
            "freight_transporter": o.freight_transporter or "",
            "freight_amount": _s(o.freight_amount),
            "payment_mode": o.payment_mode or "pay_later",
            "pay_account": _s(o.pay_account_id), "freight_account": _s(o.freight_account_id),
            "bag_type": o.bag_type or "", "no_of_bags": _s(o.no_of_bags),
            "batch_no": o.batch_no or "", "expiry_date": _s(o.expiry_date),
            "tds_code": o.tds_code or "", "tds_applicable": bool(o.tds_applicable),
            "tds_amount": _s(o.tds_amount),
            "other_charges_account": _s(o.other_charges_account_id),
            "other_charges_type": o.other_charges_type or "Add",
            "other_charges_amount": _s(o.other_charges_amount),
            "round_off_type": o.round_off_type or "Add", "round_off": _s(o.round_off),
            "net_amount": _s(o.net_amount),
            "remarks": o.remarks or "",
            "reference_document_1": o.reference_document_1.url if o.reference_document_1 else None,
            "reference_document_2": o.reference_document_2.url if o.reference_document_2 else None,
            "reference_document_3": o.reference_document_3.url if o.reference_document_3 else None,
        },
        "items": [{
            "item": _s(i.item_id), "unit": i.unit or "",
            "destination": f"farm:{i.farm_id}" if i.farm_id else (f"warehouse:{i.farm_warehouse_id}" if i.farm_warehouse_id else ""),
            "batch": _s(i.batch_id),
            "sent_qty": _s(i.sent_qty), "rcv_qty": _s(i.rcv_qty),
            "free_qty": _s(i.free_qty), "rate": _s(i.rate),
            "discount_percent": _s(i.discount_percent), "discount_amount": _s(i.discount_amount),
            "gst_percent": _s(i.gst_percent),
        } for i in o.items.all()],
    }


def _load_chicks_purchase(o) -> dict:
    return {
        "header": {
            "date": _s(o.date), "supplier": _s(o.supplier_id), "hatchery": _s(o.hatchery_id),
            "item": _s(o.item_id), "bill_no": o.bill_no or "", "dc_no": o.dc_no or "",
            # "Extra" was retired as a value; a header with none recorded is
            # one where nobody said there was any carriage.
            "freight_type": o.freight_type or "No Freight",
            "freight_settlement": o.freight_settlement or "In Purchase Bill",
            "freight_transporter": o.freight_transporter or "",
            "freight_amount": _s(o.freight_amount),
            "remarks": o.remarks or "",
        },
        "items": [{
            "farm_warehouse": _s(i.farm_warehouse_id), "sent_qty": _s(i.sent_qty),
            "mortality": _s(i.mortality), "shortage": _s(i.shortage), "weaks": _s(i.weaks),
            "excess_qty": _s(i.excess_qty), "rate": _s(i.rate), "batch": i.batch or "",
        } for i in o.items.all()],
    }


def _load_payment(o) -> dict:
    return {
        "header": {"date": _s(o.date), "location": _s(o.location_id)},
        "items": [{
            "supplier": _s(ln.supplier_id), "mode": ln.mode or "Cash",
            "pay_account": _s(ln.pay_account_id), "amount": _s(ln.amount),
            "bank_charges": _s(ln.bank_charges), "reference_no": ln.reference_no or "",
            "remarks": ln.remarks or "",
        } for ln in o.lines.all()],
    }


def _messages(exc: DjangoValidationError) -> str:
    return " ".join(exc.messages) if hasattr(exc, "messages") else str(exc)


def _write_document(spec, request, instance=None) -> Response:
    """Apply header + line items using the web helpers, inside one transaction."""
    model, apply_fn, save_lines_fn, lines_key, exclude, require_line = spec[:6]
    # request.data is a QueryDict for a multipart body (file uploads); dict()
    # on it copies the internal multi-value lists verbatim instead of the
    # last-value-per-key a plain POST field is. QueryDict.dict() collapses it
    # correctly. A JSON body is already a plain dict, unaffected either way.
    data = request.data.dict() if hasattr(request.data, "dict") else dict(request.data)
    # The helpers read the lines as a JSON string under a specific POST key.
    lines = data.pop("items", None)
    if lines is None:
        lines = data.pop("lines", None)
    # A multipart body (needed for reference document uploads) can only carry
    # strings, so the mobile client sends the row array pre-stringified — a
    # plain JSON body still hands over a real list, which passes through as-is.
    if isinstance(lines, str):
        try:
            lines = json.loads(lines)
        except json.JSONDecodeError:
            lines = []
    post = {k: ("" if v is None else v) for k, v in data.items()}
    post[lines_key] = json.dumps(lines or [])

    shim = _ShimRequest(post, request.user, request.FILES)
    inst = instance or model()
    try:
        apply_fn(inst, shim)
        inst.full_clean(exclude=exclude)
        with transaction.atomic():
            inst.save()
            save_lines_fn(inst, shim)
            if require_line and not inst.lines.exists():
                raise DjangoValidationError("Add at least one line.")
    except DjangoValidationError as exc:
        raise ValidationError(_messages(exc))
    return Response({"id": inst.id, "message": f"{model.__name__} saved."}, status=201)


def _make_write_view(spec):
    model, loader = spec[0], spec[6]

    class _WriteView(V1ViewMixin, APIView):
        permission_classes = [IsAuthenticated]

        def get(self, request, pk):
            instance = model.objects.filter(pk=pk).first()
            if not instance:
                raise NotFound(f"{model.__name__} not found.")
            return Response(loader(instance))

        def post(self, request):
            return _write_document(spec, request)

        def put(self, request, pk):
            instance = model.objects.filter(pk=pk).first()
            if not instance:
                raise NotFound(f"{model.__name__} not found.")
            return _write_document(spec, request, instance=instance)

        def delete(self, request, pk):
            instance = model.objects.filter(pk=pk).first()
            if not instance:
                raise NotFound(f"{model.__name__} not found.")
            try:
                instance.delete()
            except ProtectedError:
                raise ValidationError("Cannot delete: this record is referenced elsewhere.")
            return Response({"deleted": True})

    _WriteView.__name__ = f"{model.__name__}WriteView"
    return _WriteView


# spec = (model, apply_fn, save_lines_fn, lines_post_key, clean_exclude, require_line, loader)
_GENERAL = (GeneralPurchase, web._apply_posted_general_purchase_fields,
            web._save_general_purchase_items, "items_json", ["purchase_no"], False,
            _load_general_purchase)
_CHICKS = (ChicksPurchase, web._apply_posted_chicks_purchase_fields,
           web._save_chicks_purchase_items, "items_json", ["purchase_no"], False,
           _load_chicks_purchase)
_PAYMENT = (SupplierPayment, web._apply_posted_payment_fields,
            web._save_payment_lines, "lines_json", ["payment_no"], True,
            _load_payment)

GeneralPurchaseWriteView = _make_write_view(_GENERAL)
ChicksPurchaseWriteView = _make_write_view(_CHICKS)
SupplierPaymentWriteView = _make_write_view(_PAYMENT)

_WRITE_VIEWS = [
    ("general-purchases", GeneralPurchaseWriteView),
    ("chicks-purchases", ChicksPurchaseWriteView),
    ("supplier-payments", SupplierPaymentWriteView),
]


def write_urls() -> list:
    urls = []
    for suffix, view in _WRITE_VIEWS:
        urls.append(path(f"purchase/{suffix}/save", view.as_view(),
                         name=f"purchase-{suffix}-save-new"))
        urls.append(path(f"purchase/{suffix}/save/<int:pk>", view.as_view(),
                         name=f"purchase-{suffix}-save"))
    return urls
