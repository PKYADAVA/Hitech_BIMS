"""Hatchery domain — mobile API v1 resources.

Same one-line pattern as ``broiler/api.py``. Parent transactions are full-CRUD
cursor feeds; their line-item tables are registered as their own resources and
filtered from the client with the base layer's generic ``?<fk>=<id>`` filter
(e.g. ``/api/v1/hatchery/egg-purchase-items?egg_purchase=42``), so no bespoke
nested serializers are needed for a first release.

Registered under ``/api/v1/hatchery/…`` by :func:`register`.
"""
from __future__ import annotations

from api.viewsets import register_model
from hatchery_master.models import ExpenseType, Hatcher, Hatchery, HatcheryExpense, Setter

from .models import (
    ChangeRequest,
    ChickSale,
    ChickSaleItem,
    DeliveryChallan,
    DeliveryChallanItem,
    EggGrading,
    EggPurchase,
    EggPurchaseItem,
    HatchEntry,
    HatchSetting,
    TraySetting,
)


def register(router) -> None:
    # --- Settings / operational records (full CRUD) ---------------------
    register_model(router, "hatchery/hatch-settings", HatchSetting,
                   search_fields=["setting_no", "batch_flock_no", "supplier_name"])
    register_model(router, "hatchery/tray-settings", TraySetting,
                   search_fields=["setting_no", "loaded_by"])

    # --- Hatchery master data (full CRUD; list also serves as pickers) --
    register_model(router, "hatchery/hatcheries", Hatchery,
                   search_fields=["hatchery_name", "owner_name"], ordering=["hatchery_name"])
    register_model(router, "hatchery/setters", Setter,
                   search_fields=["setter_no"], ordering=["setter_no"])
    register_model(router, "hatchery/hatchers", Hatcher,
                   search_fields=["hatcher_no"], ordering=["hatcher_no"])
    register_model(router, "hatchery/expense-types", ExpenseType,
                   search_fields=["name"], ordering=["name"])

    # --- Transactions (full CRUD, cursor feeds) -------------------------
    register_model(router, "hatchery/egg-purchases", EggPurchase, cursor=True)
    register_model(router, "hatchery/egg-gradings", EggGrading, cursor=True)
    register_model(router, "hatchery/delivery-challans", DeliveryChallan, cursor=True)
    register_model(router, "hatchery/hatch-entries", HatchEntry, cursor=True)
    register_model(router, "hatchery/chick-sales", ChickSale, cursor=True)
    register_model(router, "hatchery/expenses", HatcheryExpense, cursor=True)

    # --- Line items (CRUD; filter by parent via ?<fk>=<id>) -------------
    register_model(router, "hatchery/egg-purchase-items", EggPurchaseItem)
    register_model(router, "hatchery/delivery-challan-items", DeliveryChallanItem)
    register_model(router, "hatchery/chick-sale-items", ChickSaleItem)

    # --- Change-request approval queue (read-only) ----------------------
    register_model(router, "hatchery/change-requests", ChangeRequest, read_only=True,
                   search_fields=["object_label", "module"], ordering=["-id"])


# --- Change-request review action (mobile) ---------------------------------
from django.db import transaction  # noqa: E402
from django.utils import timezone  # noqa: E402
from rest_framework.exceptions import (  # noqa: E402
    NotFound,
    PermissionDenied,
    ValidationError,
)
from rest_framework.permissions import IsAuthenticated  # noqa: E402
from rest_framework.response import Response  # noqa: E402
from rest_framework.views import APIView  # noqa: E402

from api.viewsets import V1ViewMixin  # noqa: E402

from .models import ChangeRequest  # noqa: E402


class TraySettingLookupView(V1ViewMixin, APIView):
    """GET /hatchery/tray-setting-lookup?tray_setting=<id> — the setting's dates
    and its source purchase figures (net qty/rate/amount), for the Hatch Entry
    form's auto-filled Eggs Total / Egg Rate / Hatch Date. Mirrors
    ``applySetting()`` in the web ``hatch_entry_form``."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        ts_id = request.query_params.get("tray_setting")
        ts = (TraySetting.objects
              .filter(id=ts_id)
              .select_related("grading__purchase_invoice")
              .first() if ts_id else None)
        if not ts:
            return Response({})

        inv = getattr(getattr(ts, "grading", None), "purchase_invoice", None)

        def _num(fn):
            try:
                return str(fn())
            except Exception:
                return "0"

        return Response({
            "setting_date": ts.setting_date.isoformat() if ts.setting_date else None,
            "hatch_date": ts.hatch_date.isoformat() if ts.hatch_date else None,
            "eggs_total": _num(inv.net_quantity) if inv else "0",
            "egg_rate": _num(inv.net_rate) if inv else "0",
            "eggs_amount": _num(inv.net_amount) if inv else "0",
            "eggs_set": _num(ts.total_eggs_set),
        })


class ChangeRequestReviewView(V1ViewMixin, APIView):
    """POST /hatchery/change-requests/<id>/<approve|reject> — apply the web's
    review logic (permission check + apply payload on approve)."""

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, pk, decision):
        # Lazy imports: the web views module is heavy and only needed here.
        from user.access import user_can
        from .views import CHANGE_REQUEST_HANDLERS

        cr = ChangeRequest.objects.filter(pk=pk).first()
        if not cr:
            raise NotFound("Change request not found.")
        if cr.status != "pending":
            raise ValidationError("This request has already been reviewed.")
        handler = CHANGE_REQUEST_HANDLERS.get(cr.module)
        if not handler:
            raise ValidationError("Unknown module for change request.")
        if not user_can(request.user, handler["tab"], cr.action):
            raise PermissionDenied("You do not have permission to review this request.")

        if decision == "approve":
            obj = handler["model"].objects.filter(id=cr.object_id).first()
            if obj is None:
                raise ValidationError("The record no longer exists.")
            if cr.action == "delete":
                # See hatchery/change_requests.py's ChangeRequestReviewAPI for
                # why this isn't a plain obj.delete() — a stock-bearing
                # document needs its recompute chain re-run afterward.
                delete_fn = handler.get("delete")
                if delete_fn:
                    delete_fn(obj)
                else:
                    obj.delete()
            else:
                handler["save"](cr.payload, cr.object_id)
            cr.status = "approved"
        elif decision == "reject":
            cr.status = "rejected"
        else:
            raise ValidationError("Invalid decision.")

        cr.reviewed_by = request.user
        cr.reviewed_at = timezone.now()
        cr.review_note = str(request.data.get("review_note") or "")
        cr.save()
        return Response({"status": cr.status, "id": cr.id})


class ChangeRequestCreateView(V1ViewMixin, APIView):
    """POST /hatchery/change-requests/create — a phone's way in to the same
    workflow the web's /change_request_api/ offers: {module, object_id,
    action, payload?, note?}. Kept separate from the read-only
    hatchery/change-requests list (register_model) and from the web's own
    endpoint (session + CSRF, not JWT) rather than trying to share either."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        from user.access import user_can

        from .change_requests import CHANGE_REQUEST_HANDLERS

        data = request.data
        handler = CHANGE_REQUEST_HANDLERS.get(data.get("module"))
        if not handler:
            raise ValidationError("Unknown module for change request.")
        if not user_can(request.user, handler["tab"], "view"):
            raise PermissionDenied("You do not have access to this module.")
        action = data.get("action")
        if action not in ("edit", "delete"):
            raise ValidationError("Invalid action.")
        obj = handler["model"].objects.filter(id=data.get("object_id")).first()
        if obj is None:
            raise NotFound("Record not found.")
        if action == "edit" and not data.get("payload"):
            raise ValidationError("No proposed changes supplied.")
        cr = ChangeRequest.objects.create(
            module=data["module"], object_id=obj.id,
            object_label=handler["number"](obj),
            action=action,
            payload=data.get("payload") if action == "edit" else None,
            note=str(data.get("note") or ""),
            requested_by=request.user,
        )
        return Response({"id": cr.id, "message": "Change request submitted for approval."}, status=201)
