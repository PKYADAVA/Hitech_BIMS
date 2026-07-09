from typing import Optional
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views import View
from django.http import Http404, JsonResponse
from django.core.exceptions import ValidationError
from django.db import transaction
import json
import logging

from .models import HatchSetting, HatchEggIntake, HatchHatcherOutput, HatchSalesLine

logger = logging.getLogger(__name__)


class BaseAPIView(View):
    """Base class for API views with common error handling."""

    def handle_exception(self, e: Exception) -> JsonResponse:
        logger.error(f"Error in {self.__class__.__name__}: {str(e)}", exc_info=True)
        if isinstance(e, Http404):
            return JsonResponse({"error": str(e)}, status=404)
        if isinstance(e, ValidationError):
            return JsonResponse({"error": str(e)}, status=400)
        return JsonResponse({"error": "Internal server error"}, status=500)


@method_decorator(login_required, name="dispatch")
class HatchSettingListTemplateView(View):
    """Renders the hatch register list page."""

    def get(self, request):
        return render(request, "hatchery_list.html")


@method_decorator(login_required, name="dispatch")
class HatchSettingFormTemplateView(View):
    """Renders the full hatch register form page for add/edit."""

    def get(self, request, id: Optional[int] = None):
        context = {"hatch_setting_id": id}
        return render(request, "hatchery_form.html", context)


def _egg_intake_to_dict(row: HatchEggIntake) -> dict:
    return {
        "id": row.id,
        "sub_lot_flock": row.sub_lot_flock,
        "setter_no": row.setter_no,
        "no_trays": row.no_trays,
        "tray_size": row.tray_size,
        "total_eggs": row.total_eggs,
    }


def _hatcher_output_to_dict(row: HatchHatcherOutput) -> dict:
    return {
        "id": row.id,
        "hatcher_no": row.hatcher_no,
        "infertile_qty": row.infertile_qty,
        "early_dead_qty": row.early_dead_qty,
        "blasting_qty": row.blasting_qty,
        "transfer_qty": row.transfer_qty,
        "dead_in_shell_qty": row.dead_in_shell_qty,
        "culls_malf_qty": row.culls_malf_qty,
        "saleable_chicks": row.saleable_chicks,
    }


def _sales_line_to_dict(row: HatchSalesLine) -> dict:
    return {
        "id": row.id,
        "trader_customer_name": row.trader_customer_name,
        "chicks_sold": row.chicks_sold,
        "free_chicks": row.free_chicks,
        "billed_chicks": row.billed_chicks,
        "rate": str(row.rate),
        "total_amount": str(row.total_amount),
        "payment_status": row.payment_status,
        "delivery_notes": row.delivery_notes,
    }


def _hatch_setting_to_dict(hs: HatchSetting) -> dict:
    return {
        "id": hs.id,
        "setting_no": hs.setting_no,
        "batch_flock_no": hs.batch_flock_no,
        "supplier_name": hs.supplier_name,
        "primary_machine_nos": hs.primary_machine_nos,
        "received_date": hs.received_date.isoformat() if hs.received_date else None,
        "received_time": hs.received_time.strftime("%H:%M") if hs.received_time else None,
        "setting_date": hs.setting_date.isoformat() if hs.setting_date else None,
        "transfer_date": hs.transfer_date.isoformat() if hs.transfer_date else None,
        "hatch_date": hs.hatch_date.isoformat() if hs.hatch_date else None,
        "push_time": hs.push_time.strftime("%H:%M") if hs.push_time else None,
        "received_qty": hs.received_qty,
        "breakage_qty": hs.breakage_qty,
        "crack_qty": hs.crack_qty,
        "setting_qty": hs.setting_qty,
        "breakage_percent": hs.breakage_percent(),
        "crack_percent": hs.crack_percent(),
        "setter_temperature": hs.setter_temperature,
        "setter_humidity": hs.setter_humidity,
        "hatcher_temperature": hs.hatcher_temperature,
        "hatcher_humidity": hs.hatcher_humidity,
        "avg_chick_weight": hs.avg_chick_weight,
        "medicine_vaccine": hs.medicine_vaccine,
        "packing_boxes_used": hs.packing_boxes_used,
        "remarks": hs.remarks,
        "prepared_by": hs.prepared_by,
        "verified_by": hs.verified_by,
        "egg_intakes": [_egg_intake_to_dict(r) for r in hs.egg_intakes.all()],
        "hatcher_outputs": [_hatcher_output_to_dict(r) for r in hs.hatcher_outputs.all()],
        "sales_lines": [_sales_line_to_dict(r) for r in hs.sales_lines.all()],
        "total_setting_qty": hs.total_setting_qty(),
        "total_saleable_chicks": hs.total_saleable_chicks(),
        "hatch_percent": hs.hatch_percent(),
        "total_chicks_sold": hs.total_chicks_sold(),
        "unsold_chicks": hs.unsold_chicks(),
        "total_sales_amount": str(hs.total_sales_amount()),
    }


@method_decorator(login_required, name="dispatch")
class HatchSettingAPI(BaseAPIView):
    """API endpoints for HatchSetting (hatch register) records, including nested rows."""

    def get(self, request, id: Optional[int] = None) -> JsonResponse:
        try:
            if id:
                hs = get_object_or_404(
                    HatchSetting.objects.prefetch_related(
                        "egg_intakes", "hatcher_outputs", "sales_lines"
                    ),
                    id=id,
                )
                return JsonResponse(_hatch_setting_to_dict(hs))

            hatch_settings = HatchSetting.objects.all()
            results = []
            for hs in hatch_settings:
                results.append({
                    "id": hs.id,
                    "setting_no": hs.setting_no,
                    "batch_flock_no": hs.batch_flock_no,
                    "supplier_name": hs.supplier_name,
                    "received_date": hs.received_date.isoformat() if hs.received_date else None,
                    "setting_date": hs.setting_date.isoformat() if hs.setting_date else None,
                    "hatch_date": hs.hatch_date.isoformat() if hs.hatch_date else None,
                    "total_setting_qty": hs.total_setting_qty(),
                    "total_saleable_chicks": hs.total_saleable_chicks(),
                    "hatch_percent": hs.hatch_percent(),
                    "unsold_chicks": hs.unsold_chicks(),
                })
            return JsonResponse(results, safe=False)
        except Exception as e:
            return self.handle_exception(e)

    @transaction.atomic
    def post(self, request) -> JsonResponse:
        try:
            data = json.loads(request.body.decode("utf-8"))
            hs = self._save_hatch_setting(data)
            return JsonResponse({"message": "Hatch setting created", "id": hs.id}, status=201)
        except Exception as e:
            return self.handle_exception(e)

    @transaction.atomic
    def put(self, request, id: int) -> JsonResponse:
        try:
            data = json.loads(request.body.decode("utf-8"))
            hs = self._save_hatch_setting(data, hatch_setting_id=id)
            return JsonResponse({"message": "Hatch setting updated", "id": hs.id})
        except Exception as e:
            return self.handle_exception(e)

    def delete(self, request, id: int) -> JsonResponse:
        try:
            hs = get_object_or_404(HatchSetting, id=id)
            hs.delete()
            return JsonResponse({"message": "Hatch setting deleted"})
        except Exception as e:
            return self.handle_exception(e)

    def _save_hatch_setting(self, data: dict, hatch_setting_id: Optional[int] = None) -> HatchSetting:
        header_fields = [
            "setting_no", "batch_flock_no", "supplier_name", "primary_machine_nos",
            "received_date", "received_time", "setting_date", "transfer_date",
            "hatch_date", "push_time", "received_qty", "breakage_qty",
            "crack_qty", "setting_qty", "setter_temperature", "setter_humidity",
            "hatcher_temperature", "hatcher_humidity", "avg_chick_weight",
            "medicine_vaccine", "packing_boxes_used", "remarks",
            "prepared_by", "verified_by",
        ]
        header_data = {f: data[f] for f in header_fields if f in data and data[f] not in ("", None)}

        if hatch_setting_id:
            hs = get_object_or_404(HatchSetting, id=hatch_setting_id)
            for field, value in header_data.items():
                setattr(hs, field, value)
            hs.full_clean()
            hs.save()
            hs.egg_intakes.all().delete()
            hs.hatcher_outputs.all().delete()
            hs.sales_lines.all().delete()
        else:
            hs = HatchSetting(**header_data)
            hs.full_clean()
            hs.save()

        for row in data.get("egg_intakes", []):
            HatchEggIntake.objects.create(
                hatch_setting=hs,
                sub_lot_flock=row.get("sub_lot_flock", ""),
                setter_no=row["setter_no"],
                no_trays=row.get("no_trays") or None,
                tray_size=row.get("tray_size") or None,
                total_eggs=row.get("total_eggs") or None,
            )

        for row in data.get("hatcher_outputs", []):
            HatchHatcherOutput.objects.create(
                hatch_setting=hs,
                hatcher_no=row["hatcher_no"],
                infertile_qty=row.get("infertile_qty") or 0,
                early_dead_qty=row.get("early_dead_qty") or 0,
                blasting_qty=row.get("blasting_qty") or 0,
                transfer_qty=row.get("transfer_qty") or 0,
                dead_in_shell_qty=row.get("dead_in_shell_qty") or 0,
                culls_malf_qty=row.get("culls_malf_qty") or 0,
                saleable_chicks=row.get("saleable_chicks") or 0,
            )

        for row in data.get("sales_lines", []):
            HatchSalesLine.objects.create(
                hatch_setting=hs,
                trader_customer_name=row["trader_customer_name"],
                chicks_sold=row.get("chicks_sold") or 0,
                free_chicks=row.get("free_chicks") or 0,
                billed_chicks=row.get("billed_chicks") or 0,
                rate=row.get("rate") or 0,
                total_amount=row.get("total_amount") or 0,
                payment_status=row.get("payment_status") or "unpaid",
                delivery_notes=row.get("delivery_notes", ""),
            )

        return hs
