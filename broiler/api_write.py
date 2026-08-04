"""Broiler document write endpoints for the mobile API v1.

Same approach as ``inventory.api_write``, and it imports that module's
machinery rather than restating it: each view hands the JWT-authenticated
request to the web module's own ``*API`` view, so a phone save runs the
identical validation, running-stock calculation and chain recompute the web
form runs. A second copy of that arithmetic is exactly what would drift.

Medicine/Vaccine Consumption is a *document*, not a row: one supervisor and
one date over many entry rows, which is the shape the web API already accepts
(``{"supervisor": id, "date": iso, "rows": [...]}``) and the shape the phone's
form has. Posting rows one at a time would work for the first row and corrupt
the rest — ``stock`` is a running balance, so each row's value depends on the
ones saved before it, and the chain is recomputed once at the end.

Mounted under ``/api/v1/broiler/medicine-entries/save[/<id>]``.
"""
from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.urls import path
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.viewsets import V1ViewMixin
from inventory.api_write import _make_write_view, _s

from . import views as web
from .models import FarmLocationCapture, MedicineVaccineEntry


def _load_medicine_entry(o) -> dict:
    """An existing entry in the shape the phone's form fields use."""
    return {
        "supervisor": _s(o.supervisor_id),
        "date": _s(o.date),
        "rows": [{
            "id": o.id,
            "farm": _s(o.farm_id),
            "batch": _s(o.batch_id),
            "age_days": _s(o.age_days),
            "item": _s(o.item_id),
            "qty": _s(o.qty),
            "stock": _s(o.stock),
            "remarks": o.remarks or "",
        }],
    }


MedicineEntryWriteView = _make_write_view(
    web.MedicineEntryAPI, MedicineVaccineEntry, _load_medicine_entry)


class _CaptureRequest:
    """What ``_save_capture`` reads off a request, taken from a DRF one.

    The web view reads ``request.POST`` and ``request.FILES`` directly. Under
    DRF those are not the same object — the multipart body has already been
    parsed into ``request.data``, and touching the underlying Django request's
    ``POST`` afterwards raises rather than re-reading a consumed stream. This
    presents the DRF values under the names the web code expects, so that code
    is reused as it stands rather than copied and left to drift.
    """

    def __init__(self, request):
        self.POST = request.data
        self.FILES = request.FILES
        self.user = request.user


class FarmLocationCaptureWriteView(V1ViewMixin, APIView):
    """POST /api/v1/broiler/location-captures/save[/<id>] — create or update.

    Multipart, because a capture is the photos and scans as much as the pin:
    farm pictures and other documents take any number of files, and each master
    slot (PAN, Aadhar, cheques…) takes one. ``_save_capture`` places them and
    mirrors them onto the farm and farmer masters; doing that here again is
    exactly the copy that would drift.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    @transaction.atomic
    def post(self, request, pk=None):
        if pk is None:
            instance = FarmLocationCapture()
        else:
            instance = FarmLocationCapture.objects.filter(pk=pk).first()
            if instance is None:
                raise NotFound("Farm location capture not found.")
        if pk is not None:
            # A saved capture keeps the farm it was taken at. Saving pushes the
            # pin and address onto the farm master (sync_farm), so re-pointing
            # one at a different farm stamps this visit's location onto a farm
            # nobody visited and leaves the visited one holding a reading with
            # nothing behind it. The phone locks the picker; this is the rule
            # itself, for anything that does not.
            sent = str(request.data.get("farm") or "")
            if sent and sent != str(instance.farm_id):
                raise ValidationError(
                    {"farm": "A capture cannot be moved to a different farm. "
                             "Record a new capture against that farm instead."})

        try:
            saved = web._save_capture(_CaptureRequest(request), instance)
        except DjangoValidationError as exc:
            raise ValidationError(getattr(exc, "message_dict", None) or exc.messages)
        return Response(
            {"id": saved.id, "capture_no": saved.capture_no},
            status=201 if pk is None else 200)


def write_urls() -> list:
    """URL patterns for the broiler document write endpoints."""
    return [
        path("broiler/location-captures/save",
             FarmLocationCaptureWriteView.as_view(), name="broiler-captures-save-new"),
        path("broiler/location-captures/save/<int:pk>",
             FarmLocationCaptureWriteView.as_view(), name="broiler-captures-save"),
        path("broiler/medicine-entries/save", MedicineEntryWriteView.as_view(),
             name="broiler-medicine-entries-save-new"),
        path("broiler/medicine-entries/save/<int:pk>", MedicineEntryWriteView.as_view(),
             name="broiler-medicine-entries-save"),
    ]
