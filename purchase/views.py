#pylint: disable=no-member

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.http import require_POST
from django.http import Http404, JsonResponse
from django.db.models import F
from django.core.files.storage import default_storage
from django.utils import timezone
from hatchery_master.models import STATES_AND_TERRITORIES
from picklist.services import validate_value
from .models import Supplier, SupplierShippingAddress, TaxMaster
import json

# Used only by the billing/shipping address modals (state field itself is
# picklist-bound, see picklist.bindable_fields.BINDABLE_FIELDS).
states_and_union_territories = STATES_AND_TERRITORIES

@login_required
def purchase_order(request):
    return render(request, "purchase_order.html")

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


