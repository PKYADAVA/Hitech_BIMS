"""Broiler domain — mobile API v1 resources.

Every resource is one ``register_model`` call: master/reference tables are
read-only (mobile consumes them as dropdown/picker data), while the field-data
transactions get full CRUD with cursor pagination for infinite scroll. All the
plumbing (envelope, auth, pagination, N+1-safe querysets, ``updated_since``
delta sync) comes from ``api.viewsets`` — nothing is re-implemented here.

Registered under ``/api/v1/broiler/…`` by :func:`register` (called from
``api/urls.py``).
"""
from __future__ import annotations

from api.viewsets import register_model

from .models import (
    Branch,
    BirdSale,
    BirdSaleReceipt,
    Breed,
    BreedStandard,
    BroilerBatch,
    BroilerDisease,
    BroilerFarm,
    BroilerFarmShed,
    BroilerLine,
    DailyEntry,
    Farmer,
    FarmerGroup,
    GrowingChargeScheme,
    GrowingChargeSettlement,
    MedicineVaccineEntry,
    Region,
    Supervisor,
)


def register(router) -> None:
    # --- Master data (full CRUD; list also serves as picker data) -------
    register_model(router, "broiler/farmer-groups", FarmerGroup,
                   search_fields=["code", "description"], ordering=["code"])
    register_model(router, "broiler/regions", Region,
                   search_fields=["code", "description"], ordering=["code"])
    register_model(router, "broiler/breeds", Breed,
                   search_fields=["code", "description"], ordering=["code"])
    register_model(router, "broiler/breed-standards", BreedStandard,
                   search_fields=["code"], ordering=["breed", "age"])
    register_model(router, "broiler/growing-charges", GrowingChargeScheme,
                   search_fields=["scheme_code", "schema_name"], ordering=["-id"])
    register_model(router, "broiler/branches", Branch,
                   search_fields=["code", "branch_name"], ordering=["branch_name"])
    register_model(router, "broiler/supervisors", Supervisor,
                   search_fields=["name"], ordering=["name"])
    register_model(router, "broiler/lines", BroilerLine,
                   search_fields=["code", "description"], ordering=["code"])
    register_model(router, "broiler/farmers", Farmer,
                   search_fields=["farmer_name"], ordering=["farmer_name"])
    register_model(router, "broiler/farms", BroilerFarm,
                   search_fields=["farm_name", "farm_code"], ordering=["-id"])
    register_model(router, "broiler/sheds", BroilerFarmShed,
                   search_fields=["shed_code", "shed_name"])
    register_model(router, "broiler/batches", BroilerBatch,
                   search_fields=["batch_name", "lot_no"], ordering=["-id"])
    register_model(router, "broiler/diseases", BroilerDisease,
                   search_fields=["disease_code", "disease_name"], ordering=["disease_name"])

    # --- Transactions (full CRUD, cursor-paginated feeds) ---------------
    register_model(router, "broiler/daily-entries", DailyEntry, cursor=True)
    register_model(router, "broiler/medicine-vaccine-entries", MedicineVaccineEntry, cursor=True)
    register_model(router, "broiler/bird-sales", BirdSale, cursor=True)
    register_model(router, "broiler/bird-sale-receipts", BirdSaleReceipt, cursor=True)

    # --- Growing-charge settlement / batch closing (read-only) ----------
    register_model(router, "broiler/gc-settlements", GrowingChargeSettlement, read_only=True,
                   search_fields=["settlement_code"], ordering=["-id"])
