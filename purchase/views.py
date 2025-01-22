#pylint: disable=no-member

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views import View
from django.http import Http404, JsonResponse
from django.db.models import F
from django.core.files.storage import default_storage
from .models import Supplier, TaxMaster, TermsConditions
import json

@login_required()
def purchase_order(request):
    return render(request, "purchase_order.html")

@login_required()
def purchase(request):
    return render(request, "purchase.html")



@login_required()
def supplier(request):
    states_and_union_territories = [
        "Andhra Pradesh",
        "Arunachal Pradesh",
        "Assam",
        "Bihar",
        "Chhattisgarh",
        "Goa",
        "Gujarat",
        "Haryana",
        "Himachal Pradesh",
        "Jharkhand",
        "Karnataka",
        "Kerala",
        "Madhya Pradesh",
        "Maharashtra",
        "Manipur",
        "Meghalaya",
        "Mizoram",
        "Nagaland",
        "Odisha",
        "Punjab",
        "Rajasthan",
        "Sikkim",
        "Tamil Nadu",
        "Telangana",
        "Tripura",
        "Uttar Pradesh",
        "Uttarakhand",
        "West Bengal",
        "Andaman and Nicobar Islands",
        "Chandigarh",
        "Dadra and Nagar Haveli and Daman and Diu",
        "Delhi",
        "Jammu and Kashmir",
        "Ladakh",
        "Lakshadweep",
        "Puducherry",
    ]

    # Pass the data as context
    context = {"states_and_union_territories": states_and_union_territories}
    return render(request, "supplier.html", context)



@login_required()
def terms(request):
    return render(request, "t&c.html")



@login_required()
def vendor_groups(request):
    return render(request, "vendor_group.html")


@login_required()
def tax_master(request):
    return render(request, "tax_master.html")


from .models import VendorGroup


@method_decorator(login_required, name="dispatch")
class VendorGroupAPI(View):

    def get(self, request, id=None):
        if id:
            try:
                vendor_group = VendorGroup.objects.get(id=id)
                return JsonResponse(
                    {
                        "id": vendor_group.id,
                        "code": vendor_group.code,
                        "description": vendor_group.description,
                        "currency": vendor_group.currency,
                        "control_account": vendor_group.control_account,
                        "prepayment_account": vendor_group.prepayment_account,
                    }
                )
            except VendorGroup.DoesNotExist:
                raise Http404("VendorGroup not found")
        else:
            vendor_groups = list(
                VendorGroup.objects.values(
                    "id", "code", "description", "currency", "control_account", "prepayment_account"
                )
            )
            return JsonResponse(vendor_groups, safe=False)

    def post(self, request):
        try:
            print(request.body)
            data = json.loads(request.body)  # Expect JSON payload
        except json.JSONDecodeError as e:
            print("error", e)
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        VendorGroup.objects.create(
            code=data.get("code"),
            description=data.get("description"),
            currency=data.get("currency"),
            control_account=data.get("control_account"),
            prepayment_account=data.get("prepayment_account"),
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
        vendor_group.control_account = data.get("control_account", vendor_group.control_account)
        vendor_group.prepayment_account = data.get("prepayment_account", vendor_group.prepayment_account)
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
class SupplierAPI(View):

    def get(self, request, id=None):
        print("called")
        if id:
            try:
                supplier = Supplier.objects.get(id=id)
                return JsonResponse(
                    {
                        "id": supplier.id,
                        "name": supplier.name,
                        "address": supplier.address,
                        "place": supplier.place,
                        "mobile": supplier.mobile,
                        "contact_type": supplier.contact_type,
                        "pan": supplier.pan,
                        "supplier_group": supplier.supplier_group,
                        "gstin": supplier.gstin,
                        "state": supplier.state,
                        "credit_term": supplier.credit_term,
                        "note": supplier.note,
                    }
                )
            except Supplier.DoesNotExist:
                raise Http404("Supplier not found")
        else:
            suppliers = list(
                Supplier.objects.values(
                    "id", "name", "address", "place", "mobile", 
                    "contact_type", "pan", "supplier_group", 
                    "gstin", "state", "credit_term", "note"
                )
            )
            print(suppliers, "suppliers")
            return JsonResponse(suppliers, safe=False)

    def post(self, request):
        print("called")
        try:
            print(request.body)
            data = json.loads(request.body)  # Expect JSON payload
        except json.JSONDecodeError as e:
            print("error", e)
            return JsonResponse({"error": "Invalid JSON"}, status=400)
        
        try:
            Supplier.objects.create(
                name=data.get("name"),
                address=data.get("address"),
                place=data.get("place"),
                mobile=data.get("mobile"),
                contact_type=data.get("contact_type"),
                pan=data.get("pan"),
                supplier_group=data.get("supplier_group"),
                gstin=data.get("gstin"),
                state=data.get("state"),
                credit_term=data.get("credit_term"),
                note=data.get("note"),
            )
            return JsonResponse({"message": "Supplier created"}, status=201)
        except Exception as e:
            print("error", e)
            return JsonResponse({"error": "Invalid JSON"}, status=400)

    def put(self, request, id):
        try:
            supplier = Supplier.objects.get(id=id)
        except Supplier.DoesNotExist:
            raise Http404("Supplier not found")

        try:
            data = json.loads(request.body)  # Expect JSON payload
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        supplier.name = data.get("name", supplier.name)
        supplier.address = data.get("address", supplier.address)
        supplier.place = data.get("place", supplier.place)
        supplier.mobile = data.get("mobile", supplier.mobile)
        supplier.contact_type = data.get("contact_type", supplier.contact_type)
        supplier.pan = data.get("pan", supplier.pan)
        supplier.supplier_group = data.get("supplier_group", supplier.supplier_group)
        supplier.gstin = data.get("gstin", supplier.gstin)
        supplier.state = data.get("state", supplier.state)
        supplier.credit_term = data.get("credit_term", supplier.credit_term)
        supplier.note = data.get("note", supplier.note)
        supplier.save()

        return JsonResponse({"message": "Supplier updated"})

    def delete(self, request, id):
        try:
            supplier = Supplier.objects.get(id=id)
        except Supplier.DoesNotExist:
            raise Http404("Supplier not found")

        supplier.delete()
        return JsonResponse({"message": "Supplier deleted"})


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


@method_decorator(login_required, name="dispatch")
class TermsConditionsAPI(View):

    def get(self, request, id=None):
        if id:
            try:
                terms_conditions = TermsConditions.objects.get(id=id)
                return JsonResponse(
                    {
                        "id": terms_conditions.id,
                        "type": terms_conditions.type,
                        "condition": terms_conditions.condition,
                    }
                )
            except TermsConditions.DoesNotExist:
                raise Http404("TermsConditions not found")
        else:
            terms_conditions = list(
                TermsConditions.objects.values("id", "type", "condition")
            )
            return JsonResponse(terms_conditions, safe=False)

    def post(self, request):
        try:
            data = json.loads(request.body)  # Expect JSON payload
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        TermsConditions.objects.create(
            type=data.get("type"),
            condition=data.get("condition"),
        )
        return JsonResponse({"message": "TermsConditions created"}, status=201)

    def put(self, request, id):
        try:
            terms_conditions = TermsConditions.objects.get(id=id)
        except TermsConditions.DoesNotExist:
            raise Http404("TermsConditions not found")

        try:
            data = json.loads(request.body)  # Expect JSON payload
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        terms_conditions.type = data.get("type", terms_conditions.type)
        terms_conditions.condition = data.get("condition", terms_conditions.condition)
        terms_conditions.save()

        return JsonResponse({"message": "TermsConditions updated"})

    def delete(self, request, id):
        try:
            terms_conditions = TermsConditions.objects.get(id=id)
        except TermsConditions.DoesNotExist:
            raise Http404("TermsConditions not found")

        terms_conditions.delete()
        return JsonResponse({"message": "TermsConditions deleted"})
    
