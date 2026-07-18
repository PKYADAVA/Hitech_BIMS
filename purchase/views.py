#pylint: disable=no-member

from decimal import Decimal
from typing import Optional

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.http import require_POST
from django.http import Http404, JsonResponse
from django.db.models import F
from django.core.files.storage import default_storage
from django.utils import timezone
from hatchery_master.models import STATES_AND_TERRITORIES, Hatchery
from account.models import ChartOfAccount
from inventory.models import Item, ItemCategory, Warehouse
from picklist.services import validate_value
from .models import (ChicksPurchase, ChicksPurchaseItem, GeneralPurchase, GeneralPurchaseItem,
                     Supplier, SupplierPayment, SupplierPaymentLine, SupplierShippingAddress, TaxMaster)
import json

# Used only by the billing/shipping address modals (state field itself is
# picklist-bound, see picklist.bindable_fields.BINDABLE_FIELDS).
states_and_union_territories = STATES_AND_TERRITORIES

@login_required()
def supplier(request):
    return render(request, "supplier.html", {"suppliers": Supplier.objects.all()})


def _supplier_form_context(supplier=None):
    return {
        "supplier": supplier,
        "next_code": Supplier.next_code() if not supplier else None,
        "states_and_union_territories": states_and_union_territories,
        "to_pay_to_receive_choices": Supplier.ToPayToReceive.choices,
        "today": timezone.localdate().isoformat(),
    }


def _apply_posted_supplier_fields(instance, request):
    instance.name = request.POST.get("name", "").strip()
    instance.address = request.POST.get("address", "").strip()
    instance.place = request.POST.get("place", "").strip()
    instance.mobile = request.POST.get("mobile", "").strip()
    instance.mobile_2 = request.POST.get("mobile_2", "").strip()
    instance.email = request.POST.get("email", "").strip() or None
    instance.aadhar = request.POST.get("aadhar", "").strip()
    instance.contact_type = request.POST.get("contact_type") or Supplier.ContactType.BOTH
    instance.party_category = request.POST.get("party_category") or None
    instance.pan = request.POST.get("pan", "").strip()
    instance.supplier_group = request.POST.get("supplier_group", "").strip()
    instance.gstin = request.POST.get("gstin", "").strip()
    instance.state = request.POST.get("state", "").strip()
    instance.credit_term = request.POST.get("credit_term") or None
    instance.credit_limit = request.POST.get("credit_limit") or 0
    instance.opening_balance = request.POST.get("opening_balance") or None
    instance.to_pay_to_receive = request.POST.get("to_pay_to_receive") or None
    instance.as_on_date = request.POST.get("as_on_date") or None
    instance.note = request.POST.get("note", "").strip()
    instance.country = request.POST.get("country", "").strip()
    instance.currency = request.POST.get("currency", "").strip()
    instance.account_no = request.POST.get("account_no", "").strip()
    instance.ifsc_code = request.POST.get("ifsc_code", "").strip()
    instance.bank_details = request.POST.get("bank_details", "").strip()
    instance.terms = request.POST.get("terms", "").strip()
    instance.agreement_start_date = request.POST.get("agreement_start_date") or None
    instance.agreement_months = request.POST.get("agreement_months") or None
    if request.FILES.get("agreement_copy"):
        instance.agreement_copy = request.FILES["agreement_copy"]
    if request.FILES.get("other_documents"):
        instance.other_documents = request.FILES["other_documents"]
    for field in ("state", "contact_type", "party_category", "supplier_group"):
        validate_value("purchase", "Supplier", field, getattr(instance, field))


def _create_posted_shipping_addresses(instance, request):
    try:
        addresses = json.loads(request.POST.get("shipping_addresses_json") or "[]")
    except json.JSONDecodeError:
        addresses = []
    if not addresses and instance.address:
        addresses = [{"label": instance.address[:100], "address": instance.address, "is_default": True}]
    default_assigned = False
    for entry in addresses:
        label = (entry.get("label") or "").strip()
        address_text = (entry.get("address") or "").strip()
        if not label or not address_text:
            continue
        is_default = bool(entry.get("is_default")) and not default_assigned
        default_assigned = default_assigned or is_default
        SupplierShippingAddress.objects.create(
            supplier=instance, label=label, address=address_text,
            contact_person=(entry.get("contact_person") or "").strip(),
            mobile=(entry.get("mobile") or "").strip(),
            is_default=is_default,
        )


@login_required(login_url="login")
def create_supplier(request):
    """Add a new supplier master record."""
    if request.method == "POST":
        instance = Supplier()
        try:
            _apply_posted_supplier_fields(instance, request)
            instance.full_clean()
            instance.save()
            _create_posted_shipping_addresses(instance, request)
            messages.success(request, "Supplier added successfully.")
            return redirect("supplier")
        except ValidationError as e:
            messages.error(request, " ".join(e.messages) if hasattr(e, "messages") else str(e))

    return render(request, "supplier_form.html", _supplier_form_context())


@login_required(login_url="login")
def edit_supplier(request, id):
    """Edit an existing supplier master record."""
    instance = get_object_or_404(Supplier, id=id)

    if request.method == "POST":
        try:
            _apply_posted_supplier_fields(instance, request)
            instance.full_clean()
            instance.save()
            messages.success(request, "Supplier updated successfully.")
            return redirect("supplier")
        except ValidationError as e:
            messages.error(request, " ".join(e.messages) if hasattr(e, "messages") else str(e))

    return render(request, "supplier_form.html", _supplier_form_context(instance))


@login_required(login_url="login")
@require_POST
def delete_supplier(request, id):
    """Delete a supplier master record."""
    instance = get_object_or_404(Supplier, id=id)
    instance.delete()
    messages.success(request, "Supplier deleted successfully.")
    return redirect("supplier")


@method_decorator(login_required, name="dispatch")
class SupplierShippingAddressAPI(View):
    """Supplier Master addresses, also usable by transaction forms."""
    def get(self, request, supplier_id, id=None):
        supplier = Supplier.objects.get(id=supplier_id)
        addresses = supplier.shipping_addresses.all()
        if id:
            addresses = addresses.filter(id=id)
        result = [{
            "id": address.id, "label": address.label, "address": address.address,
            "contact_person": address.contact_person, "mobile": address.mobile,
            "is_default": address.is_default,
        } for address in addresses]
        if id:
            if not result:
                return JsonResponse({"error": "Shipping address not found"}, status=404)
            return JsonResponse(result[0])
        return JsonResponse(result, safe=False)

    def post(self, request, supplier_id):
        try:
            data = json.loads(request.body)
            supplier = Supplier.objects.get(id=supplier_id)
            if not data.get("label") or not data.get("address"):
                return JsonResponse({"error": "Address label and address are required"}, status=400)
            if data.get("is_default"):
                supplier.shipping_addresses.update(is_default=False)
            address = SupplierShippingAddress.objects.create(
                supplier=supplier, label=data["label"], address=data["address"],
                contact_person=data.get("contact_person", ""), mobile=data.get("mobile", ""),
                is_default=bool(data.get("is_default")),
            )
            return JsonResponse({"id": address.id, "message": "Shipping address saved"}, status=201)
        except Supplier.DoesNotExist:
            return JsonResponse({"error": "Supplier not found"}, status=404)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)

    def put(self, request, supplier_id, id):
        try:
            data = json.loads(request.body)
            address = SupplierShippingAddress.objects.get(id=id, supplier_id=supplier_id)
            if data.get("is_default"):
                SupplierShippingAddress.objects.filter(supplier_id=supplier_id).exclude(id=id).update(is_default=False)
            for field in ("label", "address", "contact_person", "mobile"):
                if field in data:
                    setattr(address, field, data[field])
            address.is_default = bool(data.get("is_default", address.is_default))
            address.full_clean(); address.save()
            return JsonResponse({"message": "Shipping address updated"})
        except SupplierShippingAddress.DoesNotExist:
            return JsonResponse({"error": "Shipping address not found"}, status=404)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)

    def delete(self, request, supplier_id, id):
        try:
            SupplierShippingAddress.objects.get(id=id, supplier_id=supplier_id).delete()
            return JsonResponse({"message": "Shipping address deleted"})
        except SupplierShippingAddress.DoesNotExist:
            return JsonResponse({"error": "Shipping address not found"}, status=404)




@login_required()
def vendor_groups(request):
    from account.models import ChartOfAccount
    return render(request, "vendor_group.html", {
        "coa_accounts": ChartOfAccount.objects.filter(status="Active").order_by("code"),
    })


@login_required()
def tax_master(request):
    return render(request, "tax_master.html")


from .models import VendorGroup


@method_decorator(login_required, name="dispatch")
class VendorGroupAPI(View):

    @staticmethod
    def _serialize(group):
        return {
            "id": group.id,
            "code": group.code,
            "description": group.description,
            "currency": group.currency,
            "control_account": group.control_account_id,
            "control_account_display": str(group.control_account) if group.control_account else "",
            "prepayment_account": group.prepayment_account_id,
            "prepayment_account_display": str(group.prepayment_account) if group.prepayment_account else "",
        }

    def get(self, request, id=None):
        if id:
            try:
                vendor_group = VendorGroup.objects.select_related("control_account", "prepayment_account").get(id=id)
                return JsonResponse(self._serialize(vendor_group))
            except VendorGroup.DoesNotExist:
                raise Http404("VendorGroup not found")
        else:
            vendor_groups = [
                self._serialize(group)
                for group in VendorGroup.objects.select_related("control_account", "prepayment_account")
            ]
            return JsonResponse(vendor_groups, safe=False)

    def post(self, request):
        try:
            data = json.loads(request.body)  # Expect JSON payload
        except json.JSONDecodeError as e:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        VendorGroup.objects.create(
            code=data.get("code"),
            description=data.get("description"),
            currency=data.get("currency"),
            control_account_id=data.get("control_account") or None,
            prepayment_account_id=data.get("prepayment_account") or None,
        )
        return JsonResponse({"message": "VendorGroup created"}, status=201)

    def put(self, request, id):
        try:
            vendor_group = VendorGroup.objects.get(id=id)
        except VendorGroup.DoesNotExist:
            raise Http404("VendorGroup not found")

        try:
            data = json.loads(request.body)  # Expect JSON payload
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        vendor_group.code = data.get("code", vendor_group.code)
        vendor_group.description = data.get("description", vendor_group.description)
        vendor_group.currency = data.get("currency", vendor_group.currency)
        if "control_account" in data:
            vendor_group.control_account_id = data["control_account"] or None
        if "prepayment_account" in data:
            vendor_group.prepayment_account_id = data["prepayment_account"] or None
        vendor_group.save()
        return JsonResponse({"message": "VendorGroup updated"})

    def delete(self, request, id):
        try:
            vendor_group = VendorGroup.objects.get(id=id)
        except VendorGroup.DoesNotExist:
            raise Http404("VendorGroup not found")

        vendor_group.delete()
        return JsonResponse({"message": "VendorGroup deleted"})


@method_decorator(login_required, name="dispatch")
class TaxMasterAPI(View):

    def get(self, request, id=None):
        if id:
            try:
                tax_master = TaxMaster.objects.get(id=id)
                return JsonResponse(
                    {
                        "id": tax_master.id,
                        "tax_code": tax_master.tax_code,
                        "description": tax_master.description,
                        "tax_percentage": tax_master.tax_percentage,
                        "rule": tax_master.rule,
                        "coa": tax_master.coa,
                    }
                )
            except TaxMaster.DoesNotExist:
                raise Http404("TaxMaster not found")
        else:
            tax_masters = list(
                TaxMaster.objects.values(
                    "id", "tax_code", "description", "tax_percentage", "rule", "coa"
                )
            )
            return JsonResponse(tax_masters, safe=False)

    def post(self, request):
        try:
            data = json.loads(request.body)  # Expect JSON payload
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        TaxMaster.objects.create(
            tax_code=data.get("tax_code"),
            description=data.get("description"),
            tax_percentage=data.get("tax_percentage"),
            rule=data.get("rule"),
            coa=data.get("coa"),
        )
        return JsonResponse({"message": "TaxMaster created"}, status=201)

    def put(self, request, id):
        try:
            tax_master = TaxMaster.objects.get(id=id)
        except TaxMaster.DoesNotExist:
            raise Http404("TaxMaster not found")

        try:
            data = json.loads(request.body)  # Expect JSON payload
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        tax_master.tax_code = data.get("tax_code", tax_master.tax_code)
        tax_master.description = data.get("description", tax_master.description)
        tax_master.tax_percentage = data.get("tax_percentage", tax_master.tax_percentage)
        tax_master.rule = data.get("rule", tax_master.rule)
        tax_master.coa = data.get("coa", tax_master.coa)
        tax_master.save()

        return JsonResponse({"message": "TaxMaster updated"})

    def delete(self, request, id):
        try:
            tax_master = TaxMaster.objects.get(id=id)
        except TaxMaster.DoesNotExist:
            raise Http404("TaxMaster not found")

        tax_master.delete()
        return JsonResponse({"message": "TaxMaster deleted"})




# ---------------------------------------------------------------------------
# General Purchase (Purchase > Transactions)
# ---------------------------------------------------------------------------

def _general_purchase_to_item_dict(row):
    return {
        "item": row.item_id, "item_code": row.item.item_code,
        "item_description": row.item.description, "unit": row.unit,
        "sent_qty": str(row.sent_qty), "rcv_qty": str(row.rcv_qty), "free_qty": str(row.free_qty),
        "rate": str(row.rate), "discount_percent": str(row.discount_percent),
        "discount_amount": str(row.discount_amount), "gst_percent": str(row.gst_percent),
        "amount": str(row.amount), "farm_warehouse": row.farm_warehouse_id,
        "farm_warehouse_name": row.farm_warehouse.name,
    }


def _general_purchase_list_dict(gp):
    warehouses = ", ".join(dict.fromkeys(
        n for n in gp.items.values_list("farm_warehouse__name", flat=True) if n
    ))
    return {
        "id": gp.id, "date": gp.date.isoformat(), "bill_no": gp.bill_no, "dc_no": gp.dc_no,
        "supplier_name": gp.supplier.name, "item_names": gp.item_names(),
        "quantity": str(gp.total_quantity()), "no_of_bags": str(gp.no_of_bags),
        "avg_rate": str(gp.avg_rate()), "net_amount": str(gp.net_amount),
        "farm_warehouse_names": warehouses, "batch_no": gp.batch_no,
        "vehicle_no": gp.vehicle_no, "driver_name": gp.driver_name,
    }


def _general_purchase_form_context(gp=None):
    return {
        "general_purchase": gp,
        "next_purchase_no": GeneralPurchase._next_purchase_no() if not gp else None,
        "suppliers": Supplier.objects.order_by("name"),
        "items": Item.objects.order_by("item_code"),
        "warehouses": Warehouse.objects.order_by("name"),
        "accounts": ChartOfAccount.objects.order_by("code"),
        "tax_masters": TaxMaster.objects.exclude(tax_percentage__isnull=True).order_by("tax_code"),
        "today": timezone.localdate().isoformat(),
        "existing_items_json": json.dumps(
            [_general_purchase_to_item_dict(row) for row in gp.items.select_related("item", "farm_warehouse")]
        ) if gp else "[]",
        "payment_terms_choices": GeneralPurchase.PAYMENT_TERMS_CHOICES,
        "freight_type_choices": GeneralPurchase.FREIGHT_TYPE_CHOICES,
        "bag_type_choices": GeneralPurchase.BAG_TYPE_CHOICES,
        "other_charges_type_choices": GeneralPurchase.OTHER_CHARGES_TYPE_CHOICES,
        "round_off_type_choices": GeneralPurchase.ROUND_OFF_TYPE_CHOICES,
    }


def _apply_posted_general_purchase_fields(instance, request):
    instance.date = request.POST.get("date") or timezone.localdate()
    instance.supplier_id = request.POST.get("supplier") or None
    instance.bill_no = request.POST.get("bill_no", "").strip()
    instance.dc_no = request.POST.get("dc_no", "").strip()
    instance.vehicle_no = request.POST.get("vehicle_no", "").strip()
    instance.driver_name = request.POST.get("driver_name", "").strip()
    instance.driver_mobile = request.POST.get("driver_mobile", "").strip()
    instance.calculation_based_on = request.POST.get("calculation_based_on") or "Sent Quantity"
    instance.payment_terms = request.POST.get("payment_terms") or "Cash"
    instance.freight_type = request.POST.get("freight_type") or "Extra"
    instance.payment_mode = request.POST.get("payment_mode") or "pay_later"
    instance.pay_account_id = request.POST.get("pay_account") or None
    instance.freight_account_id = request.POST.get("freight_account") or None
    instance.freight_amount = request.POST.get("freight_amount") or 0
    instance.bag_type = request.POST.get("bag_type", "").strip()
    instance.no_of_bags = request.POST.get("no_of_bags") or 0
    instance.batch_no = request.POST.get("batch_no", "").strip()
    instance.expiry_date = request.POST.get("expiry_date") or None
    instance.tds_code = request.POST.get("tds_code", "").strip()
    instance.tds_applicable = request.POST.get("tds_applicable") == "on"
    instance.tds_amount = request.POST.get("tds_amount") or 0
    instance.other_charges_account_id = request.POST.get("other_charges_account") or None
    instance.other_charges_type = request.POST.get("other_charges_type") or "Add"
    instance.other_charges_amount = request.POST.get("other_charges_amount") or 0
    # round_off / round_off_type are auto-derived in compute_net_amount(),
    # never taken from the posted form.
    instance.remarks = request.POST.get("remarks", "").strip()
    if request.FILES.get("reference_document_1"):
        instance.reference_document_1 = request.FILES["reference_document_1"]
    if request.FILES.get("reference_document_2"):
        instance.reference_document_2 = request.FILES["reference_document_2"]
    if request.FILES.get("reference_document_3"):
        instance.reference_document_3 = request.FILES["reference_document_3"]
    validate_value("purchase", "GeneralPurchase", "calculation_based_on", instance.calculation_based_on)


def _save_general_purchase_items(instance, request):
    try:
        rows = json.loads(request.POST.get("items_json") or "[]")
    except json.JSONDecodeError:
        rows = []
    instance.items.all().delete()
    for row in rows:
        if not row.get("item") or not row.get("farm_warehouse"):
            continue
        GeneralPurchaseItem.objects.create(
            purchase=instance, item_id=row["item"], unit=row.get("unit") or "",
            sent_qty=Decimal(str(row.get("sent_qty") or 0)),
            rcv_qty=Decimal(str(row.get("rcv_qty") or 0)),
            free_qty=Decimal(str(row.get("free_qty") or 0)),
            rate=Decimal(str(row.get("rate") or 0)),
            discount_percent=Decimal(str(row.get("discount_percent") or 0)),
            discount_amount=Decimal(str(row.get("discount_amount") or 0)),
            gst_percent=Decimal(str(row.get("gst_percent") or 0)),
            farm_warehouse_id=row["farm_warehouse"],
        )
    instance.net_amount = instance.compute_net_amount()
    instance.save(update_fields=["net_amount", "round_off", "round_off_type"])


@login_required(login_url="login")
def general_purchase_list(request):
    return render(request, "general_purchase_list.html", {
        "categories": ItemCategory.objects.order_by("name"),
        "warehouses": Warehouse.objects.order_by("name"),
    })


@login_required(login_url="login")
def create_general_purchase(request):
    """Add a new General Purchase transaction."""
    if request.method == "POST":
        instance = GeneralPurchase()
        try:
            _apply_posted_general_purchase_fields(instance, request)
            instance.full_clean(exclude=["purchase_no"])
            with transaction.atomic():
                instance.save()
                _save_general_purchase_items(instance, request)
            messages.success(request, "General purchase added successfully.")
            return redirect("general_purchase_list")
        except ValidationError as e:
            messages.error(request, " ".join(e.messages) if hasattr(e, "messages") else str(e))

    return render(request, "general_purchase_form.html", _general_purchase_form_context())


@login_required(login_url="login")
def edit_general_purchase(request, id):
    """Edit an existing General Purchase transaction."""
    instance = get_object_or_404(GeneralPurchase, id=id)

    if request.method == "POST":
        try:
            _apply_posted_general_purchase_fields(instance, request)
            instance.full_clean(exclude=["purchase_no"])
            with transaction.atomic():
                instance.save()
                _save_general_purchase_items(instance, request)
            messages.success(request, "General purchase updated successfully.")
            return redirect("general_purchase_list")
        except ValidationError as e:
            messages.error(request, " ".join(e.messages) if hasattr(e, "messages") else str(e))

    return render(request, "general_purchase_form.html", _general_purchase_form_context(instance))


@login_required(login_url="login")
@require_POST
def delete_general_purchase(request, id):
    """Delete a General Purchase transaction."""
    instance = get_object_or_404(GeneralPurchase, id=id)
    instance.delete()
    messages.success(request, "General purchase deleted successfully.")
    return redirect("general_purchase_list")


@login_required
def general_purchase_api_list(request):
    """JSON rows for the General Purchase register's DataTable + filter bar."""
    from_date = (request.GET.get("from_date") or "").strip()
    to_date = (request.GET.get("to_date") or "").strip()
    category = (request.GET.get("category") or "").strip()
    warehouse = (request.GET.get("warehouse") or "").strip()

    qs = GeneralPurchase.objects.select_related("supplier").prefetch_related(
        "items__item", "items__farm_warehouse")
    if from_date:
        qs = qs.filter(date__gte=from_date)
    if to_date:
        qs = qs.filter(date__lte=to_date)
    if category:
        qs = qs.filter(items__item__category_id=category)
    if warehouse:
        qs = qs.filter(items__farm_warehouse_id=warehouse)
    qs = qs.distinct().order_by("-date", "-id")
    return JsonResponse([_general_purchase_list_dict(gp) for gp in qs], safe=False)



# ---------------------------------------------------------------------------
# Chicks Purchase (Purchase > Transactions)
# ---------------------------------------------------------------------------

def _chicks_purchase_to_item_dict(row):
    return {
        "sent_qty": str(row.sent_qty), "sent_free_percent": str(row.sent_free_percent),
        "rcv_free_percent": str(row.rcv_free_percent),
        "mortality": str(row.mortality), "shortage": str(row.shortage), "weaks": str(row.weaks),
        "excess_qty": str(row.excess_qty), "rcv_qty": str(row.rcv_qty),
        "free_qty": str(row.free_qty), "total_qty": str(row.total_qty),
        "rate": str(row.rate), "amount": str(row.amount),
        "farm_warehouse": row.farm_warehouse_id, "farm_warehouse_name": row.farm_warehouse.name,
        "batch": row.batch,
    }


def _chicks_purchase_list_dict(cp):
    warehouses = ", ".join(dict.fromkeys(
        n for n in cp.items.values_list("farm_warehouse__name", flat=True) if n
    ))
    return {
        "id": cp.id, "date": cp.date.isoformat(), "bill_no": cp.bill_no, "dc_no": cp.dc_no,
        "supplier_name": cp.supplier.name,
        "hatchery_name": cp.hatchery.hatchery_name if cp.hatchery_id else "",
        "item_code": cp.item.item_code,
        "quantity": str(cp.total_quantity()), "avg_rate": str(cp.avg_rate()),
        "net_amount": str(cp.net_amount), "farm_warehouse_names": warehouses,
    }


def _chicks_purchase_form_context(cp=None):
    return {
        "chicks_purchase": cp,
        "next_purchase_no": ChicksPurchase._next_purchase_no() if not cp else None,
        "suppliers": Supplier.objects.order_by("name"),
        "hatcheries": Hatchery.objects.order_by("hatchery_name"),
        "items": Item.objects.order_by("item_code"),
        "warehouses": Warehouse.objects.order_by("name"),
        "accounts": ChartOfAccount.objects.order_by("code"),
        "today": timezone.localdate().isoformat(),
        "existing_items_json": json.dumps(
            [_chicks_purchase_to_item_dict(row) for row in cp.items.select_related("farm_warehouse")]
        ) if cp else "[]",
        "freight_type_choices": ChicksPurchase.FREIGHT_TYPE_CHOICES,
        "bag_type_choices": ChicksPurchase.BAG_TYPE_CHOICES,
        "other_charges_type_choices": ChicksPurchase.OTHER_CHARGES_TYPE_CHOICES,
        "round_off_type_choices": ChicksPurchase.ROUND_OFF_TYPE_CHOICES,
    }


def _apply_posted_chicks_purchase_fields(instance, request):
    instance.date = request.POST.get("date") or timezone.localdate()
    instance.supplier_id = request.POST.get("supplier") or None
    instance.hatchery_id = request.POST.get("hatchery") or None
    instance.item_id = request.POST.get("item") or None
    instance.bill_no = request.POST.get("bill_no", "").strip()
    instance.dc_no = request.POST.get("dc_no", "").strip()
    instance.vehicle_no = request.POST.get("vehicle_no", "").strip()
    instance.driver_name = request.POST.get("driver_name", "").strip()
    instance.freight_type = request.POST.get("freight_type") or "Extra"
    instance.payment_mode = request.POST.get("payment_mode") or "pay_later"
    instance.pay_account_id = request.POST.get("pay_account") or None
    instance.freight_account_id = request.POST.get("freight_account") or None
    instance.freight_amount = request.POST.get("freight_amount") or 0
    instance.bag_type = request.POST.get("bag_type", "").strip()
    instance.no_of_bags = request.POST.get("no_of_bags") or 0
    instance.batch_no = request.POST.get("batch_no", "").strip()
    instance.expiry_date = request.POST.get("expiry_date") or None
    instance.tds_code = request.POST.get("tds_code", "").strip()
    instance.tds_applicable = request.POST.get("tds_applicable") == "on"
    instance.tds_amount = request.POST.get("tds_amount") or 0
    instance.other_charges_account_id = request.POST.get("other_charges_account") or None
    instance.other_charges_type = request.POST.get("other_charges_type") or "Add"
    instance.other_charges_amount = request.POST.get("other_charges_amount") or 0
    # round_off / round_off_type are auto-derived in compute_net_amount(),
    # never taken from the posted form.
    instance.remarks = request.POST.get("remarks", "").strip()
    if request.FILES.get("reference_document_1"):
        instance.reference_document_1 = request.FILES["reference_document_1"]
    if request.FILES.get("reference_document_2"):
        instance.reference_document_2 = request.FILES["reference_document_2"]
    if request.FILES.get("reference_document_3"):
        instance.reference_document_3 = request.FILES["reference_document_3"]


def _save_chicks_purchase_items(instance, request):
    try:
        rows = json.loads(request.POST.get("items_json") or "[]")
    except json.JSONDecodeError:
        rows = []
    instance.items.all().delete()
    for row in rows:
        if not row.get("farm_warehouse"):
            continue
        ChicksPurchaseItem.objects.create(
            purchase=instance,
            sent_qty=Decimal(str(row.get("sent_qty") or 0)),
            sent_free_percent=Decimal(str(row.get("sent_free_percent") or 0)),
            rcv_free_percent=Decimal(str(row.get("rcv_free_percent") or 0)),
            mortality=Decimal(str(row.get("mortality") or 0)),
            shortage=Decimal(str(row.get("shortage") or 0)),
            weaks=Decimal(str(row.get("weaks") or 0)),
            excess_qty=Decimal(str(row.get("excess_qty") or 0)),
            rate=Decimal(str(row.get("rate") or 0)),
            farm_warehouse_id=row["farm_warehouse"],
            batch=row.get("batch") or "",
        )
    instance.net_amount = instance.compute_net_amount()
    instance.save(update_fields=["net_amount", "round_off", "round_off_type"])


@login_required(login_url="login")
def chicks_purchase_list(request):
    return render(request, "chicks_purchase_list.html", {
        "warehouses": Warehouse.objects.order_by("name"),
    })


@login_required(login_url="login")
def create_chicks_purchase(request):
    """Add a new Chicks Purchase transaction."""
    if request.method == "POST":
        instance = ChicksPurchase()
        try:
            _apply_posted_chicks_purchase_fields(instance, request)
            instance.full_clean(exclude=["purchase_no"])
            with transaction.atomic():
                instance.save()
                _save_chicks_purchase_items(instance, request)
            messages.success(request, "Chicks purchase added successfully.")
            return redirect("chicks_purchase_list")
        except ValidationError as e:
            messages.error(request, " ".join(e.messages) if hasattr(e, "messages") else str(e))

    return render(request, "chicks_purchase_form.html", _chicks_purchase_form_context())


@login_required(login_url="login")
def edit_chicks_purchase(request, id):
    """Edit an existing Chicks Purchase transaction."""
    instance = get_object_or_404(ChicksPurchase, id=id)

    if request.method == "POST":
        try:
            _apply_posted_chicks_purchase_fields(instance, request)
            instance.full_clean(exclude=["purchase_no"])
            with transaction.atomic():
                instance.save()
                _save_chicks_purchase_items(instance, request)
            messages.success(request, "Chicks purchase updated successfully.")
            return redirect("chicks_purchase_list")
        except ValidationError as e:
            messages.error(request, " ".join(e.messages) if hasattr(e, "messages") else str(e))

    return render(request, "chicks_purchase_form.html", _chicks_purchase_form_context(instance))


@login_required(login_url="login")
@require_POST
def delete_chicks_purchase(request, id):
    """Delete a Chicks Purchase transaction."""
    instance = get_object_or_404(ChicksPurchase, id=id)
    instance.delete()
    messages.success(request, "Chicks purchase deleted successfully.")
    return redirect("chicks_purchase_list")


@login_required
def chicks_purchase_api_list(request):
    """JSON rows for the Chicks Purchase register's DataTable + filter bar."""
    from_date = (request.GET.get("from_date") or "").strip()
    to_date = (request.GET.get("to_date") or "").strip()

    qs = ChicksPurchase.objects.select_related("supplier", "hatchery", "item").prefetch_related(
        "items__farm_warehouse")
    if from_date:
        qs = qs.filter(date__gte=from_date)
    if to_date:
        qs = qs.filter(date__lte=to_date)
    qs = qs.order_by("-date", "-id")
    return JsonResponse([_chicks_purchase_list_dict(cp) for cp in qs], safe=False)



# ---------------------------------------------------------------------------
# Supplier Payment (Purchase > Transactions)
# ---------------------------------------------------------------------------

def _payment_to_line_dict(row):
    return {
        "supplier": row.supplier_id, "mode": row.mode, "pay_account": row.pay_account_id,
        "pay_account_name": f"{row.pay_account.code} - {row.pay_account.description}",
        "amount": str(row.amount), "bank_charges": str(row.bank_charges),
        "reference_no": row.reference_no, "remarks": row.remarks,
    }


def _payment_list_dict(p):
    return {
        "id": p.id, "date": p.date.isoformat(), "payment_no": p.payment_no,
        "supplier_name": p.supplier_summary(), "mode": p.mode_summary(),
        "method": p.method_summary(), "amount": str(p.total_amount()),
    }


def _payment_form_context(p=None):
    return {
        "payment": p,
        "next_payment_no": SupplierPayment._next_payment_no() if not p else None,
        "suppliers": Supplier.objects.order_by("name"),
        "locations": Warehouse.objects.order_by("name"),
        "accounts": ChartOfAccount.objects.order_by("code"),
        "today": timezone.localdate().isoformat(),
        "mode_choices": SupplierPaymentLine.MODE_CHOICES,
        "existing_lines_json": json.dumps(
            [_payment_to_line_dict(row) for row in p.lines.select_related("pay_account", "supplier")]
        ) if p else "[]",
    }


def _apply_posted_payment_fields(instance, request):
    instance.date = request.POST.get("date") or timezone.localdate()
    instance.location_id = request.POST.get("location") or None


def _save_payment_lines(instance, request):
    try:
        rows = json.loads(request.POST.get("lines_json") or "[]")
    except json.JSONDecodeError:
        rows = []
    instance.lines.all().delete()
    for row in rows:
        if not row.get("supplier") or not row.get("pay_account") or not row.get("amount"):
            continue
        SupplierPaymentLine.objects.create(
            payment=instance, supplier_id=row["supplier"], mode=row.get("mode") or "Cash",
            pay_account_id=row["pay_account"],
            amount=Decimal(str(row.get("amount") or 0)),
            bank_charges=Decimal(str(row.get("bank_charges") or 0)),
            reference_no=row.get("reference_no") or "",
            remarks=row.get("remarks") or "",
        )


@login_required(login_url="login")
def payment_list(request):
    return render(request, "payment_list.html")


@login_required(login_url="login")
def create_payment(request):
    """Add a new Supplier Payment voucher."""
    if request.method == "POST":
        instance = SupplierPayment()
        try:
            _apply_posted_payment_fields(instance, request)
            instance.full_clean(exclude=["payment_no"])
            with transaction.atomic():
                instance.save()
                _save_payment_lines(instance, request)
                if not instance.lines.exists():
                    raise ValidationError("Add at least one payment line.")
            messages.success(request, "Payment added successfully.")
            return redirect("payment_list")
        except ValidationError as e:
            messages.error(request, " ".join(e.messages) if hasattr(e, "messages") else str(e))

    return render(request, "payment_form.html", _payment_form_context())


@login_required(login_url="login")
def edit_payment(request, id):
    """Edit an existing Supplier Payment voucher."""
    instance = get_object_or_404(SupplierPayment, id=id)

    if request.method == "POST":
        try:
            _apply_posted_payment_fields(instance, request)
            instance.full_clean(exclude=["payment_no"])
            with transaction.atomic():
                instance.save()
                _save_payment_lines(instance, request)
                if not instance.lines.exists():
                    raise ValidationError("Add at least one payment line.")
            messages.success(request, "Payment updated successfully.")
            return redirect("payment_list")
        except ValidationError as e:
            messages.error(request, " ".join(e.messages) if hasattr(e, "messages") else str(e))

    return render(request, "payment_form.html", _payment_form_context(instance))


@login_required(login_url="login")
@require_POST
def delete_payment(request, id):
    """Delete a Supplier Payment voucher."""
    instance = get_object_or_404(SupplierPayment, id=id)
    instance.delete()
    messages.success(request, "Payment deleted successfully.")
    return redirect("payment_list")


@login_required
def payment_api_list(request):
    """JSON rows for the Payment register's DataTable + filter bar."""
    from_date = (request.GET.get("from_date") or "").strip()
    to_date = (request.GET.get("to_date") or "").strip()

    qs = SupplierPayment.objects.prefetch_related("lines__pay_account", "lines__supplier")
    if from_date:
        qs = qs.filter(date__gte=from_date)
    if to_date:
        qs = qs.filter(date__lte=to_date)
    qs = qs.order_by("-date", "-id")
    return JsonResponse([_payment_list_dict(p) for p in qs], safe=False)
