import csv
from datetime import date
from decimal import Decimal
from typing import Optional
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views import View
from django.http import Http404, HttpResponse, JsonResponse
from django.core.exceptions import ValidationError
from django.db import transaction
import json
import logging

from account.models import ChartOfAccount
from inventory.models import Item, Warehouse
from purchase.models import Supplier
from hatchery_master.models import Setter, Hatcher

from .models import (
    HatchSetting, HatchEggIntake, HatchHatcherOutput, HatchSalesLine,
    EggPurchase, EggPurchaseItem, EggGrading, EggGradingHatchItem,
)

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
        context = {
            "hatch_setting_id": id,
            "suppliers": Supplier.objects.all(),
            "setter_nos": (
                Setter.objects.filter(is_active=True)
                .values_list("setter_no", flat=True).distinct().order_by("setter_no")
            ),
            "hatcher_nos": (
                Hatcher.objects.filter(is_active=True)
                .values_list("hatcher_no", flat=True).distinct().order_by("hatcher_no")
            ),
            "next_batch_flock_no": HatchSetting._next_batch_flock_no() if id is None else None,
        }
        return render(request, "hatchery_form.html", context)


@login_required
def next_batch_flock_no(request):
    return JsonResponse({"batch_flock_no": HatchSetting._next_batch_flock_no()})


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
        "discount_percent": str(row.discount_percent),
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
        "avg_egg_weight": hs.avg_egg_weight,
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
                    "setting_date": hs.setting_date.isoformat() if hs.setting_date else None,
                    "transfer_date": hs.transfer_date.isoformat() if hs.transfer_date else None,
                    "hatch_date": hs.hatch_date.isoformat() if hs.hatch_date else None,
                    "total_setting_qty": hs.total_setting_qty(),
                    "total_saleable_chicks": hs.total_saleable_chicks(),
                    "hatch_percent": hs.hatch_percent(),
                    "total_chicks_sold": hs.total_chicks_sold(),
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
            "setting_no", "supplier_name", "primary_machine_nos", "avg_egg_weight",
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
            hs.full_clean(exclude=["batch_flock_no"])
            hs.save()
            hs.egg_intakes.all().delete()
            hs.hatcher_outputs.all().delete()
            hs.sales_lines.all().delete()
        else:
            hs = HatchSetting(**header_data)
            hs.full_clean(exclude=["batch_flock_no"])
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
                discount_percent=row.get("discount_percent") or 0,
                free_chicks=row.get("free_chicks") or 0,
                billed_chicks=row.get("billed_chicks") or 0,
                rate=row.get("rate") or 0,
                total_amount=row.get("total_amount") or 0,
                payment_status=row.get("payment_status") or "unpaid",
                delivery_notes=row.get("delivery_notes", ""),
            )

        return hs


@method_decorator(login_required, name="dispatch")
class EggPurchaseListTemplateView(View):
    """Renders the egg purchase list page."""

    def get(self, request):
        return render(request, "egg_purchase_list.html")


@method_decorator(login_required, name="dispatch")
class EggPurchaseFormTemplateView(View):
    """Renders the egg purchase add/edit page."""

    def get(self, request, id: Optional[int] = None):
        context = {
            "egg_purchase_id": id,
            "suppliers": Supplier.objects.all().order_by("name"),
            "warehouses": Warehouse.objects.all().order_by("name"),
            "items": Item.objects.all().order_by("item_code"),
            "pay_accounts": ChartOfAccount.objects.filter(status="Active").order_by("code"),
            "next_transaction_no": EggPurchase._next_transaction_no() if id is None else None,
        }
        return render(request, "egg_purchase_form.html", context)


@login_required
def egg_purchase_next_number(request):
    return JsonResponse({"transaction_no": EggPurchase._next_transaction_no()})


def _egg_purchase_item_to_dict(row: EggPurchaseItem) -> dict:
    return {
        "id": row.id,
        "item": row.item_id,
        "item_code": row.item.item_code,
        "item_description": row.item.description,
        "sent_qty": str(row.sent_qty),
        "rcv_qty": str(row.rcv_qty),
        "free_qty": str(row.free_qty),
        "no_of_boxes": str(row.no_of_boxes),
        "amount": str(row.amount),
        "discount_percent": str(row.discount_percent),
        "discount_amount": str(row.discount_amount),
        "total_amount": str(row.total_amount),
        "rate": str(row.rate),
    }


def _egg_purchase_to_dict(ep: EggPurchase) -> dict:
    return {
        "id": ep.id,
        "transaction_no": ep.transaction_no,
        "date": ep.date.isoformat() if ep.date else None,
        "supplier": ep.supplier_id,
        "supplier_name": ep.supplier.name,
        "warehouse": ep.warehouse_id,
        "warehouse_name": ep.warehouse.name,
        "dc_no": ep.dc_no,
        "vehicle": ep.vehicle,
        "driver": ep.driver,
        "freight_type": ep.freight_type,
        "payment_mode": ep.payment_mode,
        "pay_account": ep.pay_account_id,
        "freight_account": ep.freight_account_id,
        "freight_amount": str(ep.freight_amount),
        "tcs_applicable": ep.tcs_applicable,
        "tcs_percent": str(ep.tcs_percent),
        "tcs_amount": str(ep.tcs_amount()),
        "remarks": ep.remarks,
        "items": [_egg_purchase_item_to_dict(row) for row in ep.items.all()],
        "gross_amount": str(ep.gross_amount()),
        "net_quantity": str(ep.net_quantity()),
        "net_rate": str(ep.net_rate()),
        "net_amount": str(ep.net_amount()),
        "supplier_amount": str(ep.supplier_amount()),
    }


@method_decorator(login_required, name="dispatch")
class EggPurchaseAPI(BaseAPIView):
    """API endpoints for EggPurchase records, including nested item rows."""

    def get(self, request, id: Optional[int] = None) -> JsonResponse:
        try:
            if id:
                ep = get_object_or_404(
                    EggPurchase.objects.select_related("supplier", "warehouse").prefetch_related("items__item"),
                    id=id,
                )
                return JsonResponse(_egg_purchase_to_dict(ep))

            queryset = EggPurchase.objects.select_related("supplier", "warehouse").prefetch_related("items__item")
            supplier_id = request.GET.get("supplier")
            if supplier_id:
                queryset = queryset.filter(supplier_id=supplier_id)

            results = []
            for ep in queryset:
                item_names = ", ".join(row.item.item_code for row in ep.items.all())
                results.append({
                    "id": ep.id,
                    "transaction_no": ep.transaction_no,
                    "date": ep.date.isoformat() if ep.date else None,
                    "dc_no": ep.dc_no,
                    "supplier": ep.supplier_id,
                    "supplier_name": ep.supplier.name,
                    "item_names": item_names,
                    "items": [{"item": row.item_id, "item_code": row.item.item_code, "rcv_qty": str(row.rcv_qty)} for row in ep.items.all()],
                    "net_quantity": str(ep.net_quantity()),
                    "net_rate": str(ep.net_rate()),
                    "net_amount": str(ep.net_amount()),
                    "warehouse_name": ep.warehouse.name,
                })
            return JsonResponse(results, safe=False)
        except Exception as e:
            return self.handle_exception(e)

    @transaction.atomic
    def post(self, request) -> JsonResponse:
        try:
            data = json.loads(request.body.decode("utf-8"))
            ep = self._save_egg_purchase(data)
            return JsonResponse({"message": "Egg purchase created", "id": ep.id}, status=201)
        except Exception as e:
            return self.handle_exception(e)

    @transaction.atomic
    def put(self, request, id: int) -> JsonResponse:
        try:
            data = json.loads(request.body.decode("utf-8"))
            ep = self._save_egg_purchase(data, egg_purchase_id=id)
            return JsonResponse({"message": "Egg purchase updated", "id": ep.id})
        except Exception as e:
            return self.handle_exception(e)

    def delete(self, request, id: int) -> JsonResponse:
        try:
            ep = get_object_or_404(EggPurchase, id=id)
            ep.delete()
            return JsonResponse({"message": "Egg purchase deleted"})
        except Exception as e:
            return self.handle_exception(e)

    def _save_egg_purchase(self, data: dict, egg_purchase_id: Optional[int] = None) -> EggPurchase:
        header_fields = [
            "date", "dc_no", "vehicle", "driver", "freight_type", "payment_mode",
            "freight_amount", "tcs_applicable", "tcs_percent", "remarks",
        ]
        header_data = {f: data[f] for f in header_fields if f in data and data[f] not in ("", None)}
        header_data["tcs_applicable"] = bool(data.get("tcs_applicable"))

        header_data["supplier"] = get_object_or_404(Supplier, id=data["supplier"])
        header_data["warehouse"] = get_object_or_404(Warehouse, id=data["warehouse"])
        header_data["pay_account"] = get_object_or_404(ChartOfAccount, id=data["pay_account"])
        if data.get("freight_account"):
            header_data["freight_account"] = get_object_or_404(ChartOfAccount, id=data["freight_account"])
        else:
            header_data["freight_account"] = None

        if egg_purchase_id:
            ep = get_object_or_404(EggPurchase, id=egg_purchase_id)
            for field, value in header_data.items():
                setattr(ep, field, value)
            ep.full_clean(exclude=["transaction_no"])
            ep.save()
            ep.items.all().delete()
        else:
            ep = EggPurchase(**header_data)
            ep.full_clean(exclude=["transaction_no"])
            ep.save()

        for row in data.get("items", []):
            EggPurchaseItem.objects.create(
                egg_purchase=ep,
                item=get_object_or_404(Item, id=row["item"]),
                sent_qty=Decimal(str(row.get("sent_qty") or 0)),
                rcv_qty=Decimal(str(row.get("rcv_qty") or 0)),
                free_qty=Decimal(str(row.get("free_qty") or 0)),
                no_of_boxes=Decimal(str(row.get("no_of_boxes") or 0)),
                amount=Decimal(str(row.get("amount") or 0)),
                discount_percent=Decimal(str(row.get("discount_percent") or 0)),
                discount_amount=Decimal(str(row.get("discount_amount") or 0)),
            )

        return ep


@method_decorator(login_required, name="dispatch")
class EggGradingListTemplateView(View):
    """Renders the egg grading list page."""

    def get(self, request):
        return render(request, "egg_grading_list.html")


@method_decorator(login_required, name="dispatch")
class EggGradingFormTemplateView(View):
    """Renders the egg grading add/edit page."""

    def get(self, request, id: Optional[int] = None):
        context = {
            "egg_grading_id": id,
            "suppliers": Supplier.objects.all().order_by("name"),
            "storage_locations": Warehouse.objects.all().order_by("name"),
            "items": Item.objects.all().order_by("item_code"),
            "next_transaction_no": EggGrading._next_transaction_no() if id is None else None,
        }
        return render(request, "egg_grading_form.html", context)


@login_required
def egg_grading_next_number(request):
    return JsonResponse({"transaction_no": EggGrading._next_transaction_no()})


@login_required
def egg_grading_stock_check(request):
    purchase_invoice = request.GET.get("purchase_invoice")
    item = request.GET.get("item")
    exclude_id = request.GET.get("exclude_id")
    if not purchase_invoice or not item:
        return JsonResponse({"error": "purchase_invoice and item are required"}, status=400)
    stock = EggGrading.available_stock(purchase_invoice, item, exclude_id=exclude_id)
    return JsonResponse({"stock": str(stock)})


def _egg_grading_hatch_item_to_dict(row: EggGradingHatchItem) -> dict:
    return {
        "id": row.id,
        "hatch_item": row.hatch_item_id,
        "hatch_item_code": row.hatch_item.item_code,
        "quantity": str(row.quantity),
    }


def _egg_grading_to_dict(eg: EggGrading) -> dict:
    return {
        "id": eg.id,
        "transaction_no": eg.transaction_no,
        "date": eg.date.isoformat() if eg.date else None,
        "storage_location": eg.storage_location_id,
        "storage_location_name": eg.storage_location.name,
        "supplier": eg.supplier_id,
        "supplier_name": eg.supplier.name,
        "purchase_invoice": eg.purchase_invoice_id,
        "purchase_invoice_no": eg.purchase_invoice.transaction_no,
        "item": eg.item_id,
        "item_code": eg.item.item_code,
        "quantity": str(eg.quantity),
        "broken_eggs": str(eg.broken_eggs),
        "damage_eggs": str(eg.damage_eggs),
        "misshapped_eggs": str(eg.misshapped_eggs),
        "dirty_eggs": str(eg.dirty_eggs),
        "total_rejections": str(eg.total_rejections()),
        "eggs_to_stock": str(eg.eggs_to_stock()),
        "hatch_items": [_egg_grading_hatch_item_to_dict(row) for row in eg.hatch_items.all()],
        "total_hatch_qty": str(eg.total_hatch_qty()),
    }


@method_decorator(login_required, name="dispatch")
class EggGradingAPI(BaseAPIView):
    """API endpoints for EggGrading records, including nested hatch item rows."""

    def get(self, request, id: Optional[int] = None) -> JsonResponse:
        try:
            if id:
                eg = get_object_or_404(
                    EggGrading.objects.select_related(
                        "storage_location", "supplier", "purchase_invoice", "item"
                    ).prefetch_related("hatch_items__hatch_item"),
                    id=id,
                )
                return JsonResponse(_egg_grading_to_dict(eg))

            results = []
            for eg in EggGrading.objects.select_related(
                "storage_location", "supplier", "purchase_invoice", "item"
            ).prefetch_related("hatch_items__hatch_item"):
                hatch_egg_summary = ", ".join(
                    f"{row.hatch_item.item_code} ({row.quantity})" for row in eg.hatch_items.all()
                )
                results.append({
                    "id": eg.id,
                    "transaction_no": eg.transaction_no,
                    "date": eg.date.isoformat() if eg.date else None,
                    "item_code": eg.item.item_code,
                    "quantity": str(eg.quantity),
                    "hatch_egg_summary": hatch_egg_summary,
                    "storage_location_name": eg.storage_location.name,
                })
            return JsonResponse(results, safe=False)
        except Exception as e:
            return self.handle_exception(e)

    @transaction.atomic
    def post(self, request) -> JsonResponse:
        try:
            data = json.loads(request.body.decode("utf-8"))
            eg = self._save_egg_grading(data)
            return JsonResponse({"message": "Egg grading created", "id": eg.id}, status=201)
        except Exception as e:
            return self.handle_exception(e)

    @transaction.atomic
    def put(self, request, id: int) -> JsonResponse:
        try:
            data = json.loads(request.body.decode("utf-8"))
            eg = self._save_egg_grading(data, egg_grading_id=id)
            return JsonResponse({"message": "Egg grading updated", "id": eg.id})
        except Exception as e:
            return self.handle_exception(e)

    def delete(self, request, id: int) -> JsonResponse:
        try:
            eg = get_object_or_404(EggGrading, id=id)
            eg.delete()
            return JsonResponse({"message": "Egg grading deleted"})
        except Exception as e:
            return self.handle_exception(e)

    def _save_egg_grading(self, data: dict, egg_grading_id: Optional[int] = None) -> EggGrading:
        header_fields = ["date", "quantity", "broken_eggs", "damage_eggs", "misshapped_eggs", "dirty_eggs"]
        header_data = {f: data[f] for f in header_fields if f in data and data[f] not in ("", None)}

        header_data["storage_location"] = get_object_or_404(Warehouse, id=data["storage_location"])
        header_data["supplier"] = get_object_or_404(Supplier, id=data["supplier"])
        header_data["purchase_invoice"] = get_object_or_404(EggPurchase, id=data["purchase_invoice"])
        header_data["item"] = get_object_or_404(Item, id=data["item"])

        if egg_grading_id:
            eg = get_object_or_404(EggGrading, id=egg_grading_id)
            for field, value in header_data.items():
                setattr(eg, field, value)
            eg.full_clean(exclude=["transaction_no"])
            eg.save()
            eg.hatch_items.all().delete()
        else:
            eg = EggGrading(**header_data)
            eg.full_clean(exclude=["transaction_no"])
            eg.save()

        for row in data.get("hatch_items", []):
            if not row.get("hatch_item"):
                continue
            EggGradingHatchItem.objects.create(
                egg_grading=eg,
                hatch_item=get_object_or_404(Item, id=row["hatch_item"]),
                quantity=Decimal(str(row.get("quantity") or 0)),
            )

        return eg


# ---------------------------------------------------------------------------
# Hatchery Sheet Report
# ---------------------------------------------------------------------------

# Report columns as (row-key, display label, kind). `kind` drives formatting,
# alignment and totals behaviour, and is shared by the on-screen table, the
# Excel sheet and the CSV so all three stay in sync.
#   text  - left aligned, no total
#   date  - left aligned, no total
#   num   - right aligned integer, summed in the totals row
#   pct   - right aligned percentage (value + "%"), recomputed in totals
#   money - right aligned 2dp amount, summed in the totals row
HATCH_REPORT_COLUMNS = [
    # Identity
    ("setting_no", "Setting No", "text"),
    ("batch_flock_no", "Batch/Flock No", "text"),
    ("supplier_name", "Supplier", "text"),
    ("primary_machine_nos", "Machine Nos", "text"),
    ("avg_egg_weight", "Avg Egg Wt", "text"),
    ("received_date", "Received Date", "date"),
    ("received_time", "Received Time", "text"),
    ("setting_date", "Setting Date", "date"),
    ("transfer_date", "Transfer Date", "date"),
    ("hatch_date", "Hatch Date", "date"),
    ("push_time", "Push Time", "text"),
    # Egg intake
    ("received_qty", "Received Qty", "num"),
    ("breakage_qty", "Breakage", "num"),
    ("breakage_pct", "Breakage %", "pct"),
    ("crack_qty", "Crack", "num"),
    ("crack_pct", "Crack %", "pct"),
    ("setting_qty", "Setting Qty", "num"),
    # Candling & hatch output
    ("infertile_qty", "Infertile", "num"),
    ("infertile_pct", "Infertile %", "pct"),
    ("early_dead_qty", "Early Dead", "num"),
    ("early_dead_pct", "Early Dead %", "pct"),
    ("blasting_qty", "Blasting", "num"),
    ("blasting_pct", "Blasting %", "pct"),
    ("transfer_qty", "Transfer Qty", "num"),
    ("transfer_pct", "Transfer %", "pct"),
    ("dead_in_shell_qty", "Dead-In-Shell", "num"),
    ("culls_malf_qty", "Culls / Malf.", "num"),
    ("saleable_chicks", "Saleable Chicks", "num"),
    ("hatch_pct", "Hatch %", "pct"),
    # Environmental & consumables
    ("avg_chick_weight", "Avg Chick Wt", "text"),
    ("medicine_vaccine", "Medicine / Vaccine", "text"),
    ("packing_boxes_used", "Packing Boxes", "num"),
    # Sales
    ("chicks_sold", "Chicks Sold", "num"),
    ("unsold_chicks", "Unsold", "num"),
    ("sales_amount", "Sales Amount", "money"),
]

# Percentage columns and the (numerator, denominator) qty keys they derive
# from. Used for both per-row and totals-row percentages.
HATCH_REPORT_PCT_SOURCES = {
    "breakage_pct": ("breakage_qty", "received_qty"),
    "crack_pct": ("crack_qty", "received_qty"),
    "infertile_pct": ("infertile_qty", "setting_qty"),
    "early_dead_pct": ("early_dead_qty", "setting_qty"),
    "blasting_pct": ("blasting_qty", "setting_qty"),
    "transfer_pct": ("transfer_qty", "setting_qty"),
    "hatch_pct": ("saleable_chicks", "setting_qty"),
}

# Column keys summed into the totals footer.
HATCH_REPORT_SUM_KEYS = [key for key, _, kind in HATCH_REPORT_COLUMNS if kind in ("num", "money")]


def _pct(numerator, denominator):
    return round(numerator / denominator * 100, 2) if denominator else 0


def _build_hatch_report_rows(queryset):
    """Turn prefetched HatchSetting records into flat report row dicts.

    Aggregates are computed in Python from the prefetched child rows to avoid
    a per-record DB round trip (unlike the model's own helper methods).
    """
    rows = []
    for hs in queryset:
        outputs = list(hs.hatcher_outputs.all())
        sales = list(hs.sales_lines.all())

        infertile = sum(o.infertile_qty for o in outputs)
        early_dead = sum(o.early_dead_qty for o in outputs)
        blasting = sum(o.blasting_qty for o in outputs)
        transfer = sum(o.transfer_qty for o in outputs)
        dead_in_shell = sum(o.dead_in_shell_qty for o in outputs)
        culls = sum(o.culls_malf_qty for o in outputs)
        saleable = sum(o.saleable_chicks for o in outputs)
        sold = sum(s.chicks_sold for s in sales)
        sales_amount = sum((s.total_amount for s in sales), Decimal("0"))

        row = {
            "id": hs.id,
            "setting_no": hs.setting_no,
            "batch_flock_no": hs.batch_flock_no or "",
            "supplier_name": hs.supplier_name,
            "primary_machine_nos": hs.primary_machine_nos or "",
            "avg_egg_weight": hs.avg_egg_weight or "",
            "received_date": hs.received_date.isoformat() if hs.received_date else "",
            "received_time": hs.received_time.strftime("%H:%M") if hs.received_time else "",
            "setting_date": hs.setting_date.isoformat() if hs.setting_date else "",
            "transfer_date": hs.transfer_date.isoformat() if hs.transfer_date else "",
            "hatch_date": hs.hatch_date.isoformat() if hs.hatch_date else "",
            "push_time": hs.push_time.strftime("%H:%M") if hs.push_time else "",
            "received_qty": hs.received_qty,
            "breakage_qty": hs.breakage_qty,
            "crack_qty": hs.crack_qty,
            "setting_qty": hs.setting_qty,
            "infertile_qty": infertile,
            "early_dead_qty": early_dead,
            "blasting_qty": blasting,
            "transfer_qty": transfer,
            "dead_in_shell_qty": dead_in_shell,
            "culls_malf_qty": culls,
            "saleable_chicks": saleable,
            "setter_temperature": hs.setter_temperature or "",
            "setter_humidity": hs.setter_humidity or "",
            "hatcher_temperature": hs.hatcher_temperature or "",
            "hatcher_humidity": hs.hatcher_humidity or "",
            "avg_chick_weight": hs.avg_chick_weight or "",
            "medicine_vaccine": hs.medicine_vaccine or "",
            "packing_boxes_used": hs.packing_boxes_used or 0,
            "chicks_sold": sold,
            "unsold_chicks": saleable - sold,
            "sales_amount": sales_amount,
        }
        for pct_key, (num_key, den_key) in HATCH_REPORT_PCT_SOURCES.items():
            row[pct_key] = _pct(row[num_key], row[den_key])
        rows.append(row)
    return rows


def _hatch_report_totals(rows):
    totals = {key: 0 for key in HATCH_REPORT_SUM_KEYS}
    totals["sales_amount"] = Decimal("0")
    for row in rows:
        for key in HATCH_REPORT_SUM_KEYS:
            totals[key] += row[key] or 0
    for pct_key, (num_key, den_key) in HATCH_REPORT_PCT_SOURCES.items():
        totals[pct_key] = _pct(totals.get(num_key, 0), totals.get(den_key, 0))
    return totals


def _filter_hatch_report_queryset(request):
    """Applies the report bar filters (date range on setting_date, supplier,
    payment status) and returns (queryset, applied_filters_dict)."""
    from_date = request.GET.get("from_date", "").strip()
    to_date = request.GET.get("to_date", "").strip()
    supplier = request.GET.get("supplier", "").strip()
    payment_status = request.GET.get("payment_status", "").strip()

    qs = HatchSetting.objects.prefetch_related("hatcher_outputs", "sales_lines")
    if from_date:
        qs = qs.filter(setting_date__gte=from_date)
    if to_date:
        qs = qs.filter(setting_date__lte=to_date)
    if supplier:
        qs = qs.filter(supplier_name=supplier)
    if payment_status:
        qs = qs.filter(sales_lines__payment_status=payment_status).distinct()
    qs = qs.order_by("setting_date", "id")

    return qs, {
        "from_date": from_date,
        "to_date": to_date,
        "supplier": supplier,
        "payment_status": payment_status,
    }


def _report_export_value(kind, value):
    """Coerce a cell to a spreadsheet/CSV-friendly value (numbers stay numeric)."""
    if kind == "money":
        return float(value or 0)
    if kind in ("num", "pct"):
        return value if value not in ("", None) else 0
    return value if value not in ("", None) else ""


def _hatch_report_csv_response(rows):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="hatchery_report_{date.today().isoformat()}.csv"'
    writer = csv.writer(response)
    writer.writerow([label for _, label, _ in HATCH_REPORT_COLUMNS])
    for row in rows:
        writer.writerow([_report_export_value(kind, row[key]) for key, _, kind in HATCH_REPORT_COLUMNS])
    totals = _hatch_report_totals(rows)
    writer.writerow([
        "TOTAL" if key == "setting_no"
        else (_report_export_value(kind, totals[key]) if key in totals else "")
        for key, _, kind in HATCH_REPORT_COLUMNS
    ])
    return response


def _hatch_report_xlsx_response(rows, filters):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment

    wb = Workbook()
    ws = wb.active
    ws.title = "Hatchery Report"

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1F3B73", end_color="1F3B73", fill_type="solid")
    title_font = Font(bold=True, size=14)

    ws.append(["Hi Tech Farms — Hatch Register Report"])
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(HATCH_REPORT_COLUMNS))
    ws["A1"].font = title_font
    ws["A1"].alignment = Alignment(horizontal="center")

    range_bits = []
    if filters["from_date"] or filters["to_date"]:
        range_bits.append(f"Setting Date: {filters['from_date'] or '…'} to {filters['to_date'] or '…'}")
    if filters["supplier"]:
        range_bits.append(f"Supplier: {filters['supplier']}")
    if filters["payment_status"]:
        range_bits.append(f"Payment: {filters['payment_status'].title()}")
    ws.append([" | ".join(range_bits) if range_bits else "All records"])
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(HATCH_REPORT_COLUMNS))
    ws.append([])

    header_row_idx = ws.max_row + 1
    ws.append([label for _, label, _ in HATCH_REPORT_COLUMNS])
    for cell in ws[header_row_idx]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")

    for row in rows:
        ws.append([_report_export_value(kind, row[key]) for key, _, kind in HATCH_REPORT_COLUMNS])

    totals = _hatch_report_totals(rows)
    total_row = []
    for key, _, kind in HATCH_REPORT_COLUMNS:
        if key == "setting_no":
            total_row.append("TOTAL")
        elif key in totals:
            total_row.append(_report_export_value(kind, totals[key]))
        else:
            total_row.append("")
    ws.append(total_row)
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)

    for col_idx, (_, label, _kind) in enumerate(HATCH_REPORT_COLUMNS, start=1):
        ws.column_dimensions[ws.cell(row=header_row_idx, column=col_idx).column_letter].width = max(12, len(label) + 3)

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="hatchery_report_{date.today().isoformat()}.xlsx"'
    wb.save(response)
    return response


def _format_hatch_report_cell(kind, value):
    """Returns (display_value, css_align_class) for one report cell so the
    template can render rows without needing variable-key dict lookups."""
    if kind == "pct":
        return f"{value}%", "text-end"
    if kind == "money":
        return f"{Decimal(value or 0):,.2f}", "text-end"
    if kind == "num":
        return (value if value not in ("", None) else "-"), "text-end"
    return (value if value not in ("", None) else "-"), ""


def _hatch_report_display_rows(rows):
    """Each row -> ordered list of {value, align} cells matching HATCH_REPORT_COLUMNS."""
    display = []
    for row in rows:
        cells = []
        for key, _, kind in HATCH_REPORT_COLUMNS:
            value, align = _format_hatch_report_cell(kind, row[key])
            cells.append({"value": value, "align": align})
        display.append(cells)
    return display


def _hatch_report_display_totals(totals):
    cells = []
    for key, _, kind in HATCH_REPORT_COLUMNS:
        if key == "setting_no":
            cells.append({"value": "TOTAL", "align": ""})
        elif key in totals:
            value, align = _format_hatch_report_cell(kind, totals[key])
            cells.append({"value": value, "align": align})
        else:
            cells.append({"value": "", "align": ""})
    return cells


@method_decorator(login_required, name="dispatch")
class HatchReportView(View):
    """Filterable hatchery sheet report with on-screen table, print and
    Excel/CSV export (all driven by the same GET filters)."""

    def get(self, request):
        qs, filters = _filter_hatch_report_queryset(request)
        rows = _build_hatch_report_rows(qs)

        export = request.GET.get("export", "").strip().lower()
        if export == "csv":
            return _hatch_report_csv_response(rows)
        if export == "xlsx":
            return _hatch_report_xlsx_response(rows, filters)

        totals = _hatch_report_totals(rows)
        context = {
            "columns": HATCH_REPORT_COLUMNS,
            "display_rows": _hatch_report_display_rows(rows),
            "display_totals": _hatch_report_display_totals(totals),
            "row_count": len(rows),
            "filters": filters,
            "suppliers": (
                HatchSetting.objects.exclude(supplier_name="")
                .values_list("supplier_name", flat=True).distinct().order_by("supplier_name")
            ),
            "payment_statuses": HatchSetting.PAYMENT_STATUS_CHOICES,
            "has_filters": any(filters.values()),
        }
        return render(request, "hatchery_report.html", context)
