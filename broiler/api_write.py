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

from django.urls import path

from inventory.api_write import _make_write_view, _s

from . import views as web
from .models import MedicineVaccineEntry


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


def write_urls() -> list:
    """URL patterns for the broiler document write endpoints."""
    return [
        path("broiler/medicine-entries/save", MedicineEntryWriteView.as_view(),
             name="broiler-medicine-entries-save-new"),
        path("broiler/medicine-entries/save/<int:pk>", MedicineEntryWriteView.as_view(),
             name="broiler-medicine-entries-save"),
    ]
