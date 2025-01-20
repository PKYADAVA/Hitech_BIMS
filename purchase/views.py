#pylint: disable=no-member

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views import View
from django.http import Http404, JsonResponse
from django.db.models import F
from django.core.files.storage import default_storage
from .models import Supplier
import json



@login_required()
def purchase(request):
    return render(request, "purchase.html")



@login_required()
def supplier(request):
    return render(request, "supplier.html")



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
            data = json.loads(request.body)  # Expect JSON payload
        except json.JSONDecodeError:
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
