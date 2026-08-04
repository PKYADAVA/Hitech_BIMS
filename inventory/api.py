"""Inventory domain — mobile API v1 resources.

Mirrors the web Inventory module. Simple master data (categories, units,
sectors, offices, price list) gets full CRUD via the generic form; the Item
master and every stock transaction are exposed **read-only** because they carry
choice/M2M fields or line-item children + stock side-effects that the generic
mobile form can't author safely. All plumbing (envelope, auth, pagination,
N+1-safe querysets, ``updated_since`` delta sync) comes from ``api.viewsets``.

Registered under ``/api/v1/inventory/…`` by :func:`register` (called from
``api/urls.py``).
"""
from __future__ import annotations

from api.viewsets import register_model

from .models import (
    InventoryAdjustment,
    Item,
    ItemCategory,
    ItemPriceList,
    MedicineTransfer,
    Sector,
    StockIssue,
    StockReceive,
    StockTransfer,
    UnitOfMeasurement,
    Warehouse,
)


from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.viewsets import V1ViewMixin


class StockTransferItemLookupView(V1ViewMixin, APIView):
    """GET /api/v1/inventory/stock-transfer-item?item=<id>&date=<iso> — the
    item's UOM and its issue price on that date.

    The phone shows both on the transfer row the way the web form does. Both
    call the same view function, so a price rule can never apply on one client
    and not the other.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        import json

        from inventory.views import stock_transfer_item_lookup

        return Response(json.loads(stock_transfer_item_lookup(request).content))


class StockTransferStockLookupView(V1ViewMixin, APIView):
    """GET /api/v1/inventory/stock-transfer-stock?location_type=&location_id=
    &item=<id>&date=<iso> — what is actually at that location on that date.

    Reconciled across every transaction type, not just prior transfers, and it
    is the same figure StockTransfer.clean() enforces on save — so what the row
    shows and what the save allows cannot disagree.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        import json

        from inventory.views import stock_transfer_stock_lookup

        return Response(json.loads(stock_transfer_stock_lookup(request).content))


def register(router) -> None:
    # --- Master data (full CRUD; list also serves as picker data) -------
    register_model(router, "inventory/item-categories", ItemCategory,
                   search_fields=["code", "name"], ordering=["name"])
    register_model(router, "inventory/uom", UnitOfMeasurement,
                   search_fields=["name", "symbol"], ordering=["name"])
    register_model(router, "inventory/sectors", Sector,
                   search_fields=["code", "name"], ordering=["name"])
    register_model(router, "inventory/warehouses", Warehouse,
                   search_fields=["code", "name", "location"], ordering=["name"])
    register_model(router, "inventory/price-list", ItemPriceList,
                   search_fields=["item__item_code", "item__description"],
                   ordering=["-effective_date", "-id"])

    # --- Items (read-only: choice + M2M fields aren't form-writable) -----
    register_model(router, "inventory/items", Item, read_only=True,
                   search_fields=["item_code", "description", "hsn_code"],
                   ordering=["item_code"])

    # --- Transactions (read-only: line-item children + stock movement) --
    register_model(router, "inventory/stock-transfers", StockTransfer, read_only=True,
                   search_fields=["trnum", "dc_no", "vehicle_no", "driver_name"], cursor=True)
    register_model(router, "inventory/medicine-transfers", MedicineTransfer, read_only=True,
                   search_fields=["trnum", "dc_no", "vehicle_no", "driver_name"], cursor=True)
    register_model(router, "inventory/adjustments", InventoryAdjustment, read_only=True,
                   search_fields=["trnum", "bill_no"], cursor=True)
    register_model(router, "inventory/stock-issues", StockIssue, read_only=True,
                   search_fields=["trnum"], cursor=True)
    register_model(router, "inventory/stock-receives", StockReceive, read_only=True,
                   search_fields=["trnum"], cursor=True)
