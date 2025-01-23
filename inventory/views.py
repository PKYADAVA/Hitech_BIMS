from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View
from django.contrib.auth.decorators import login_required
from .models import ItemCategory, Item, Warehouse
import json

# Create your views here.

def inventory(request):
    return render(request, 'inventory.html')

def items(request):
    return render(request, 'item.html')


def item_category(request):
    return render(request, 'item_category.html')


def warehouse(request):
    return render(request, 'sector_offices.html')



@method_decorator(login_required, name="dispatch")
class CategoryAPI(View):

    def get(self, request, id=None):
        if id:
            try:
                category = ItemCategory.objects.get(id=id)
                return JsonResponse({"id": category.id, "name": category.name})
            except ItemCategory.DoesNotExist:
                raise Http404("Category not found")
        else:
            categories = list(ItemCategory.objects.values("id", "name"))
            return JsonResponse(categories, safe=False)

    def post(self, request):
        try:
            data = json.loads(request.body)  # Expect JSON payload
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        if not data.get("name"):
            return JsonResponse({"error": "Name is required"}, status=400)

        ItemCategory.objects.create(name=data["name"])
        return JsonResponse({"message": "Category created"}, status=201)

    def put(self, request, id):
        try:
            category = ItemCategory.objects.get(id=id)
        except ItemCategory.DoesNotExist:
            raise Http404("Category not found")

        try:
            data = json.loads(request.body)  # Expect JSON payload
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        if "name" in data:
            category.name = data["name"]
            category.save()
            return JsonResponse({"message": "Category updated"})

        return JsonResponse({"error": "No updates provided"}, status=400)

    def delete(self, request, id):
        try:
            category = ItemCategory.objects.get(id=id)
        except ItemCategory.DoesNotExist:
            raise Http404("Category not found")

        category.delete()
        return JsonResponse({"message": "Category deleted"})


@method_decorator(login_required, name="dispatch")
class CategoryAPI(View):

    def get(self, request, id=None):
        if id:
            try:
                category = ItemCategory.objects.get(id=id)
                return JsonResponse({"id": category.id, "name": category.name})
            except ItemCategory.DoesNotExist:
                raise Http404("Category not found")
        else:
            categories = list(ItemCategory.objects.values("id", "name"))
            return JsonResponse(categories, safe=False)

    def post(self, request):
        try:
            data = json.loads(request.body)  # Expect JSON payload
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        if not data.get("name"):
            return JsonResponse({"error": "Name is required"}, status=400)

        ItemCategory.objects.create(name=data["name"])
        return JsonResponse({"message": "Category created"}, status=201)

    def put(self, request, id):
        try:
            category = ItemCategory.objects.get(id=id)
        except ItemCategory.DoesNotExist:
            raise Http404("Category not found")

        try:
            data = json.loads(request.body)  # Expect JSON payload
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        if "name" in data:
            category.name = data["name"]
            category.save()
            return JsonResponse({"message": "Category updated"})

        return JsonResponse({"error": "No updates provided"}, status=400)

    def delete(self, request, id):
        try:
            category = ItemCategory.objects.get(id=id)
        except ItemCategory.DoesNotExist:
            raise Http404("Category not found")

        category.delete()
        return JsonResponse({"message": "Category deleted"})


@method_decorator(login_required, name="dispatch")
class ItemAPI(View):

    def get(self, request, id=None):
        if id:
            try:
                item = Item.objects.get(id=id)
                return JsonResponse({
                    "id": item.id,
                    "item_code": item.item_code,
                    "description": item.description,
                    "category": item.category.id,
                    "warehouse": item.warehouse.id,
                    "valuation_method": item.valuation_method,
                    "standard_cost_per_unit": str(item.standard_cost_per_unit),
                    "storage_uom": item.storage_uom,
                    "consumption_uom": item.consumption_uom,
                    "usage": item.usage,
                    "source": item.source,
                    "type": item.type,
                    "item_account": item.item_account,
                    "lot_serial_control": item.lot_serial_control,
                    "kg_per_bag": str(item.kg_per_bag) if item.kg_per_bag else None,
                    "hsn_code": item.hsn_code,
                })
            except Item.DoesNotExist:
                raise Http404("Item not found")
        else:
            items = list(
                Item.objects.values(
                    "id", "item_code", "description", "category", "warehouse", "valuation_method",
                    "standard_cost_per_unit", "storage_uom", "consumption_uom", "usage", "source",
                    "type", "item_account", "lot_serial_control", "kg_per_bag", "hsn_code"
                )
            )
            print(items, "items")
            return JsonResponse(items, safe=False)

    def post(self, request):
        try:
            data = json.loads(request.body)  # Expect JSON payload
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        required_fields = [
            "item_code", "description", "category", "warehouse", "valuation_method",
            "standard_cost_per_unit", "storage_uom", "consumption_uom", "usage", "source", "type", "item_account"
        ]

        if not all(field in data for field in required_fields):
            return JsonResponse({"error": "Missing required fields"}, status=400)

        try:
            category = ItemCategory.objects.get(id=data["category"])
        except ItemCategory.DoesNotExist:
            return JsonResponse({"error": "Invalid category ID"}, status=400)

        try:
            warehouse = Warehouse.objects.get(id=data["warehouse"])
        except Warehouse.DoesNotExist:
            return JsonResponse({"error": "Invalid warehouse ID"}, status=400)

        Item.objects.create(
            item_code=data["item_code"],
            description=data["description"],
            category=category,
            warehouse=warehouse,
            valuation_method=data["valuation_method"],
            standard_cost_per_unit=data["standard_cost_per_unit"],
            storage_uom=data["storage_uom"],
            consumption_uom=data["consumption_uom"],
            usage=data["usage"],
            source=data["source"],
            type=data["type"],
            item_account=data["item_account"],
            lot_serial_control=data.get("lot_serial_control", "None"),
            kg_per_bag=data.get("kg_per_bag"),
            hsn_code=data.get("hsn_code"),
        )
        return JsonResponse({"message": "Item created"}, status=201)

    def put(self, request, id):
        try:
            item = Item.objects.get(id=id)
        except Item.DoesNotExist:
            raise Http404("Item not found")

        try:
            data = json.loads(request.body)  # Expect JSON payload
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        for field in [
            "item_code", "description", "valuation_method", "standard_cost_per_unit",
            "storage_uom", "consumption_uom", "usage", "source", "type", "item_account", "lot_serial_control",
            "kg_per_bag", "hsn_code"
        ]:
            if field in data:
                setattr(item, field, data[field])

        if "category" in data:
            try:
                item.category = ItemCategory.objects.get(id=data["category"])
            except ItemCategory.DoesNotExist:
                return JsonResponse({"error": "Invalid category ID"}, status=400)

        if "warehouse" in data:
            try:
                item.warehouse = Warehouse.objects.get(id=data["warehouse"])
            except Warehouse.DoesNotExist:
                return JsonResponse({"error": "Invalid warehouse ID"}, status=400)

        item.save()
        return JsonResponse({"message": "Item updated"})

    def delete(self, request, id):
        try:
            item = Item.objects.get(id=id)
        except Item.DoesNotExist:
            raise Http404("Item not found")

        item.delete()
        return JsonResponse({"message": "Item deleted"})


@method_decorator(login_required, name="dispatch")
class WarehouseAPI(View):

    def get(self, request, id=None):
        if id:
            try:
                warehouse = Warehouse.objects.get(id=id)
                return JsonResponse({"id": warehouse.id, "name": warehouse.name})
            except Warehouse.DoesNotExist:
                raise Http404("Warehouse not found")
        else:
            warehouses = list(Warehouse.objects.values("id", "name"))
            return JsonResponse(warehouses, safe=False)

    def post(self, request):
        try:
            print(request.body,"request.body")
            data = json.loads(request.body)  # Expect JSON payload
            print(data,"data")
        except json.JSONDecodeError as e:
            print("error", e)
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        if not data.get("name"):
            return JsonResponse({"error": "Name is required"}, status=400)

        Warehouse.objects.create(name=data["name"])
        return JsonResponse({"message": "Warehouse created"}, status=201)

    def put(self, request, id):
        try:
            warehouse = Warehouse.objects.get(id=id)
        except Warehouse.DoesNotExist:
            raise Http404("Warehouse not found")

        try:
            data = json.loads(request.body)  # Expect JSON payload
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        if "name" in data:
            warehouse.name = data["name"]
            warehouse.save()
            return JsonResponse({"message": "Warehouse updated"})

        return JsonResponse({"error": "No updates provided"}, status=400)

    def delete(self, request, id):
        try:
            warehouse = Warehouse.objects.get(id=id)
        except Warehouse.DoesNotExist:
            raise Http404("Warehouse not found")

        warehouse.delete()
        return JsonResponse({"message": "Warehouse deleted"})
    