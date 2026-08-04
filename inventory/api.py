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

from api.viewsets import register_model, serializer_factory

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


class StockTransferWriteSerializer(serializer_factory(StockTransfer)):
    """Create a Stock Transfer from the phone the way the web form does.

    Saving the row is not the whole job. Running stock is stored per row and
    walked chronologically from the source location, so a transfer inserted
    among existing ones leaves every later row's stock wrong until the chain is
    recomputed — the web POST does that, and a plain DRF create would not.

    The date rule is shared too: a transfer cannot be dated ahead of today, or
    everything read as-of a date is wrong from then on.
    """

    def validate_date(self, value):
        from Hitech_BIMS.entry_dates import reject_future_date

        return reject_future_date(value, "Transfer date")

    def create(self, validated_data):
        from inventory.views import _recompute_stock_transfer_chain

        instance = super().create(validated_data)
        _recompute_stock_transfer_chain(
            instance.from_location_type,
            instance.from_warehouse_id or instance.from_farm_id,
            instance.item_id)
        return instance

    def update(self, instance, validated_data):
        from inventory.views import _recompute_stock_transfer_chain

        # An edit can move the row between locations; both chains need walking.
        before = (instance.from_location_type,
                  instance.from_warehouse_id or instance.from_farm_id,
                  instance.item_id)
        instance = super().update(instance, validated_data)
        after = (instance.from_location_type,
                 instance.from_warehouse_id or instance.from_farm_id,
                 instance.item_id)
        for chain in {before, after}:
            _recompute_stock_transfer_chain(*chain)
        return instance


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
    # Stock Transfer is the exception among these: the phone creates them, so
    # it is writable through a serializer carrying the web form's side effects.
    register_model(router, "inventory/stock-transfers", StockTransfer,
                   serializer=StockTransferWriteSerializer,
                   search_fields=["trnum", "dc_no", "vehicle_no", "driver_name"], cursor=True)
    register_model(router, "inventory/medicine-transfers", MedicineTransfer, read_only=True,
                   search_fields=["trnum", "dc_no", "vehicle_no", "driver_name"], cursor=True)
    register_model(router, "inventory/adjustments", InventoryAdjustment, read_only=True,
                   search_fields=["trnum", "bill_no"], cursor=True)
    register_model(router, "inventory/stock-issues", StockIssue, read_only=True,
                   search_fields=["trnum"], cursor=True)
    register_model(router, "inventory/stock-receives", StockReceive, read_only=True,
                   search_fields=["trnum"], cursor=True)
