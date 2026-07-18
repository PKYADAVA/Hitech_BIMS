from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.contrib.auth.decorators import login_required
from .models import (
    ItemCategory, Item, Sector, Warehouse, StockTransfer, MedicineTransfer, MedicineTransferItem,
    InventoryAdjustment, InventoryAdjustmentItem, StockIssue, StockIssueItem, StockReceive, StockReceiveItem,
)
from hatchery_master.models import Hatchery
from broiler.models import Branch, BroilerFarm, BroilerBatch
from account.models import ChartOfAccount
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
    return render(request, 'sector_offices.html', {'sectors': Sector.objects.order_by('name')})

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
            "id": warehouse.id, "code": warehouse.code, "name": warehouse.name,
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


# ---------------------------------------------------------------------------
# Stock Transfer (Inventory > Transactions)
# ---------------------------------------------------------------------------

def _location_dict(location_type, warehouse, farm):
    if location_type == 'farm':
        return {
            "type": "farm", "id": farm.id if farm else None,
            "name": farm.farm_name if farm else "",
        }
    return {
        "type": "warehouse", "id": warehouse.id if warehouse else None,
        "name": warehouse.name if warehouse else "",
    }


def _stock_transfer_to_dict(row):
    from_loc = _location_dict(row.from_location_type, row.from_warehouse, row.from_farm)
    to_loc = _location_dict(row.to_location_type, row.to_warehouse, row.to_farm)
    return {
        "id": row.id, "date": row.date.isoformat(), "trnum": row.trnum, "dc_no": row.dc_no,
        "item": row.item_id, "item_code": row.item.item_code if row.item_id else "",
        "item_name": row.item.description if row.item_id else "",
        "unit": row.item.storage_uom if row.item_id else "",
        "quantity": str(row.quantity), "purchase_rate": str(row.purchase_rate), "rate": str(row.rate),
        "stock": str(row.stock),
        "from_location_type": from_loc["type"], "from_location_id": from_loc["id"],
        "from_location_name": from_loc["name"],
        "from_batch": row.from_batch_id, "from_batch_name": row.from_batch.batch_name if row.from_batch_id else "",
        "to_location_type": to_loc["type"], "to_location_id": to_loc["id"], "to_location_name": to_loc["name"],
        "to_batch": row.to_batch_id, "to_batch_name": row.to_batch.batch_name if row.to_batch_id else "",
        "vehicle_no": row.vehicle_no, "driver_name": row.driver_name,
        "remarks": row.remarks,
    }


def _apply_stock_transfer_row(instance, row, user):
    if row.get("date"):
        instance.date = timezone.datetime.fromisoformat(row["date"]).date()
    instance.dc_no = row.get("dc_no") or ""
    instance.item_id = row.get("item") or None
    instance.quantity = Decimal(str(row.get("quantity") or 0))
    instance.purchase_rate = Decimal(str(row.get("purchase_rate") or 0))
    instance.rate = Decimal(str(row.get("rate") or 0))

    from_type = row.get("from_location_type") or "warehouse"
    from_id = row.get("from_location_id") or None
    instance.from_location_type = from_type
    instance.from_warehouse_id = from_id if from_type == "warehouse" else None
    instance.from_farm_id = from_id if from_type == "farm" else None
    instance.from_batch_id = row.get("from_batch") if from_type == "farm" else None

    to_type = row.get("to_location_type") or "warehouse"
    to_id = row.get("to_location_id") or None
    instance.to_location_type = to_type
    instance.to_warehouse_id = to_id if to_type == "warehouse" else None
    instance.to_farm_id = to_id if to_type == "farm" else None
    instance.to_batch_id = row.get("to_batch") if to_type == "farm" else None

    instance.vehicle_no = row.get("vehicle_no") or ""
    instance.driver_name = row.get("driver_name") or ""
    instance.remarks = row.get("remarks") or ""
    if not instance.pk:
        instance.created_by = user
    prev = StockTransfer.previous_stock(from_type, from_id, instance.item_id, instance.date, instance.pk)
    instance.stock = (Decimal(str(prev)) - instance.quantity if from_id and instance.item_id else 0)


def _recompute_stock_transfer_chain(location_type, location_id, item_id):
    """Recomputes running stock for every transfer out of this source
    location (Warehouse or Farm) that touches item_id, walking
    chronologically from an opening balance of 0 (see
    StockTransfer.previous_stock)."""
    if not location_type or not location_id or not item_id:
        return
    filters = {"from_location_type": location_type, "item_id": item_id}
    filters["from_farm_id" if location_type == "farm" else "from_warehouse_id"] = location_id
    qs = StockTransfer.objects.filter(**filters).order_by('date', 'id')
    running = Decimal('0')
    for r in qs:
        running -= r.quantity
        if r.stock != running:
            r.stock = running
            r.save(update_fields=["stock"])


@method_decorator(login_required, name="dispatch")
class StockTransferListTemplateView(View):
    def get(self, request):
        return render(request, "stock_transfer_list.html", {
            "categories": ItemCategory.objects.order_by("name"),
            "items": Item.objects.order_by("item_code"),
            "warehouses": Warehouse.objects.order_by("name"),
            "farms": BroilerFarm.objects.order_by("farm_name"),
        })


@method_decorator(login_required, name="dispatch")
class StockTransferFormTemplateView(View):
    def get(self, request):
        return render(request, "stock_transfer_form.html", {
            "items": Item.objects.order_by("item_code"),
            "warehouses": Warehouse.objects.order_by("name"),
            "farms": BroilerFarm.objects.order_by("farm_name"),
            "today": timezone.localdate().isoformat(),
        })


@method_decorator(login_required, name="dispatch")
class StockTransferAPI(View):

    def get(self, request, id=None):
        if id:
            try:
                row = StockTransfer.objects.select_related(
                    "item", "from_warehouse", "from_farm", "from_batch",
                    "to_warehouse", "to_farm", "to_batch").get(id=id)
                return JsonResponse(_stock_transfer_to_dict(row))
            except StockTransfer.DoesNotExist:
                raise Http404("Stock transfer not found")

        qs = StockTransfer.objects.select_related(
            "item", "from_warehouse", "from_farm", "from_batch", "to_warehouse", "to_farm", "to_batch")
        from_date = (request.GET.get("from_date") or "").strip()
        to_date = (request.GET.get("to_date") or "").strip()
        category = (request.GET.get("category") or "").strip()
        item_id = (request.GET.get("item") or "").strip()
        from_location_type = (request.GET.get("from_location_type") or "").strip()
        from_location_id = (request.GET.get("from_location_id") or "").strip()
        to_location_type = (request.GET.get("to_location_type") or "").strip()
        to_location_id = (request.GET.get("to_location_id") or "").strip()
        if from_date:
            qs = qs.filter(date__gte=from_date)
        if to_date:
            qs = qs.filter(date__lte=to_date)
        if category:
            qs = qs.filter(item__category_id=category)
        if item_id:
            qs = qs.filter(item_id=item_id)
        if from_location_type and from_location_id:
            qs = qs.filter(from_location_type=from_location_type, **{
                ("from_farm_id" if from_location_type == "farm" else "from_warehouse_id"): from_location_id,
            })
        if to_location_type and to_location_id:
            qs = qs.filter(to_location_type=to_location_type, **{
                ("to_farm_id" if to_location_type == "farm" else "to_warehouse_id"): to_location_id,
            })
        return JsonResponse([_stock_transfer_to_dict(r) for r in qs.order_by("-date", "-id")], safe=False)

    @transaction.atomic
    def post(self, request):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        rows = data.get("rows") or []
        if not rows:
            return JsonResponse({"error": "Add at least one transfer row"}, status=400)

        created = []
        try:
            for row in rows:
                if not row.get("item") or not row.get("from_location_id") or not row.get("to_location_id"):
                    continue
                instance = StockTransfer()
                _apply_stock_transfer_row(instance, row, request.user)
                instance.full_clean(exclude=["trnum"])
                instance.save()
                created.append(instance.id)
                _recompute_stock_transfer_chain(instance.from_location_type, instance.from_warehouse_id
                                                or instance.from_farm_id, instance.item_id)
        except ValidationError as e:
            return JsonResponse({"error": " ".join(e.messages) if hasattr(e, "messages") else str(e)}, status=400)

        if not created:
            return JsonResponse(
                {"error": "Add at least one row with Item, From Location and To Location selected"}, status=400)
        return JsonResponse({"message": "Stock transfer created", "ids": created}, status=201)

    @transaction.atomic
    def put(self, request, id):
        try:
            instance = StockTransfer.objects.get(id=id)
        except StockTransfer.DoesNotExist:
            raise Http404("Stock transfer not found")

        old_key = (instance.from_location_type, instance.from_warehouse_id or instance.from_farm_id)
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        try:
            _apply_stock_transfer_row(instance, data, request.user)
            instance.full_clean(exclude=["trnum"])
            instance.save()
        except ValidationError as e:
            return JsonResponse({"error": " ".join(e.messages) if hasattr(e, "messages") else str(e)}, status=400)

        new_key = (instance.from_location_type, instance.from_warehouse_id or instance.from_farm_id)
        for location_type, location_id in {old_key, new_key}:
            _recompute_stock_transfer_chain(location_type, location_id, instance.item_id)
        return JsonResponse({"message": "Stock transfer updated"})

    def delete(self, request, id):
        try:
            instance = StockTransfer.objects.get(id=id)
        except StockTransfer.DoesNotExist:
            raise Http404("Stock transfer not found")

        location_type = instance.from_location_type
        location_id = instance.from_warehouse_id or instance.from_farm_id
        item_id = instance.item_id
        instance.delete()
        _recompute_stock_transfer_chain(location_type, location_id, item_id)
        return JsonResponse({"message": "Stock transfer deleted"})


@login_required
def stock_transfer_item_lookup(request):
    """UOM and purchase rate for a selected item, for the Add form's
    auto-filled UOM / Purchase Rate fields."""
    item_id = request.GET.get("item")
    item = Item.objects.filter(id=item_id).first() if item_id else None
    return JsonResponse({
        "unit": item.storage_uom if item else "",
        "purchase_rate": str(item.standard_cost_per_unit) if item else "0",
    })


@login_required
def stock_transfer_stock_lookup(request):
    """Opening stock of an item at a source location (Warehouse or Farm) as
    of a given date — the closing balance of the most recent saved transfer
    before that date (0 if none)."""
    location_type = request.GET.get("location_type")
    location_id = request.GET.get("location_id")
    item_id = request.GET.get("item")
    entry_date = request.GET.get("date")
    if not location_type or not location_id or not item_id or not entry_date:
        return JsonResponse({"stock": "0"})
    d = timezone.datetime.fromisoformat(entry_date).date()
    stock = StockTransfer.previous_stock(location_type, int(location_id), int(item_id), d, None)
    return JsonResponse({"stock": str(stock)})


@login_required
def stock_transfer_farm_batches(request):
    """Batches for a Farm, for the Add/Edit form's Batch box that appears
    when From Location is a Farm."""
    farm_id = request.GET.get("farm")
    if not farm_id:
        return JsonResponse([], safe=False)
    batches = BroilerBatch.objects.filter(broiler_farm_id=farm_id).order_by("-start_date", "-id")
    return JsonResponse([
        {"id": b.id, "batch_name": b.batch_name, "is_active": b.end_date is None}
        for b in batches
    ], safe=False)


# ---------------------------------------------------------------------------
# Medicine Vaccine Transfer (Inventory > Transactions)
# ---------------------------------------------------------------------------

def _medicine_transfer_list_dict(header):
    from_loc = _location_dict(header.from_location_type, header.from_warehouse, header.from_farm)
    to_loc = _location_dict(header.to_location_type, header.to_warehouse, header.to_farm)
    lines = list(header.items.all())
    return {
        "id": header.id, "date": header.date.isoformat(), "trnum": header.trnum, "dc_no": header.dc_no,
        "from_location_type": from_loc["type"], "from_location_id": from_loc["id"],
        "from_location_name": from_loc["name"],
        "from_batch": header.from_batch_id, "from_batch_name": header.from_batch.batch_name if header.from_batch_id else "",
        "to_location_type": to_loc["type"], "to_location_id": to_loc["id"], "to_location_name": to_loc["name"],
        "to_batch": header.to_batch_id, "to_batch_name": header.to_batch.batch_name if header.to_batch_id else "",
        "description": ", ".join(l.item.description for l in lines if l.item_id),
        "quantity": str(sum((l.quantity for l in lines), Decimal('0'))),
        "vehicle_no": header.vehicle_no, "driver_name": header.driver_name,
    }


def _medicine_transfer_detail_dict(header):
    detail = _medicine_transfer_list_dict(header)
    detail.update({
        "transport_cost": str(header.transport_cost),
        "paid_by": header.paid_by_id,
        "paid_by_label": f"{header.paid_by.code} - {header.paid_by.description}" if header.paid_by_id else "",
        "items": [
            {
                "id": l.id, "item": l.item_id, "item_code": l.item.item_code if l.item_id else "",
                "item_name": l.item.description if l.item_id else "",
                "unit": l.item.storage_uom if l.item_id else "",
                "quantity": str(l.quantity), "rate": str(l.rate), "remarks": l.remarks, "stock": str(l.stock),
            }
            for l in header.items.all()
        ],
    })
    return detail


def _apply_medicine_transfer_header(instance, data, user):
    if data.get("date"):
        instance.date = timezone.datetime.fromisoformat(data["date"]).date()
    instance.dc_no = data.get("dc_no") or ""

    from_type = data.get("from_location_type") or "warehouse"
    from_id = data.get("from_location_id") or None
    instance.from_location_type = from_type
    instance.from_warehouse_id = from_id if from_type == "warehouse" else None
    instance.from_farm_id = from_id if from_type == "farm" else None
    instance.from_batch_id = data.get("from_batch") if from_type == "farm" else None

    to_type = data.get("to_location_type") or "warehouse"
    to_id = data.get("to_location_id") or None
    instance.to_location_type = to_type
    instance.to_warehouse_id = to_id if to_type == "warehouse" else None
    instance.to_farm_id = to_id if to_type == "farm" else None
    instance.to_batch_id = data.get("to_batch") if to_type == "farm" else None

    instance.vehicle_no = data.get("vehicle_no") or ""
    instance.driver_name = data.get("driver_name") or ""
    instance.transport_cost = Decimal(str(data.get("transport_cost") or 0))
    instance.paid_by_id = data.get("paid_by") or None
    if not instance.pk:
        instance.created_by = user


def _save_medicine_transfer_items(transfer, items_data):
    """Replaces every line of ``transfer`` with ``items_data``, computing
    each line's running stock as it goes (seeded from the last saved line
    for that item at this source location, then chained locally so two
    lines of the same item within one submission stack correctly). Returns
    the set of item ids the transfer now touches."""
    transfer.items.all().delete()
    location_type = transfer.from_location_type
    location_id = transfer.from_warehouse_id or transfer.from_farm_id
    running_by_item = {}
    touched_item_ids = set()
    for row in items_data:
        if not row.get("item"):
            continue
        item_id = int(row["item"])
        quantity = Decimal(str(row.get("quantity") or 0))
        rate = Decimal(str(row.get("rate") or 0))
        remarks = row.get("remarks") or ""
        if item_id not in running_by_item:
            running_by_item[item_id] = Decimal(str(
                MedicineTransferItem.previous_stock(location_type, location_id, item_id, transfer.date, None)))
        running_by_item[item_id] -= quantity
        MedicineTransferItem.objects.create(
            transfer=transfer, item_id=item_id, quantity=quantity, rate=rate, remarks=remarks,
            stock=running_by_item[item_id])
        touched_item_ids.add(item_id)
    return touched_item_ids


def _recompute_medicine_stock_chain(location_type, location_id, item_id):
    """Recomputes running stock for every line moved out of this source
    location (Warehouse or Farm) that touches item_id, walking
    chronologically from an opening balance of 0."""
    if not location_type or not location_id or not item_id:
        return
    filters = {"transfer__from_location_type": location_type, "item_id": item_id}
    filters["transfer__from_farm_id" if location_type == "farm" else "transfer__from_warehouse_id"] = location_id
    qs = MedicineTransferItem.objects.filter(**filters).order_by('transfer__date', 'id')
    running = Decimal('0')
    for r in qs:
        running -= r.quantity
        if r.stock != running:
            r.stock = running
            r.save(update_fields=["stock"])


@method_decorator(login_required, name="dispatch")
class MedicineTransferListTemplateView(View):
    def get(self, request):
        return render(request, "medicine_transfer_list.html", {
            "categories": ItemCategory.objects.order_by("name"),
            "items": Item.objects.order_by("item_code"),
            "warehouses": Warehouse.objects.order_by("name"),
            "farms": BroilerFarm.objects.order_by("farm_name"),
            "accounts": ChartOfAccount.objects.order_by("code"),
        })


@method_decorator(login_required, name="dispatch")
class MedicineTransferFormTemplateView(View):
    def get(self, request):
        return render(request, "medicine_transfer_form.html", {
            "items": Item.objects.order_by("item_code"),
            "warehouses": Warehouse.objects.order_by("name"),
            "farms": BroilerFarm.objects.order_by("farm_name"),
            "accounts": ChartOfAccount.objects.order_by("code"),
            "today": timezone.localdate().isoformat(),
        })


@method_decorator(login_required, name="dispatch")
class MedicineTransferAPI(View):

    def get(self, request, id=None):
        if id:
            try:
                header = MedicineTransfer.objects.select_related(
                    "from_warehouse", "from_farm", "from_batch", "to_warehouse", "to_farm", "to_batch", "paid_by"
                ).prefetch_related("items__item").get(id=id)
                return JsonResponse(_medicine_transfer_detail_dict(header))
            except MedicineTransfer.DoesNotExist:
                raise Http404("Medicine transfer not found")

        qs = MedicineTransfer.objects.select_related(
            "from_warehouse", "from_farm", "from_batch", "to_warehouse", "to_farm", "to_batch"
        ).prefetch_related("items__item")
        from_date = (request.GET.get("from_date") or "").strip()
        to_date = (request.GET.get("to_date") or "").strip()
        category = (request.GET.get("category") or "").strip()
        item_id = (request.GET.get("item") or "").strip()
        from_location_type = (request.GET.get("from_location_type") or "").strip()
        from_location_id = (request.GET.get("from_location_id") or "").strip()
        to_location_type = (request.GET.get("to_location_type") or "").strip()
        to_location_id = (request.GET.get("to_location_id") or "").strip()
        if from_date:
            qs = qs.filter(date__gte=from_date)
        if to_date:
            qs = qs.filter(date__lte=to_date)
        if category:
            qs = qs.filter(items__item__category_id=category)
        if item_id:
            qs = qs.filter(items__item_id=item_id)
        if from_location_type and from_location_id:
            qs = qs.filter(from_location_type=from_location_type, **{
                ("from_farm_id" if from_location_type == "farm" else "from_warehouse_id"): from_location_id,
            })
        if to_location_type and to_location_id:
            qs = qs.filter(to_location_type=to_location_type, **{
                ("to_farm_id" if to_location_type == "farm" else "to_warehouse_id"): to_location_id,
            })
        rows = qs.order_by("-date", "-id").distinct()
        return JsonResponse([_medicine_transfer_list_dict(r) for r in rows], safe=False)

    @transaction.atomic
    def post(self, request):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        items_data = data.get("items") or []
        if not items_data:
            return JsonResponse({"error": "Add at least one item line"}, status=400)

        instance = MedicineTransfer()
        try:
            _apply_medicine_transfer_header(instance, data, request.user)
            instance.full_clean(exclude=["trnum"])
            instance.save()
            touched = _save_medicine_transfer_items(instance, items_data)
        except ValidationError as e:
            return JsonResponse({"error": " ".join(e.messages) if hasattr(e, "messages") else str(e)}, status=400)

        if not touched:
            # instance.save() already committed the header — undo it so a
            # request with no valid item lines doesn't leave an orphan.
            instance.delete()
            return JsonResponse({"error": "Add at least one item line with an Item selected"}, status=400)

        location_type = instance.from_location_type
        location_id = instance.from_warehouse_id or instance.from_farm_id
        for item_id in touched:
            _recompute_medicine_stock_chain(location_type, location_id, item_id)
        return JsonResponse({"message": "Medicine transfer created", "id": instance.id}, status=201)

    @transaction.atomic
    def put(self, request, id):
        try:
            instance = MedicineTransfer.objects.get(id=id)
        except MedicineTransfer.DoesNotExist:
            raise Http404("Medicine transfer not found")

        old_key = (instance.from_location_type, instance.from_warehouse_id or instance.from_farm_id)
        old_item_ids = set(instance.items.values_list('item_id', flat=True))
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        items_data = data.get("items") or []
        try:
            _apply_medicine_transfer_header(instance, data, request.user)
            instance.full_clean(exclude=["trnum"])
            instance.save()
            touched = _save_medicine_transfer_items(instance, items_data)
        except ValidationError as e:
            return JsonResponse({"error": " ".join(e.messages) if hasattr(e, "messages") else str(e)}, status=400)

        new_key = (instance.from_location_type, instance.from_warehouse_id or instance.from_farm_id)
        for item_id in old_item_ids | touched:
            _recompute_medicine_stock_chain(old_key[0], old_key[1], item_id)
            _recompute_medicine_stock_chain(new_key[0], new_key[1], item_id)
        return JsonResponse({"message": "Medicine transfer updated"})

    def delete(self, request, id):
        try:
            instance = MedicineTransfer.objects.get(id=id)
        except MedicineTransfer.DoesNotExist:
            raise Http404("Medicine transfer not found")

        location_type = instance.from_location_type
        location_id = instance.from_warehouse_id or instance.from_farm_id
        item_ids = list(instance.items.values_list('item_id', flat=True))
        instance.delete()
        for item_id in item_ids:
            _recompute_medicine_stock_chain(location_type, location_id, item_id)
        return JsonResponse({"message": "Medicine transfer deleted"})


@login_required
def medicine_transfer_bulk_update(request):
    """Applies a shared set of header field changes to several selected
    transfers at once (list page's "Edit-Multiple"). Only keys present in
    ``fields`` are touched; the rest of each transfer is left as-is."""
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    ids = data.get("ids") or []
    fields = data.get("fields") or {}
    if not ids:
        return JsonResponse({"error": "Select at least one transfer"}, status=400)
    if not fields:
        return JsonResponse({"error": "Select at least one field to change"}, status=400)

    allowed = {"dc_no", "from_location_type", "from_location_id", "to_location_type", "to_location_id",
               "vehicle_no", "driver_name", "transport_cost", "paid_by"}
    unknown = set(fields) - allowed
    if unknown:
        return JsonResponse({"error": f"Unsupported field(s): {', '.join(unknown)}"}, status=400)

    updated = 0
    errors = []
    with transaction.atomic():
        for instance in MedicineTransfer.objects.filter(id__in=ids):
            old_key = (instance.from_location_type, instance.from_warehouse_id or instance.from_farm_id)
            item_ids = list(instance.items.values_list('item_id', flat=True))

            if "dc_no" in fields:
                instance.dc_no = fields["dc_no"] or ""
            if "from_location_type" in fields and "from_location_id" in fields:
                from_type = fields["from_location_type"]
                from_id = fields["from_location_id"]
                instance.from_location_type = from_type
                instance.from_warehouse_id = from_id if from_type == "warehouse" else None
                instance.from_farm_id = from_id if from_type == "farm" else None
            if "to_location_type" in fields and "to_location_id" in fields:
                to_type = fields["to_location_type"]
                to_id = fields["to_location_id"]
                instance.to_location_type = to_type
                instance.to_warehouse_id = to_id if to_type == "warehouse" else None
                instance.to_farm_id = to_id if to_type == "farm" else None
            if "vehicle_no" in fields:
                instance.vehicle_no = fields["vehicle_no"] or ""
            if "driver_name" in fields:
                instance.driver_name = fields["driver_name"] or ""
            if "transport_cost" in fields:
                instance.transport_cost = Decimal(str(fields["transport_cost"] or 0))
            if "paid_by" in fields:
                instance.paid_by_id = fields["paid_by"] or None

            try:
                instance.full_clean(exclude=["trnum"])
                instance.save()
            except ValidationError as e:
                errors.append(f"{instance.trnum}: " + (" ".join(e.messages) if hasattr(e, "messages") else str(e)))
                continue

            new_key = (instance.from_location_type, instance.from_warehouse_id or instance.from_farm_id)
            if new_key != old_key:
                for item_id in item_ids:
                    _recompute_medicine_stock_chain(old_key[0], old_key[1], item_id)
                    _recompute_medicine_stock_chain(new_key[0], new_key[1], item_id)
            updated += 1

    if errors and not updated:
        return JsonResponse({"error": "; ".join(errors)}, status=400)
    response = {"message": f"Updated {updated} transfer(s)"}
    if errors:
        response["warnings"] = errors
    return JsonResponse(response)


@login_required
def medicine_transfer_item_lookup(request):
    """UOM and default rate for a selected item, for the Add form's
    auto-filled Unit / Rate fields."""
    item_id = request.GET.get("item")
    item = Item.objects.filter(id=item_id).first() if item_id else None
    return JsonResponse({
        "unit": item.storage_uom if item else "",
        "rate": str(item.standard_cost_per_unit) if item else "0",
    })


@login_required
def medicine_transfer_stock_lookup(request):
    """Opening stock of an item at a source location (Warehouse or Farm) as
    of a given date — the closing balance of the most recent saved line
    before that date (0 if none)."""
    location_type = request.GET.get("location_type")
    location_id = request.GET.get("location_id")
    item_id = request.GET.get("item")
    entry_date = request.GET.get("date")
    if not location_type or not location_id or not item_id or not entry_date:
        return JsonResponse({"stock": "0"})
    d = timezone.datetime.fromisoformat(entry_date).date()
    stock = MedicineTransferItem.previous_stock(location_type, int(location_id), int(item_id), d, None)
    return JsonResponse({"stock": str(stock)})


@login_required
def medicine_transfer_farm_batches(request):
    """Batches for a Farm, for the Add/Edit form's Batch box that appears
    beside From Location / To Location when that side is a Farm."""
    farm_id = request.GET.get("farm")
    if not farm_id:
        return JsonResponse([], safe=False)
    batches = BroilerBatch.objects.filter(broiler_farm_id=farm_id).order_by("-start_date", "-id")
    return JsonResponse([
        {"id": b.id, "batch_name": b.batch_name, "is_active": b.end_date is None}
        for b in batches
    ], safe=False)


# ---------------------------------------------------------------------------
# Inventory Adjustment (Inventory > Transactions)
# ---------------------------------------------------------------------------

def _inventory_adjustment_list_dict(header):
    loc = _location_dict(header.location_type, header.warehouse, header.farm)
    lines = list(header.items.all())
    types = sorted({l.adjustment_type for l in lines})
    rates = {l.rate for l in lines}
    return {
        "id": header.id, "date": header.date.isoformat(), "trnum": header.trnum, "bill_no": header.bill_no,
        "location_type": loc["type"], "location_id": loc["id"], "location_name": loc["name"],
        "batch": header.batch_id, "batch_name": header.batch.batch_name if header.batch_id else "",
        "chart_of_account": header.chart_of_account_id,
        "chart_of_account_label": (f"{header.chart_of_account.code} - {header.chart_of_account.description}"
                                   if header.chart_of_account_id else ""),
        "type": "/".join(types),
        "item": ", ".join(l.item.description for l in lines if l.item_id),
        "quantity": str(sum((l.quantity for l in lines), Decimal('0'))),
        "price": str(next(iter(rates))) if len(rates) == 1 else "",
        "amount": str(sum((l.amount for l in lines), Decimal('0'))),
    }


def _inventory_adjustment_detail_dict(header):
    detail = _inventory_adjustment_list_dict(header)
    detail.update({
        "items": [
            {
                "id": l.id, "item": l.item_id, "item_code": l.item.item_code if l.item_id else "",
                "item_name": l.item.description if l.item_id else "",
                "unit": l.item.storage_uom if l.item_id else "",
                "adjustment_type": l.adjustment_type, "quantity": str(l.quantity), "rate": str(l.rate),
                "amount": str(l.amount), "remarks": l.remarks, "stock": str(l.stock),
            }
            for l in header.items.all()
        ],
    })
    return detail


def _apply_inventory_adjustment_header(instance, data, user):
    if data.get("date"):
        instance.date = timezone.datetime.fromisoformat(data["date"]).date()
    instance.bill_no = data.get("bill_no") or ""

    location_type = data.get("location_type") or "warehouse"
    location_id = data.get("location_id") or None
    instance.location_type = location_type
    instance.warehouse_id = location_id if location_type == "warehouse" else None
    instance.farm_id = location_id if location_type == "farm" else None
    instance.batch_id = data.get("batch") if location_type == "farm" else None

    instance.chart_of_account_id = data.get("chart_of_account") or None
    if not instance.pk:
        instance.created_by = user


def _save_inventory_adjustment_items(adjustment, items_data):
    """Replaces every line of ``adjustment`` with ``items_data``, computing
    each line's running stock as it goes (seeded from the last saved line
    for that item at this location, then chained locally so two lines of
    the same item within one submission stack correctly). Returns the set
    of item ids the adjustment now touches."""
    adjustment.items.all().delete()
    location_type = adjustment.location_type
    location_id = adjustment.warehouse_id or adjustment.farm_id
    running_by_item = {}
    touched_item_ids = set()
    for row in items_data:
        if not row.get("item") or not row.get("adjustment_type"):
            continue
        item_id = int(row["item"])
        adjustment_type = row["adjustment_type"]
        quantity = Decimal(str(row.get("quantity") or 0))
        rate = Decimal(str(row.get("rate") or 0))
        remarks = row.get("remarks") or ""
        if item_id not in running_by_item:
            running_by_item[item_id] = Decimal(str(
                InventoryAdjustmentItem.previous_stock(location_type, location_id, item_id, adjustment.date, None)))
        running_by_item[item_id] += quantity if adjustment_type == 'Add' else -quantity
        InventoryAdjustmentItem.objects.create(
            adjustment=adjustment, item_id=item_id, adjustment_type=adjustment_type, quantity=quantity,
            rate=rate, remarks=remarks, stock=running_by_item[item_id])
        touched_item_ids.add(item_id)
    return touched_item_ids


def _recompute_inventory_adjustment_chain(location_type, location_id, item_id):
    """Recomputes running stock for every line at this location (Warehouse
    or Farm) that touches item_id, walking chronologically from an opening
    balance of 0."""
    if not location_type or not location_id or not item_id:
        return
    filters = {"adjustment__location_type": location_type, "item_id": item_id}
    filters["adjustment__farm_id" if location_type == "farm" else "adjustment__warehouse_id"] = location_id
    qs = InventoryAdjustmentItem.objects.filter(**filters).order_by('adjustment__date', 'id')
    running = Decimal('0')
    for r in qs:
        running += r.quantity if r.adjustment_type == 'Add' else -r.quantity
        if r.stock != running:
            r.stock = running
            r.save(update_fields=["stock"])


@method_decorator(login_required, name="dispatch")
class InventoryAdjustmentListTemplateView(View):
    def get(self, request):
        return render(request, "inventory_adjustment_list.html", {
            "categories": ItemCategory.objects.order_by("name"),
            "items": Item.objects.order_by("item_code"),
            "warehouses": Warehouse.objects.order_by("name"),
            "accounts": ChartOfAccount.objects.order_by("code"),
        })


@method_decorator(login_required, name="dispatch")
class InventoryAdjustmentFormTemplateView(View):
    def get(self, request):
        return render(request, "inventory_adjustment_form.html", {
            "items": Item.objects.order_by("item_code"),
            "warehouses": Warehouse.objects.order_by("name"),
            "farms": BroilerFarm.objects.order_by("farm_name"),
            "accounts": ChartOfAccount.objects.order_by("code"),
            "today": timezone.localdate().isoformat(),
        })


@method_decorator(login_required, name="dispatch")
class InventoryAdjustmentAPI(View):

    def get(self, request, id=None):
        if id:
            try:
                header = InventoryAdjustment.objects.select_related(
                    "warehouse", "farm", "batch", "chart_of_account").prefetch_related("items__item").get(id=id)
                return JsonResponse(_inventory_adjustment_detail_dict(header))
            except InventoryAdjustment.DoesNotExist:
                raise Http404("Inventory adjustment not found")

        qs = InventoryAdjustment.objects.select_related(
            "warehouse", "farm", "batch", "chart_of_account").prefetch_related("items__item")
        from_date = (request.GET.get("from_date") or "").strip()
        to_date = (request.GET.get("to_date") or "").strip()
        category = (request.GET.get("category") or "").strip()
        item_id = (request.GET.get("item") or "").strip()
        warehouse_id = (request.GET.get("warehouse") or "").strip()
        if from_date:
            qs = qs.filter(date__gte=from_date)
        if to_date:
            qs = qs.filter(date__lte=to_date)
        if category:
            qs = qs.filter(items__item__category_id=category)
        if item_id:
            qs = qs.filter(items__item_id=item_id)
        if warehouse_id:
            qs = qs.filter(location_type="warehouse", warehouse_id=warehouse_id)
        rows = qs.order_by("-date", "-id").distinct()
        return JsonResponse([_inventory_adjustment_list_dict(r) for r in rows], safe=False)

    @transaction.atomic
    def post(self, request):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        items_data = data.get("items") or []
        if not items_data:
            return JsonResponse({"error": "Add at least one item line"}, status=400)

        instance = InventoryAdjustment()
        try:
            _apply_inventory_adjustment_header(instance, data, request.user)
            instance.full_clean(exclude=["trnum"])
            instance.save()
            touched = _save_inventory_adjustment_items(instance, items_data)
        except ValidationError as e:
            return JsonResponse({"error": " ".join(e.messages) if hasattr(e, "messages") else str(e)}, status=400)

        if not touched:
            # instance.save() already committed the header — undo it so a
            # request with no valid item lines doesn't leave an orphan.
            instance.delete()
            return JsonResponse(
                {"error": "Add at least one item line with an Item and Add/Deduct selected"}, status=400)

        location_id = instance.warehouse_id or instance.farm_id
        for item_id in touched:
            _recompute_inventory_adjustment_chain(instance.location_type, location_id, item_id)
        return JsonResponse({"message": "Inventory adjustment created", "id": instance.id}, status=201)

    @transaction.atomic
    def put(self, request, id):
        try:
            instance = InventoryAdjustment.objects.get(id=id)
        except InventoryAdjustment.DoesNotExist:
            raise Http404("Inventory adjustment not found")

        old_key = (instance.location_type, instance.warehouse_id or instance.farm_id)
        old_item_ids = set(instance.items.values_list('item_id', flat=True))
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        items_data = data.get("items") or []
        try:
            _apply_inventory_adjustment_header(instance, data, request.user)
            instance.full_clean(exclude=["trnum"])
            instance.save()
            touched = _save_inventory_adjustment_items(instance, items_data)
        except ValidationError as e:
            return JsonResponse({"error": " ".join(e.messages) if hasattr(e, "messages") else str(e)}, status=400)

        new_key = (instance.location_type, instance.warehouse_id or instance.farm_id)
        for item_id in old_item_ids | touched:
            _recompute_inventory_adjustment_chain(old_key[0], old_key[1], item_id)
            _recompute_inventory_adjustment_chain(new_key[0], new_key[1], item_id)
        return JsonResponse({"message": "Inventory adjustment updated"})

    def delete(self, request, id):
        try:
            instance = InventoryAdjustment.objects.get(id=id)
        except InventoryAdjustment.DoesNotExist:
            raise Http404("Inventory adjustment not found")

        location_type = instance.location_type
        location_id = instance.warehouse_id or instance.farm_id
        item_ids = list(instance.items.values_list('item_id', flat=True))
        instance.delete()
        for item_id in item_ids:
            _recompute_inventory_adjustment_chain(location_type, location_id, item_id)
        return JsonResponse({"message": "Inventory adjustment deleted"})


@login_required
def inventory_adjustment_item_lookup(request):
    """UOM and default rate for a selected item, for the Add form's
    auto-filled Unit / Rate fields."""
    item_id = request.GET.get("item")
    item = Item.objects.filter(id=item_id).first() if item_id else None
    return JsonResponse({
        "unit": item.storage_uom if item else "",
        "rate": str(item.standard_cost_per_unit) if item else "0",
    })


@login_required
def inventory_adjustment_stock_lookup(request):
    """Opening stock of an item at a location (Warehouse or Farm) as of a
    given date — the closing balance of the most recent saved line before
    that date (0 if none)."""
    location_type = request.GET.get("location_type")
    location_id = request.GET.get("location_id")
    item_id = request.GET.get("item")
    entry_date = request.GET.get("date")
    if not location_type or not location_id or not item_id or not entry_date:
        return JsonResponse({"stock": "0"})
    d = timezone.datetime.fromisoformat(entry_date).date()
    stock = InventoryAdjustmentItem.previous_stock(location_type, int(location_id), int(item_id), d, None)
    return JsonResponse({"stock": str(stock)})


@login_required
def inventory_adjustment_farm_batches(request):
    """Batches for a Farm, for the Add/Edit form's Batch box that appears
    beside Location when it's a Farm."""
    farm_id = request.GET.get("farm")
    if not farm_id:
        return JsonResponse([], safe=False)
    batches = BroilerBatch.objects.filter(broiler_farm_id=farm_id).order_by("-start_date", "-id")
    return JsonResponse([
        {"id": b.id, "batch_name": b.batch_name, "is_active": b.end_date is None}
        for b in batches
    ], safe=False)


# ---------------------------------------------------------------------------
# Stock Issued (Inventory > Transactions)
# ---------------------------------------------------------------------------

def _stock_issue_list_dict(header):
    lines = list(header.items.all())
    rates = {l.rate for l in lines}
    locations = []
    for l in lines:
        loc = _location_dict(l.location_type, l.warehouse, l.farm)
        if loc["name"] and loc["name"] not in locations:
            locations.append(loc["name"])
    return {
        "id": header.id, "date": header.date.isoformat(), "trnum": header.trnum,
        "chart_of_account": header.chart_of_account_id,
        "chart_of_account_label": (f"{header.chart_of_account.code} - {header.chart_of_account.description}"
                                   if header.chart_of_account_id else ""),
        "item": ", ".join(l.item.description for l in lines if l.item_id),
        "quantity": str(sum((l.quantity for l in lines), Decimal('0'))),
        "price": str(next(iter(rates))) if len(rates) == 1 else "",
        "amount": str(sum((l.amount for l in lines), Decimal('0'))),
        "farm_warehouse": ", ".join(locations),
    }


def _stock_issue_detail_dict(header):
    detail = _stock_issue_list_dict(header)
    detail.update({
        "items": [
            {
                "id": l.id, "item": l.item_id, "item_code": l.item.item_code if l.item_id else "",
                "item_name": l.item.description if l.item_id else "",
                "unit": l.item.storage_uom if l.item_id else "",
                "quantity": str(l.quantity), "rate": str(l.rate), "amount": str(l.amount),
                "location_type": l.location_type,
                "location_id": (l.farm_id if l.location_type == 'farm' else l.warehouse_id),
                "location_name": _location_dict(l.location_type, l.warehouse, l.farm)["name"],
                "batch": l.batch_id, "batch_name": l.batch.batch_name if l.batch_id else "",
                "remarks": l.remarks,
            }
            for l in header.items.all()
        ],
    })
    return detail


def _apply_stock_issue_header(instance, data, user):
    if data.get("date"):
        instance.date = timezone.datetime.fromisoformat(data["date"]).date()
    instance.chart_of_account_id = data.get("chart_of_account") or None
    if not instance.pk:
        instance.created_by = user


def _save_stock_issue_items(issue, items_data):
    """Replaces every line of ``issue`` with ``items_data``. Returns the
    number of valid lines created."""
    issue.items.all().delete()
    created = 0
    for row in items_data:
        location_type = row.get("location_type") or "warehouse"
        location_id = row.get("location_id") or None
        if not row.get("item") or not location_id:
            continue
        item_id = int(row["item"])
        quantity = Decimal(str(row.get("quantity") or 0))
        rate = Decimal(str(row.get("rate") or 0))
        remarks = row.get("remarks") or ""
        batch_id = row.get("batch") if location_type == "farm" else None
        StockIssueItem.objects.create(
            issue=issue, item_id=item_id, quantity=quantity, rate=rate, remarks=remarks,
            location_type=location_type,
            warehouse_id=location_id if location_type == "warehouse" else None,
            farm_id=location_id if location_type == "farm" else None,
            batch_id=batch_id,
        )
        created += 1
    return created


@method_decorator(login_required, name="dispatch")
class StockIssueListTemplateView(View):
    def get(self, request):
        return render(request, "stock_issued_list.html", {
            "categories": ItemCategory.objects.order_by("name"),
            "items": Item.objects.order_by("item_code"),
            "warehouses": Warehouse.objects.order_by("name"),
        })


@method_decorator(login_required, name="dispatch")
class StockIssueFormTemplateView(View):
    def get(self, request):
        return render(request, "stock_issued_form.html", {
            "items": Item.objects.order_by("item_code"),
            "warehouses": Warehouse.objects.order_by("name"),
            "farms": BroilerFarm.objects.order_by("farm_name"),
            "accounts": ChartOfAccount.objects.order_by("code"),
            "today": timezone.localdate().isoformat(),
        })


@method_decorator(login_required, name="dispatch")
class StockIssueAPI(View):

    def get(self, request, id=None):
        if id:
            try:
                header = StockIssue.objects.select_related("chart_of_account").prefetch_related(
                    "items__item", "items__warehouse", "items__farm", "items__batch").get(id=id)
                return JsonResponse(_stock_issue_detail_dict(header))
            except StockIssue.DoesNotExist:
                raise Http404("Stock issue not found")

        qs = StockIssue.objects.select_related("chart_of_account").prefetch_related(
            "items__item", "items__warehouse", "items__farm", "items__batch")
        from_date = (request.GET.get("from_date") or "").strip()
        to_date = (request.GET.get("to_date") or "").strip()
        category = (request.GET.get("category") or "").strip()
        item_id = (request.GET.get("item") or "").strip()
        warehouse_id = (request.GET.get("warehouse") or "").strip()
        if from_date:
            qs = qs.filter(date__gte=from_date)
        if to_date:
            qs = qs.filter(date__lte=to_date)
        if category:
            qs = qs.filter(items__item__category_id=category)
        if item_id:
            qs = qs.filter(items__item_id=item_id)
        if warehouse_id:
            qs = qs.filter(items__location_type="warehouse", items__warehouse_id=warehouse_id)
        rows = qs.order_by("-date", "-id").distinct()
        return JsonResponse([_stock_issue_list_dict(r) for r in rows], safe=False)

    @transaction.atomic
    def post(self, request):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        items_data = data.get("items") or []
        if not items_data:
            return JsonResponse({"error": "Add at least one item line"}, status=400)

        instance = StockIssue()
        try:
            _apply_stock_issue_header(instance, data, request.user)
            instance.full_clean(exclude=["trnum"])
            instance.save()
            created = _save_stock_issue_items(instance, items_data)
        except ValidationError as e:
            return JsonResponse({"error": " ".join(e.messages) if hasattr(e, "messages") else str(e)}, status=400)

        if not created:
            # instance.save() already committed the header — undo it so a
            # request with no valid item lines doesn't leave an orphan.
            instance.delete()
            return JsonResponse(
                {"error": "Add at least one item line with an Item and Location selected"}, status=400)
        return JsonResponse({"message": "Stock issue created", "id": instance.id}, status=201)

    @transaction.atomic
    def put(self, request, id):
        try:
            instance = StockIssue.objects.get(id=id)
        except StockIssue.DoesNotExist:
            raise Http404("Stock issue not found")

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        items_data = data.get("items") or []
        try:
            _apply_stock_issue_header(instance, data, request.user)
            instance.full_clean(exclude=["trnum"])
            instance.save()
            created = _save_stock_issue_items(instance, items_data)
        except ValidationError as e:
            return JsonResponse({"error": " ".join(e.messages) if hasattr(e, "messages") else str(e)}, status=400)

        if not created:
            return JsonResponse(
                {"error": "Add at least one item line with an Item and Location selected"}, status=400)
        return JsonResponse({"message": "Stock issue updated"})

    def delete(self, request, id):
        try:
            instance = StockIssue.objects.get(id=id)
        except StockIssue.DoesNotExist:
            raise Http404("Stock issue not found")
        instance.delete()
        return JsonResponse({"message": "Stock issue deleted"})


@login_required
def stock_issue_item_lookup(request):
    """UOM and default rate for a selected item, for the Add form's
    auto-filled Unit / Rate fields."""
    item_id = request.GET.get("item")
    item = Item.objects.filter(id=item_id).first() if item_id else None
    return JsonResponse({
        "unit": item.storage_uom if item else "",
        "rate": str(item.standard_cost_per_unit) if item else "0",
    })


@login_required
def stock_issue_farm_batches(request):
    """Batches for a Farm, for the Add/Edit form's Batch box that appears
    when a line's Location is a Farm."""
    farm_id = request.GET.get("farm")
    if not farm_id:
        return JsonResponse([], safe=False)
    batches = BroilerBatch.objects.filter(broiler_farm_id=farm_id).order_by("-start_date", "-id")
    return JsonResponse([
        {"id": b.id, "batch_name": b.batch_name, "is_active": b.end_date is None}
        for b in batches
    ], safe=False)


# ---------------------------------------------------------------------------
# Stock Received (Inventory > Transactions)
# ---------------------------------------------------------------------------

def _stock_receive_list_dict(header):
    lines = list(header.items.all())
    rates = {l.rate for l in lines}
    locations = []
    for l in lines:
        loc = _location_dict(l.location_type, l.warehouse, l.farm)
        if loc["name"] and loc["name"] not in locations:
            locations.append(loc["name"])
    return {
        "id": header.id, "date": header.date.isoformat(), "trnum": header.trnum,
        "chart_of_account": header.chart_of_account_id,
        "chart_of_account_label": (f"{header.chart_of_account.code} - {header.chart_of_account.description}"
                                   if header.chart_of_account_id else ""),
        "item": ", ".join(l.item.description for l in lines if l.item_id),
        "quantity": str(sum((l.quantity for l in lines), Decimal('0'))),
        "price": str(next(iter(rates))) if len(rates) == 1 else "",
        "amount": str(sum((l.amount for l in lines), Decimal('0'))),
        "farm_warehouse": ", ".join(locations),
    }


def _stock_receive_detail_dict(header):
    detail = _stock_receive_list_dict(header)
    detail.update({
        "items": [
            {
                "id": l.id, "item": l.item_id, "item_code": l.item.item_code if l.item_id else "",
                "item_name": l.item.description if l.item_id else "",
                "unit": l.item.storage_uom if l.item_id else "",
                "quantity": str(l.quantity), "rate": str(l.rate), "amount": str(l.amount),
                "location_type": l.location_type,
                "location_id": (l.farm_id if l.location_type == 'farm' else l.warehouse_id),
                "location_name": _location_dict(l.location_type, l.warehouse, l.farm)["name"],
                "batch": l.batch_id, "batch_name": l.batch.batch_name if l.batch_id else "",
                "remarks": l.remarks,
            }
            for l in header.items.all()
        ],
    })
    return detail


def _apply_stock_receive_header(instance, data, user):
    if data.get("date"):
        instance.date = timezone.datetime.fromisoformat(data["date"]).date()
    instance.chart_of_account_id = data.get("chart_of_account") or None
    if not instance.pk:
        instance.created_by = user


def _save_stock_receive_items(receive, items_data):
    """Replaces every line of ``receive`` with ``items_data``. Returns the
    number of valid lines created."""
    receive.items.all().delete()
    created = 0
    for row in items_data:
        location_type = row.get("location_type") or "warehouse"
        location_id = row.get("location_id") or None
        if not row.get("item") or not location_id:
            continue
        item_id = int(row["item"])
        quantity = Decimal(str(row.get("quantity") or 0))
        rate = Decimal(str(row.get("rate") or 0))
        remarks = row.get("remarks") or ""
        batch_id = row.get("batch") if location_type == "farm" else None
        StockReceiveItem.objects.create(
            receive=receive, item_id=item_id, quantity=quantity, rate=rate, remarks=remarks,
            location_type=location_type,
            warehouse_id=location_id if location_type == "warehouse" else None,
            farm_id=location_id if location_type == "farm" else None,
            batch_id=batch_id,
        )
        created += 1
    return created


@method_decorator(login_required, name="dispatch")
class StockReceiveListTemplateView(View):
    def get(self, request):
        return render(request, "stock_received_list.html", {
            "categories": ItemCategory.objects.order_by("name"),
            "items": Item.objects.order_by("item_code"),
            "warehouses": Warehouse.objects.order_by("name"),
        })


@method_decorator(login_required, name="dispatch")
class StockReceiveFormTemplateView(View):
    def get(self, request):
        return render(request, "stock_received_form.html", {
            "items": Item.objects.order_by("item_code"),
            "warehouses": Warehouse.objects.order_by("name"),
            "farms": BroilerFarm.objects.order_by("farm_name"),
            "accounts": ChartOfAccount.objects.order_by("code"),
            "today": timezone.localdate().isoformat(),
        })


@method_decorator(login_required, name="dispatch")
class StockReceiveAPI(View):

    def get(self, request, id=None):
        if id:
            try:
                header = StockReceive.objects.select_related("chart_of_account").prefetch_related(
                    "items__item", "items__warehouse", "items__farm", "items__batch").get(id=id)
                return JsonResponse(_stock_receive_detail_dict(header))
            except StockReceive.DoesNotExist:
                raise Http404("Stock receive not found")

        qs = StockReceive.objects.select_related("chart_of_account").prefetch_related(
            "items__item", "items__warehouse", "items__farm", "items__batch")
        from_date = (request.GET.get("from_date") or "").strip()
        to_date = (request.GET.get("to_date") or "").strip()
        category = (request.GET.get("category") or "").strip()
        item_id = (request.GET.get("item") or "").strip()
        warehouse_id = (request.GET.get("warehouse") or "").strip()
        if from_date:
            qs = qs.filter(date__gte=from_date)
        if to_date:
            qs = qs.filter(date__lte=to_date)
        if category:
            qs = qs.filter(items__item__category_id=category)
        if item_id:
            qs = qs.filter(items__item_id=item_id)
        if warehouse_id:
            qs = qs.filter(items__location_type="warehouse", items__warehouse_id=warehouse_id)
        rows = qs.order_by("-date", "-id").distinct()
        return JsonResponse([_stock_receive_list_dict(r) for r in rows], safe=False)

    @transaction.atomic
    def post(self, request):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        items_data = data.get("items") or []
        if not items_data:
            return JsonResponse({"error": "Add at least one item line"}, status=400)

        instance = StockReceive()
        try:
            _apply_stock_receive_header(instance, data, request.user)
            instance.full_clean(exclude=["trnum"])
            instance.save()
            created = _save_stock_receive_items(instance, items_data)
        except ValidationError as e:
            return JsonResponse({"error": " ".join(e.messages) if hasattr(e, "messages") else str(e)}, status=400)

        if not created:
            # instance.save() already committed the header — undo it so a
            # request with no valid item lines doesn't leave an orphan.
            instance.delete()
            return JsonResponse(
                {"error": "Add at least one item line with an Item and Location selected"}, status=400)
        return JsonResponse({"message": "Stock receive created", "id": instance.id}, status=201)

    @transaction.atomic
    def put(self, request, id):
        try:
            instance = StockReceive.objects.get(id=id)
        except StockReceive.DoesNotExist:
            raise Http404("Stock receive not found")

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        items_data = data.get("items") or []
        try:
            _apply_stock_receive_header(instance, data, request.user)
            instance.full_clean(exclude=["trnum"])
            instance.save()
            created = _save_stock_receive_items(instance, items_data)
        except ValidationError as e:
            return JsonResponse({"error": " ".join(e.messages) if hasattr(e, "messages") else str(e)}, status=400)

        if not created:
            return JsonResponse(
                {"error": "Add at least one item line with an Item and Location selected"}, status=400)
        return JsonResponse({"message": "Stock receive updated"})

    def delete(self, request, id):
        try:
            instance = StockReceive.objects.get(id=id)
        except StockReceive.DoesNotExist:
            raise Http404("Stock receive not found")
        instance.delete()
        return JsonResponse({"message": "Stock receive deleted"})


@login_required
def stock_receive_item_lookup(request):
    """UOM and default rate for a selected item, for the Add form's
    auto-filled Unit / Rate fields."""
    item_id = request.GET.get("item")
    item = Item.objects.filter(id=item_id).first() if item_id else None
    return JsonResponse({
        "unit": item.storage_uom if item else "",
        "rate": str(item.standard_cost_per_unit) if item else "0",
    })


@login_required
def stock_receive_farm_batches(request):
    """Batches for a Farm, for the Add/Edit form's Batch box that appears
    when a line's Location is a Farm."""
    farm_id = request.GET.get("farm")
    if not farm_id:
        return JsonResponse([], safe=False)
    batches = BroilerBatch.objects.filter(broiler_farm_id=farm_id).order_by("-start_date", "-id")
    return JsonResponse([
        {"id": b.id, "batch_name": b.batch_name, "is_active": b.end_date is None}
        for b in batches
    ], safe=False)
