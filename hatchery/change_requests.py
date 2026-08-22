"""Change-request infrastructure shared across the whole ERP.

A user who lacks the edit/delete right on a transaction tab can still raise
a request for one; a user who holds the right reviews and applies it. The
``ChangeRequest`` model (hatchery/models.py) is deliberately generic — it
carries a ``module`` string rather than a model FK — because the workflow
does not belong to hatchery, only its first seven modules happened to.

Each module registers itself into ``CHANGE_REQUEST_HANDLERS`` from its own
app's views.py (import this module, then assign a key), rather than this
file importing every app's models — that would make every transaction
module a hard dependency of hatchery, the wrong way round.
"""
import json
import logging

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone as _tz
from django.utils.decorators import method_decorator
from django.views import View

from user.access import user_can

from .models import ChangeRequest

logger = logging.getLogger(__name__)

#: module key -> handler dict. Populated by every app's views.py at import
#: time (Django loads every app's views before the first request, via
#: urls.py's own imports, so lookups here — which only ever happen at
#: request time — always see every app's registrations).
#:
#: Handler shape: {
#:     "api": "/foo_api/",              # GET <api><id>/ loads the current record
#:     "label": "Human Name",
#:     "tab": "foo_list",                # permission tab_code reviewed against
#:     "model": FooModel,
#:     "save": lambda data, oid: FooAPI()._save(data, oid),
#:     "number": lambda obj: obj.display_field,
#: }
CHANGE_REQUEST_HANDLERS = {}


class BaseAPIView(View):
    """Same error-handling shape as hatchery.views.BaseAPIView, duplicated
    rather than imported so this module never has to import hatchery.views
    (which imports every transaction app right back)."""

    def handle_exception(self, e: Exception) -> JsonResponse:
        logger.error(f"Error in {self.__class__.__name__}: {str(e)}", exc_info=True)
        if isinstance(e, ValidationError):
            message = " ".join(e.messages) if hasattr(e, "messages") else str(e)
            return JsonResponse({"error": message}, status=400)
        return JsonResponse({"error": "An unexpected error occurred."}, status=500)


@method_decorator(login_required, name="dispatch")
class ChangeRequestListTemplateView(View):
    def get(self, request):
        return render(request, "change_request_list.html")


def _change_request_to_dict(cr, user):
    handler = CHANGE_REQUEST_HANDLERS.get(cr.module, {})
    return {
        "id": cr.id, "module": cr.module, "module_label": handler.get("label", cr.module),
        "object_id": cr.object_id, "object_label": cr.object_label,
        "action": cr.action, "action_label": cr.get_action_display(),
        "status": cr.status, "note": cr.note,
        "payload": cr.payload,
        "requested_by": cr.requested_by.username,
        "requested_at": _tz.localtime(cr.requested_at).strftime("%Y-%m-%d %H:%M"),
        "reviewed_by": cr.reviewed_by.username if cr.reviewed_by else "",
        "reviewed_at": _tz.localtime(cr.reviewed_at).strftime("%Y-%m-%d %H:%M") if cr.reviewed_at else "",
        "review_note": cr.review_note,
        "can_review": user_can(user, handler.get("tab", ""), cr.action) if handler else False,
        "detail_api": handler.get("api", ""),
    }


@method_decorator(login_required, name="dispatch")
class ChangeRequestAPI(BaseAPIView):
    @staticmethod
    def _fk_labels():
        """id -> human label per payload field name, so the diff viewer can show
        names instead of raw foreign-key ids (both current and proposed sides).

        Extended by each module as it registers — a field name absent here
        just shows its raw id, so leaving one out is never a hard failure.
        """
        from account.models import ChartOfAccount
        from broiler.models import BroilerBatch, BroilerFarm
        from hatchery_master.models import Hatchery, Setter
        from inventory.models import Item, Warehouse
        from purchase.models import Supplier
        from sales.models import Customer

        from .models import DeliveryChallan, EggGrading, EggPurchase, TraySetting

        items = {str(i.id): f"{i.item_code} - {i.description}" for i in Item.objects.all()}
        warehouses = {str(w.id): w.name for w in Warehouse.objects.all()}
        accounts = {str(a.id): f"{a.code} - {a.description}" for a in ChartOfAccount.objects.all()}
        return {
            "supplier": {str(s.id): s.name for s in Supplier.objects.all()},
            "customer": {str(c.id): c.name for c in Customer.objects.all()},
            "warehouse": warehouses,
            "storage_location": warehouses,
            "item": items,
            "hatch_item": items,
            "pay_account": accounts,
            "freight_account": accounts,
            "chart_of_account": accounts,
            "hatchery": {str(h.id): h.hatchery_name for h in Hatchery.objects.all()},
            "setter": {str(s.id): s.setter_no for s in Setter.objects.all()},
            "grading": {str(g.id): g.transaction_no for g in EggGrading.objects.all()},
            "purchase_invoice": {str(p.id): p.transaction_no for p in EggPurchase.objects.all()},
            "tray_setting": {str(t.id): t.setting_no for t in TraySetting.objects.all()},
            "delivery_challan": {str(d.id): d.challan_no for d in DeliveryChallan.objects.all()},
            "farm": {str(f.id): f.farm_name for f in BroilerFarm.objects.all()},
            "batch": {str(b.id): b.batch_name for b in BroilerBatch.objects.all()},
        }

    def get(self, request):
        try:
            requests_qs = ChangeRequest.objects.select_related("requested_by", "reviewed_by").all()[:300]
            return JsonResponse({
                "requests": [_change_request_to_dict(cr, request.user) for cr in requests_qs],
                "labels": self._fk_labels(),
            })
        except Exception as e:
            return self.handle_exception(e)

    def post(self, request):
        """Create a change request: {module, object_id, action, payload?, note?}."""
        try:
            data = json.loads(request.body)
            handler = CHANGE_REQUEST_HANDLERS.get(data.get("module"))
            if not handler:
                raise ValidationError("Unknown module for change request.")
            if not user_can(request.user, handler["tab"], "view"):
                raise ValidationError("You do not have access to this module.")
            action = data.get("action")
            if action not in ("edit", "delete"):
                raise ValidationError("Invalid action.")
            obj = get_object_or_404(handler["model"], id=data.get("object_id"))
            if action == "edit" and not data.get("payload"):
                raise ValidationError("No proposed changes supplied.")
            cr = ChangeRequest.objects.create(
                module=data["module"], object_id=obj.id,
                object_label=handler["number"](obj),
                action=action,
                payload=data.get("payload") if action == "edit" else None,
                note=data.get("note") or "",
                requested_by=request.user,
            )
            return JsonResponse({"id": cr.id, "message": "Change request submitted for approval."}, status=201)
        except Exception as e:
            return self.handle_exception(e)


@method_decorator(login_required, name="dispatch")
class ChangeRequestReviewAPI(BaseAPIView):
    """POST /change_request_api/<id>/approve|reject/ — reviewer must hold the
    matching edit/delete right on the target module's tab."""

    @transaction.atomic
    def post(self, request, id, decision):
        try:
            cr = get_object_or_404(ChangeRequest, id=id)
            if cr.status != "pending":
                raise ValidationError("This request has already been reviewed.")
            handler = CHANGE_REQUEST_HANDLERS.get(cr.module)
            if not handler:
                raise ValidationError("Unknown module for change request.")
            if not user_can(request.user, handler["tab"], cr.action):
                return JsonResponse(
                    {"error": "You do not have permission to review this request."}, status=403)
            data = json.loads(request.body) if request.body else {}
            if decision == "approve":
                obj = handler["model"].objects.filter(id=cr.object_id).first()
                if obj is None:
                    raise ValidationError("The record no longer exists.")
                if cr.action == "delete":
                    # A stock-bearing document (Stock Transfer, Medicine
                    # Transfer, …) needs its recompute chain re-run after the
                    # row is gone, using the location/item captured before
                    # the delete — a bare .delete() would leave every later
                    # row's running "stock" column silently stale, with no
                    # signal anywhere that it happened. Handlers without that
                    # concern (every flat-record module so far) just omit
                    # "delete" and get the plain behaviour.
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
            cr.reviewed_at = _tz.now()
            cr.review_note = data.get("review_note") or ""
            cr.save()
            return JsonResponse({"message": f"Request {cr.status}."})
        except Exception as e:
            return self.handle_exception(e)
