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


def _make_write_view(web_api_cls):
    """A mobile create/update/delete view delegating to one web document API."""

    class _WriteView(V1ViewMixin, APIView):
        permission_classes = [IsAuthenticated]

        def post(self, request):
            return _delegate(web_api_cls().post, request)

        def put(self, request, pk):
            return _delegate(web_api_cls().put, request, pk)

        def delete(self, request, pk):
            return _delegate(web_api_cls().delete, request, pk)

    _WriteView.__name__ = f"{web_api_cls.__name__}WriteView"
    return _WriteView


StockTransferWriteView = _make_write_view(web.StockTransferAPI)
MedicineTransferWriteView = _make_write_view(web.MedicineTransferAPI)
InventoryAdjustmentWriteView = _make_write_view(web.InventoryAdjustmentAPI)
StockIssueWriteView = _make_write_view(web.StockIssueAPI)
StockReceiveWriteView = _make_write_view(web.StockReceiveAPI)

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
