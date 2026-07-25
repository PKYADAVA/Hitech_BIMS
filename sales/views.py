#pylint: disable=no-member

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.http import require_POST
from django.http import Http404, JsonResponse
from django.utils import timezone

import json

from inventory.models import Item, ItemCategory
from account.models import ChartOfAccount
from hatchery_master.models import STATES_AND_TERRITORIES
from picklist.services import validate_value
from sales.models import Customer, CustomerGroup, CustomerShippingAddress, SalesPriceMaster

# Used only by the billing/shipping address modals (state field itself is
# picklist-bound, see picklist.bindable_fields.BINDABLE_FIELDS).
states_and_union_territories = STATES_AND_TERRITORIES

@login_required
def customer(request):
    return render(request, "customer.html", {"customers": Customer.objects.all()})


def _customer_form_context(customer=None):
    return {
        "customer": customer,
        "next_code": Customer.next_code() if not customer else None,
        "states_and_union_territories": states_and_union_territories,
        "to_pay_to_receive_choices": Customer.ToPayToReceive.choices,
        "today": timezone.localdate().isoformat(),
    }


def _apply_posted_customer_fields(instance, request):
    instance.name = request.POST.get("name", "").strip()
    instance.address = request.POST.get("address", "").strip()
    instance.mobile = request.POST.get("mobile", "").strip()
    instance.mobile_2 = request.POST.get("mobile_2", "").strip()
    instance.email = request.POST.get("email", "").strip()
    instance.pan_tin = request.POST.get("pan_tin", "").strip()
    instance.aadhar = request.POST.get("aadhar", "").strip()
    instance.contact_type = request.POST.get("contact_type") or Customer.ContactType.BOTH
    instance.party_category = request.POST.get("party_category") or None
    instance.gstin = request.POST.get("gstin", "").strip()
    instance.state = request.POST.get("state", "").strip()
    instance.opening_balance = request.POST.get("opening_balance") or None
    instance.to_pay_to_receive = request.POST.get("to_pay_to_receive") or None
    instance.as_on_date = request.POST.get("as_on_date") or None
    instance.note = request.POST.get("note", "").strip()
    instance.credit_period = request.POST.get("credit_period") or None
    instance.credit_limit = request.POST.get("credit_limit") or 0
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
    for field in ("state", "contact_type", "party_category"):
        validate_value("sales", "Customer", field, getattr(instance, field))


@login_required(login_url="login")
def create_customer(request):
    """Add a new customer master record."""
    if request.method == "POST":
        instance = Customer()
        try:
            _apply_posted_customer_fields(instance, request)
            instance.full_clean()
            instance.save()
            _create_posted_shipping_addresses(instance, request)
            messages.success(request, "Customer added successfully.")
            return redirect("customer")
        except ValidationError as e:
            messages.error(request, " ".join(e.messages) if hasattr(e, "messages") else str(e))

    return render(request, "customer_form.html", _customer_form_context())


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
        CustomerShippingAddress.objects.create(
            customer=instance, label=label, address=address_text,
            contact_person=(entry.get("contact_person") or "").strip(),
            mobile=(entry.get("mobile") or "").strip(),
            is_default=is_default,
        )


@login_required(login_url="login")
def edit_customer(request, id):
    """Edit an existing customer master record."""
    instance = get_object_or_404(Customer, id=id)

    if request.method == "POST":
        try:
            _apply_posted_customer_fields(instance, request)
            instance.full_clean()
            instance.save()
            messages.success(request, "Customer updated successfully.")
            return redirect("customer")
        except ValidationError as e:
            messages.error(request, " ".join(e.messages) if hasattr(e, "messages") else str(e))

    return render(request, "customer_form.html", _customer_form_context(instance))


@login_required(login_url="login")
@require_POST
def delete_customer(request, id):
    """Delete a customer master record."""
    instance = get_object_or_404(Customer, id=id)
    instance.delete()
    messages.success(request, "Customer deleted successfully.")
    return redirect("customer")


@login_required
def customer_groups(request):
    return render(request, "customer_groups.html", {
        "coa_accounts": ChartOfAccount.objects.filter(status="Active").order_by("code"),
    })


@login_required
def sales_price(request):
    return render(request, "sales_price_master.html")


@method_decorator(login_required, name="dispatch")
class CustomerShippingAddressAPI(View):
    """Customer Master addresses, also used by transaction forms."""
    def get(self, request, customer_id, id=None):
        customer = Customer.objects.get(id=customer_id)
        addresses = customer.shipping_addresses.all()
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

    def post(self, request, customer_id):
        try:
            data = json.loads(request.body)
            customer = Customer.objects.get(id=customer_id)
            if not data.get("label") or not data.get("address"):
                return JsonResponse({"error": "Address label and address are required"}, status=400)
            if data.get("is_default"):
                customer.shipping_addresses.update(is_default=False)
            address = CustomerShippingAddress.objects.create(
                customer=customer, label=data["label"], address=data["address"],
                contact_person=data.get("contact_person", ""), mobile=data.get("mobile", ""),
                is_default=bool(data.get("is_default")),
            )
            return JsonResponse({"id": address.id, "message": "Shipping address saved"}, status=201)
        except Customer.DoesNotExist:
            return JsonResponse({"error": "Customer not found"}, status=404)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)

    def put(self, request, customer_id, id):
        try:
            data = json.loads(request.body)
            address = CustomerShippingAddress.objects.get(id=id, customer_id=customer_id)
            if data.get("is_default"):
                CustomerShippingAddress.objects.filter(customer_id=customer_id).exclude(id=id).update(is_default=False)
            for field in ("label", "address", "contact_person", "mobile"):
                if field in data:
                    setattr(address, field, data[field])
            address.is_default = bool(data.get("is_default", address.is_default))
            address.full_clean(); address.save()
            return JsonResponse({"message": "Shipping address updated"})
        except CustomerShippingAddress.DoesNotExist:
            return JsonResponse({"error": "Shipping address not found"}, status=404)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)

    def delete(self, request, customer_id, id):
        try:
            CustomerShippingAddress.objects.get(id=id, customer_id=customer_id).delete()
            return JsonResponse({"message": "Shipping address deleted"})
        except CustomerShippingAddress.DoesNotExist:
            return JsonResponse({"error": "Shipping address not found"}, status=404)


@method_decorator(login_required, name="dispatch")
class CustomerGroupAPI(View):

    @staticmethod
    def _serialize(group):
        return {
            "id": group.id,
            "code": group.code,
            "description": group.description,
            "currency": group.currency,
            "control_account": group.control_account_id,
            "control_account_display": str(group.control_account) if group.control_account else "",
            "advance_account": group.advance_account_id,
            "advance_account_display": str(group.advance_account) if group.advance_account else "",
        }

    def get(self, request, id=None):
        """
        Handle GET requests to retrieve either a list of customer groups or a specific customer group.
        """
        if id:
            try:
                customer_group = CustomerGroup.objects.select_related("control_account", "advance_account").get(id=id)
                return JsonResponse(self._serialize(customer_group))
            except CustomerGroup.DoesNotExist:
                raise Http404("Customer group not found")
        else:
            customer_groups = [
                self._serialize(group)
                for group in CustomerGroup.objects.select_related("control_account", "advance_account")
            ]
            return JsonResponse(customer_groups, safe=False)

    def post(self, request):
        """
        Handle POST requests to create a new customer group.
        """
        try:
            data = json.loads(request.body)  # Expect JSON payload
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON format"}, status=400)

        required_fields = ["code", "description", "currency", "control_account", "advance_account"]
        for field in required_fields:
            if not data.get(field):
                return JsonResponse({"error": f"{field} field is required"}, status=400)

        CustomerGroup.objects.create(
            code=data["code"],
            description=data["description"],
            currency=data["currency"],
            control_account_id=data["control_account"],
            advance_account_id=data["advance_account"]
        )
        return JsonResponse({"message": "Customer group created successfully"}, status=201)

    def put(self, request, id):
        """
        Handle PUT requests to update an existing customer group.
        """
        try:
            customer_group = CustomerGroup.objects.get(id=id)
        except CustomerGroup.DoesNotExist:
            return JsonResponse({"error": "Customer group not found"}, status=404)

        try:
            data = json.loads(request.body)  # Expect JSON payload
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON format"}, status=400)

        for field in ["code", "description", "currency"]:
            setattr(customer_group, field, data.get(field, getattr(customer_group, field)))
        if "control_account" in data:
            customer_group.control_account_id = data["control_account"] or None
        if "advance_account" in data:
            customer_group.advance_account_id = data["advance_account"] or None

        customer_group.save()
        return JsonResponse({"message": "Customer group updated successfully"})

    def delete(self, request, id):
        """
        Handle DELETE requests to delete an existing customer group.
        """
        try:
            customer_group = CustomerGroup.objects.get(id=id)
        except CustomerGroup.DoesNotExist:
            return JsonResponse({"error": "Customer group not found"}, status=404)

        customer_group.delete()
        return JsonResponse({"message": "Customer group deleted successfully"}, status=204)
    

@method_decorator(login_required, name="dispatch")
class SalesPriceMasterAPI(View):
    def get(self, request, id=None):
        if id:
            try:
                sales_price = SalesPriceMaster.objects.get(id=id)
                sales_price_data = {
                    "id": sales_price.id,
                    "item_category": sales_price.item_category.id,
                    "item": sales_price.item.id,
                    "price": sales_price.price,
                    "date": sales_price.date,
                }
                return JsonResponse(sales_price_data)
            except SalesPriceMaster.DoesNotExist:
                raise Http404("Sales price not found")
        else:
            sales_prices = list(SalesPriceMaster.objects.values(
                "id", "item_category", "item", "price", "date"
            ))
            return JsonResponse(sales_prices, safe=False)

    def post(self, request):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError as e:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        try:
            item_category = ItemCategory.objects.filter(id=data["item_category"]).first()
            item = Item.objects.filter(id=data["item"]).first()

            sales_price = SalesPriceMaster.objects.create(
                item_category=item_category,
                item=item,
                price=data["price"],
                date=data["date"],
            )

            return JsonResponse({"message": "Sales price created", "id": sales_price.id}, status=201)

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    def put(self, request, id):
        try:
            sales_price = SalesPriceMaster.objects.get(id=id)
        except SalesPriceMaster.DoesNotExist:
            return JsonResponse({"error": "Sales price not found"}, status=404)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError as e:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        sales_price.price = data.get("price", sales_price.price)
        sales_price.save()
        return JsonResponse({"message": "Sales price updated"})

    def delete(self, request, id):
        try:
            sales_price = SalesPriceMaster.objects.get(id=id)
        except SalesPriceMaster.DoesNotExist:
            return JsonResponse({"error": "Sales price not found"}, status=404)

        sales_price.delete()
        return JsonResponse({"message": "Sales price deleted"}, status=204)    


# ---------------------------------------------------------------------------
# Sales Invoice (Sales > Transactions)
# ---------------------------------------------------------------------------
from decimal import Decimal
from sales.models import SalesInvoice, SalesInvoiceItem
from inventory.models import Warehouse


def _si_num(v):
    try:
        return Decimal(str(v)) if v not in (None, "") else Decimal("0")
    except Exception:
        return Decimal("0")


def _sales_invoice_list_dict(inv):
    return {
        "id": inv.id, "date": inv.date.isoformat(), "invoice_no": inv.invoice_no,
        "transaction_type": inv.transaction_type,
        "customer_name": inv.customer.name if inv.customer_id else "",
        "reference_no": inv.reference_no,
        "total_items": inv.total_items(),
        "amount": str(inv.net_amount),
        "is_active": inv.is_active,
    }


def _sales_invoice_item_dict(row):
    return {
        "item": row.item_id, "item_code": row.item.item_code,
        "item_name": row.item.description, "batch_no": row.batch_no,
        "hsn_sac": row.hsn_sac, "uom": row.uom,
        "quantity": str(row.quantity), "free_qty": str(row.free_qty), "rate": str(row.rate),
        "discount_percent": str(row.discount_percent),
        "taxable_amount": str(row.taxable_amount),
        "gst_percent": str(row.gst_percent), "gst_amount": str(row.gst_amount),
        "amount": str(row.amount),
    }


def _sales_invoice_form_context(inv=None):
    from account.models import TermsConditions, BankCashMaster, CompanyProfile
    items = list(Item.objects.order_by("item_code").values(
        "id", "item_code", "description", "hsn_code", "storage_uom", "standard_cost_per_unit"))
    return {
        "invoice": inv,
        "next_no": SalesInvoice._next_no() if not inv else None,
        "customers": Customer.objects.order_by("name"),
        "branches": Warehouse.objects.order_by("name"),
        "org_centres": __import__("account.models", fromlist=["OrganizationCentre"]).OrganizationCentre.objects.order_by("name"),
        "items_json": json.dumps(items, default=str),
        "transaction_types": SalesInvoice.TRANSACTION_TYPE_CHOICES,
        "today": timezone.localdate().isoformat(),
        "existing_items_json": json.dumps(
            [_sales_invoice_item_dict(r) for r in inv.items.select_related("item")]) if inv else "[]",
        "terms_list": list(TermsConditions.objects.order_by("type").values("id", "type", "party_type", "condition")),
        "banks": list(BankCashMaster.objects.order_by("name").values("id", "code", "name", "micr", "address", "contact_person", "is_cash")),
        "company": CompanyProfile.get_solo(),
        "states_and_union_territories": states_and_union_territories,
        "terms_json": json.dumps({t.id: t.condition for t in TermsConditions.objects.all()}),
        "banks_json": json.dumps({b["id"]: b for b in BankCashMaster.objects.values("id", "code", "name", "micr", "address", "contact_person")}, default=str),
    }


def _apply_posted_invoice(instance, request):
    d = request.POST
    instance.transaction_type = d.get("transaction_type") or "Sales Invoice"
    instance.date = d.get("date") or timezone.localdate()
    instance.customer_id = d.get("customer") or None
    instance.billing_address = d.get("billing_address") or ""
    instance.shipping_address = d.get("shipping_address") or ""
    instance.gstin = d.get("gstin") or ""
    instance.reference_no = d.get("reference_no") or ""
    instance.reference_date = d.get("reference_date") or None
    instance.transportation = d.get("transportation") or ""
    instance.vehicle_no = d.get("vehicle_no") or ""
    instance.place_of_supply = d.get("place_of_supply") or ""
    instance.eway_bill_no = d.get("eway_bill_no") or ""
    instance.branch_id = d.get("branch") or None
    instance.organization_centre_id = d.get("organization_centre") or None
    instance.sales_person = d.get("sales_person") or ""
    instance.payment_terms = d.get("payment_terms") or ""
    instance.due_date = d.get("due_date") or None
    instance.remarks = d.get("remarks") or ""
    instance.terms_conditions_id = d.get("terms_conditions") or None
    instance.bank_account_id = d.get("bank_account") or None
    instance.print_bank_details = bool(d.get("print_bank_details"))
    instance.other_charges_amount = _si_num(d.get("other_charges_amount"))
    instance.round_off = _si_num(d.get("round_off"))


def _save_invoice_items(instance, request):
    try:
        rows = json.loads(request.POST.get("items_json") or "[]")
    except json.JSONDecodeError:
        rows = []
    instance.items.all().delete()
    for r in rows:
        if not r.get("item"):
            continue
        qty = _si_num(r.get("quantity"))
        free = _si_num(r.get("free_qty"))
        rate = _si_num(r.get("rate"))
        disc = _si_num(r.get("discount_percent"))
        gross = qty * rate
        taxable = gross - (gross * disc / Decimal("100"))
        gst_pct = _si_num(r.get("gst_percent"))
        gst_amt = taxable * gst_pct / Decimal("100")
        SalesInvoiceItem.objects.create(
            invoice=instance, item_id=r["item"], batch_no=r.get("batch_no") or "",
            hsn_sac=r.get("hsn_sac") or "", uom=r.get("uom") or "",
            quantity=qty, free_qty=free, rate=rate, discount_percent=disc,
            taxable_amount=taxable.quantize(Decimal("0.01")),
            gst_percent=gst_pct, gst_amount=gst_amt.quantize(Decimal("0.01")),
            amount=(taxable + gst_amt).quantize(Decimal("0.01")),
        )
    instance.net_amount = instance.compute_net_amount()
    instance.save(update_fields=["net_amount"])


@login_required(login_url="login")
def sales_invoice_list(request):
    return render(request, "sales_invoice_list.html")


@login_required(login_url="login")
def sales_invoice_api_list(request):
    from_date = (request.GET.get("from_date") or "").strip()
    to_date = (request.GET.get("to_date") or "").strip()
    qs = SalesInvoice.objects.select_related("customer")
    if from_date:
        qs = qs.filter(date__gte=from_date)
    if to_date:
        qs = qs.filter(date__lte=to_date)
    return JsonResponse([_sales_invoice_list_dict(i) for i in qs.order_by("-date", "-id")], safe=False)


@login_required(login_url="login")
def create_sales_invoice(request):
    if request.method == "POST":
        instance = SalesInvoice(created_by=request.user if request.user.is_authenticated else None)
        try:
            _apply_posted_invoice(instance, request)
            if not instance.customer_id:
                raise ValidationError("Select a customer.")
            instance.full_clean(exclude=["invoice_no"])
            with transaction.atomic():
                instance.save()
                _save_invoice_items(instance, request)
                if not instance.items.exists():
                    raise ValidationError("Add at least one item.")
            messages.success(request, "Sales Invoice created successfully.")
            return redirect("sales_invoice_list")
        except ValidationError as e:
            messages.error(request, " ".join(e.messages) if hasattr(e, "messages") else str(e))
    return render(request, "sales_invoice_form.html", _sales_invoice_form_context())


@login_required(login_url="login")
def edit_sales_invoice(request, id):
    instance = get_object_or_404(SalesInvoice, id=id)
    if request.method == "POST":
        try:
            _apply_posted_invoice(instance, request)
            if not instance.customer_id:
                raise ValidationError("Select a customer.")
            instance.full_clean(exclude=["invoice_no"])
            with transaction.atomic():
                instance.save()
                _save_invoice_items(instance, request)
                if not instance.items.exists():
                    raise ValidationError("Add at least one item.")
            messages.success(request, "Sales Invoice updated successfully.")
            return redirect("sales_invoice_list")
        except ValidationError as e:
            messages.error(request, " ".join(e.messages) if hasattr(e, "messages") else str(e))
    return render(request, "sales_invoice_form.html", _sales_invoice_form_context(instance))


@login_required(login_url="login")
@require_POST
def delete_sales_invoice(request, id):
    get_object_or_404(SalesInvoice, id=id).delete()
    messages.success(request, "Sales Invoice deleted successfully.")
    return redirect("sales_invoice_list")
