"""Hatchery domain — mobile API v1 resources.

Same one-line pattern as ``broiler/api.py``. Parent transactions are full-CRUD
cursor feeds; their line-item tables are registered as their own resources and
filtered from the client with the base layer's generic ``?<fk>=<id>`` filter
(e.g. ``/api/v1/hatchery/egg-purchase-items?egg_purchase=42``), so no bespoke
nested serializers are needed for a first release.

Registered under ``/api/v1/hatchery/…`` by :func:`register`.
"""
from __future__ import annotations

from api.viewsets import register_model
from hatchery_master.models import ExpenseType, Hatcher, Hatchery, HatcheryExpense, Setter

from .models import (
    ChickSale,
    ChickSaleItem,
    DeliveryChallan,
    DeliveryChallanItem,
    EggGrading,
    EggPurchase,
    EggPurchaseItem,
    HatchEntry,
    HatchSetting,
    TraySetting,
)


def register(router) -> None:
    # --- Settings / operational records (full CRUD) ---------------------
    register_model(router, "hatchery/hatch-settings", HatchSetting,
                   search_fields=["setting_no", "batch_flock_no", "supplier_name"])
    register_model(router, "hatchery/tray-settings", TraySetting,
                   search_fields=["setting_no", "loaded_by"])

    # --- Hatchery master data (full CRUD; list also serves as pickers) --
    register_model(router, "hatchery/hatcheries", Hatchery,
                   search_fields=["hatchery_name", "owner_name"], ordering=["hatchery_name"])
    register_model(router, "hatchery/setters", Setter,
                   search_fields=["setter_no"], ordering=["setter_no"])
    register_model(router, "hatchery/hatchers", Hatcher,
                   search_fields=["hatcher_no"], ordering=["hatcher_no"])
    register_model(router, "hatchery/expense-types", ExpenseType,
                   search_fields=["name"], ordering=["name"])

    # --- Transactions (full CRUD, cursor feeds) -------------------------
    register_model(router, "hatchery/egg-purchases", EggPurchase, cursor=True)
    register_model(router, "hatchery/egg-gradings", EggGrading, cursor=True)
    register_model(router, "hatchery/delivery-challans", DeliveryChallan, cursor=True)
    register_model(router, "hatchery/hatch-entries", HatchEntry, cursor=True)
    register_model(router, "hatchery/chick-sales", ChickSale, cursor=True)
    register_model(router, "hatchery/expenses", HatcheryExpense, cursor=True)

    # --- Line items (CRUD; filter by parent via ?<fk>=<id>) -------------
    register_model(router, "hatchery/egg-purchase-items", EggPurchaseItem)
    register_model(router, "hatchery/delivery-challan-items", DeliveryChallanItem)
    register_model(router, "hatchery/chick-sale-items", ChickSaleItem)
