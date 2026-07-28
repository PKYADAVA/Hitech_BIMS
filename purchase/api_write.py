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

    def __init__(self, post: dict, user):
        self.POST = post
        self.FILES = {}
        self.user = user
        self.method = "POST"


def _messages(exc: DjangoValidationError) -> str:
    return " ".join(exc.messages) if hasattr(exc, "messages") else str(exc)


def _write_document(spec, request, instance=None) -> Response:
    """Apply header + line items using the web helpers, inside one transaction."""
    model, apply_fn, save_lines_fn, lines_key, exclude, require_line = spec
    data = dict(request.data)
    # The helpers read the lines as a JSON string under a specific POST key.
    lines = data.pop("items", None)
    if lines is None:
        lines = data.pop("lines", None)
    post = {k: ("" if v is None else v) for k, v in data.items()}
    post[lines_key] = json.dumps(lines or [])

    shim = _ShimRequest(post, request.user)
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
    model = spec[0]

    class _WriteView(V1ViewMixin, APIView):
        permission_classes = [IsAuthenticated]

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


# spec = (model, apply_fn, save_lines_fn, lines_post_key, clean_exclude, require_line)
_GENERAL = (GeneralPurchase, web._apply_posted_general_purchase_fields,
            web._save_general_purchase_items, "items_json", ["purchase_no"], False)
_CHICKS = (ChicksPurchase, web._apply_posted_chicks_purchase_fields,
           web._save_chicks_purchase_items, "items_json", ["purchase_no"], False)
_PAYMENT = (SupplierPayment, web._apply_posted_payment_fields,
            web._save_payment_lines, "lines_json", ["payment_no"], True)

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
