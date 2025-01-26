#pylint: disable=no-member

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views import View
from django.http import Http404, JsonResponse
from django.db.models import F
from django.core.files.storage import default_storage

import json

from purchase.models import CreditTerm, Supplier, VendorGroup
from sales.models import Customer, CustomerGroup

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

@login_required
def sales(request):
    return render(request, "sales.html")


@login_required
def customer(request):
    context = {
        "customer_groups": CustomerGroup.objects.all(),
        "contact_types": Customer._meta.get_field('contact_type').choices,
        "supplier_groups": Supplier.objects.all(),
        "credit_terms": CreditTerm.objects.all(),
        "states_and_union_territories": states_and_union_territories,
    } 
    return render(request, "customer.html", context)


@login_required
def customer_groups(request):
    return render(request, "customer_groups.html")


@login_required
def sales_price(request):
    return render(request, "sales_price_master.html")


@method_decorator(login_required, name="dispatch")
class CustomerAPI(View):
    def get(self, request, id=None):
        if id:
            try:
                customer = Customer.objects.get(id=id)
                # Returning all fields from the customer model
                customer_data = {
                    "id": customer.id,
                    "name": customer.name,
                    "address": customer.address,
                    "place": customer.place,
                    "phone": customer.phone,
                    "mobile": customer.mobile,
                    "contact_type": customer.contact_type,
                    "pan_tin": customer.pan_tin,
                    "credit_limit": customer.credit_limit,
                    "state": customer.state,
                    "note": customer.note,
                    "supplier_address": customer.supplier_address,
                    "customer_group": customer.customer_group.id if customer.customer_group else None,
                    "credit_term": customer.credit_term.id if customer.credit_term else None,
                }
                return JsonResponse(customer_data)
            except Customer.DoesNotExist:
                raise Http404("Customer not found")
        else:
            # For all customers, retrieve all relevant fields
            customers = list(Customer.objects.values(
                "id", "name", "address", "place", "phone", "mobile", "contact_type", 
                "pan_tin", "credit_limit", "state", "note", "supplier_address",
                "customer_group", "credit_term"
            ))
            return JsonResponse(customers, safe=False)

    def post(self, request):
        try:
            data = json.loads(request.body)  # Expect JSON payload
            print(data)
        except json.JSONDecodeError as e:
            return JsonResponse({"error": "Invalid JSON"}, status=400)


        try:
            # Fetch optional related fields and handle null/blank cases
            customer_group = None
            if "customer_group" in data:
                customer_group = CustomerGroup.objects.filter(id=data["customer_group"]).first()

            supplier_group = None
            if "supplier_group" in data:
                supplier_group = VendorGroup.objects.filter(id=data["supplier_group"]).first()

            credit_term = None
            if "credit_term" in data:
                credit_term = CreditTerm.objects.filter(id=data["credit_term"]).first()

            # Create a new Customer instance
            customer = Customer.objects.create(
                name=data["name"],
                address=data.get("address", ""),
                place=data.get("place", ""),
                phone=data.get("phone"),
                mobile=data.get("mobile"),
                contact_type=data.get("contact_type", "Both"),
                pan_tin=data.get("pan_tin", ""),
                customer_group=customer_group,
                supplier_group=supplier_group,
                credit_limit=data.get("credit_limit", 0.00),
                credit_term=credit_term,
                gstin=data.get("gstin", ""),
                state=data.get("state", ""),
                note=data.get("note", ""),
                supplier_address=data.get("supplier_address", ""),
            )

            return JsonResponse({"message": "Customer created", "id": customer.id}, status=201)

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    def put(self, request, id):
        try:
            customer = Customer.objects.get(id=id)
        except Customer.DoesNotExist:
            return JsonResponse({"error": "Customer not found"}, status=404)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError as e:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        customer.name = data.get("name", customer.name)
        customer.save()
        return JsonResponse({"message": "Customer updated"})

    def delete(self, request, id):
        try:
            customer = Customer.objects.get(id=id)
        except Customer.DoesNotExist:
            return JsonResponse({"error": "Customer not found"}, status=404)

        customer.delete()
        return JsonResponse({"message": "Customer deleted"}, status=204)


@method_decorator(login_required, name="dispatch")
class CustomerGroupAPI(View):

    def get(self, request, id=None):
        """
        Handle GET requests to retrieve either a list of customer groups or a specific customer group.
        """
        if id:
            try:
                customer_group = CustomerGroup.objects.get(id=id)
                return JsonResponse({
                    "id": customer_group.id,
                    "code": customer_group.code,
                    "description": customer_group.description,
                    "currency": customer_group.currency,
                    "control_account": customer_group.control_account,
                    "advance_account": customer_group.advance_account,
                })
            except CustomerGroup.DoesNotExist:
                raise Http404("Customer group not found")
        else:
            customer_groups = list(CustomerGroup.objects.values(
                "id", "code", "description", "currency", "control_account", "advance_account"
            ))
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
            control_account=data["control_account"],
            advance_account=data["advance_account"]
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

        fields_to_update = ["code", "description", "currency", "control_account", "advance_account"]
        for field in fields_to_update:
            setattr(customer_group, field, data.get(field, getattr(customer_group, field)))

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