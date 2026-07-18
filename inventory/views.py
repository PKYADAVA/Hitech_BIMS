from django.db.models import F
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View
from django.contrib.auth.decorators import login_required
from .models import ItemCategory, Item, Sector, Warehouse
from hatchery_master.models import Hatchery
from broiler.models import Branch
import json

# Create your views here.
@login_required
def items(request):
    categories  = ItemCategory.objects.all()
    warehouses = Warehouse.objects.all()
    return render(request, 'item.html', {'categories': categories, 'warehouses': warehouses})


@login_required
def item_category(request):
    return render(request, 'item_category.html')

@login_required
def warehouse(request):
    return render(request, 'sector_offices.html')

@login_required
def warehouse_add(request):
    return render(request, 'warehouse_form.html', {'sectors': Sector.objects.order_by('name'), 'warehouse_id': None})

@login_required
def warehouse_edit(request, id):
    from django.shortcuts import get_object_or_404
    office = get_object_or_404(Warehouse, id=id)
    return render(request, 'warehouse_form.html', {'sectors': Sector.objects.order_by('name'), 'warehouse_id': id, 'office': office})

@login_required
def sector(request):
    return render(request, 'sector.html')



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
        except json.JSONDecodeError as e:
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
                    "id", "item_code", "description", "category__name", "warehouse__name", "valuation_method",
                    "standard_cost_per_unit", "storage_uom", "consumption_uom", "usage", "source",
                    "type", "item_account", "lot_serial_control", "kg_per_bag", "hsn_code"
                )
            )
            return JsonResponse(items, safe=False)

    def post(self, request):
        try:
            data = json.loads(request.body)  # Expect JSON payload
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        
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
            usage=data["usage"]
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

    @staticmethod
    def _to_dict(warehouse):
        return {
            "id": warehouse.id, "name": warehouse.name,
            "sector": warehouse.sector_id,
            "sector_name": warehouse.sector.name if warehouse.sector_id else "",
            "address": warehouse.address, "location": warehouse.location,
        }

    def get(self, request, id=None):
        if id:
            try:
                warehouse = Warehouse.objects.select_related("sector").get(id=id)
                return JsonResponse(self._to_dict(warehouse))
            except Warehouse.DoesNotExist:
                raise Http404("Warehouse not found")
        else:
            warehouses = [self._to_dict(w) for w in Warehouse.objects.select_related("sector").all()]
            return JsonResponse(warehouses, safe=False)

    def post(self, request):
        try:
            data = json.loads(request.body)  # Expect JSON payload
        except json.JSONDecodeError as e:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        if not data.get("name"):
            return JsonResponse({"error": "Sector Description is required"}, status=400)
        if not data.get("sector"):
            return JsonResponse({"error": "Sector Type is required"}, status=400)
        if not data.get("address"):
            return JsonResponse({"error": "Address is required"}, status=400)
        if not data.get("location"):
            return JsonResponse({"error": "Location is required"}, status=400)

        Warehouse.objects.create(
            name=data["name"], sector_id=data["sector"],
            address=data["address"], location=data["location"],
        )
        return JsonResponse({"message": "Office created"}, status=201)

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
        if "sector" in data:
            warehouse.sector_id = data["sector"] or None
        if "address" in data:
            warehouse.address = data["address"]
        if "location" in data:
            warehouse.location = data["location"]
        warehouse.save()
        return JsonResponse({"message": "Office updated"})

    def delete(self, request, id):
        try:
            warehouse = Warehouse.objects.get(id=id)
        except Warehouse.DoesNotExist:
            raise Http404("Warehouse not found")

        warehouse.delete()
        return JsonResponse({"message": "Warehouse deleted"})


@method_decorator(login_required, name="dispatch")
class SectorAPI(View):

    def get(self, request, id=None):
        if id:
            try:
                sector = Sector.objects.get(id=id)
                return JsonResponse({"id": sector.id, "name": sector.name})
            except Sector.DoesNotExist:
                raise Http404("Sector not found")
        else:
            sectors = list(Sector.objects.values("id", "name"))
            return JsonResponse(sectors, safe=False)

    def post(self, request):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        if not data.get("name"):
            return JsonResponse({"error": "Name is required"}, status=400)

        Sector.objects.create(name=data["name"])
        return JsonResponse({"message": "Sector created"}, status=201)

    def put(self, request, id):
        try:
            sector = Sector.objects.get(id=id)
        except Sector.DoesNotExist:
            raise Http404("Sector not found")

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        if "name" in data:
            sector.name = data["name"]
        sector.save()
        return JsonResponse({"message": "Sector updated"})

    def delete(self, request, id):
        try:
            sector = Sector.objects.get(id=id)
        except Sector.DoesNotExist:
            raise Http404("Sector not found")

        sector.delete()
        return JsonResponse({"message": "Sector deleted"})


@login_required
def warehouse_mapping(request):
    return render(request, "warehouse_mapping.html")


@login_required
def warehouse_mapping_data(request):
    offices = list(Warehouse.objects.select_related("branch").values(
        "id", "name", "branch_id", branch_name=F("branch__branch_name")))
    branches = list(Branch.objects.values("id", "branch_name"))
    hatcheries = list(Hatchery.objects.select_related("warehouse").values(
        "id", "hatchery_name", "warehouse_id", warehouse_name=F("warehouse__name")))
    return JsonResponse({"offices": offices, "branches": branches, "hatcheries": hatcheries})


@login_required
def warehouse_mapping_save_branch(request):
    """Sector Mapping: set which broiler Branch one Warehouse/Sector belongs
    to — e.g. Akbarpur Warehouse -> Akbarpur Branch. Many warehouses can
    point to the same branch."""
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    office_id = data.get("warehouse")
    branch_id = data.get("branch") or None
    if not office_id:
        return JsonResponse({"error": "Sector (warehouse) is required"}, status=400)
    office = Warehouse.objects.filter(id=office_id).first()
    if not office:
        return JsonResponse({"error": "Sector not found"}, status=404)
    if branch_id and not Branch.objects.filter(id=branch_id).exists():
        return JsonResponse({"error": "Branch not found"}, status=404)

    office.branch_id = branch_id
    office.save(update_fields=["branch"])
    return JsonResponse({"message": "Mapping saved"})


@login_required
def warehouse_mapping_save_hatchery(request):
    """Map one Hatchery to its Warehouse/Office."""
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    hatchery_id = data.get("hatchery")
    office_id = data.get("warehouse") or None
    if not hatchery_id:
        return JsonResponse({"error": "Hatchery is required"}, status=400)
    hatchery = Hatchery.objects.filter(id=hatchery_id).first()
    if not hatchery:
        return JsonResponse({"error": "Hatchery not found"}, status=404)
    if office_id and not Warehouse.objects.filter(id=office_id).exists():
        return JsonResponse({"error": "Warehouse not found"}, status=404)

    hatchery.warehouse_id = office_id
    hatchery.save(update_fields=["warehouse"])
    return JsonResponse({"message": "Mapping saved"})
    