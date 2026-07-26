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

from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.serializers import serializer_factory
from api.viewsets import V1ViewMixin, register_model

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


def _active_batch_for_farm(farm_id):
    """The farm's current batch (open first, else latest) — mirrors the web
    ``broiler.views._active_batch_for_farm`` used by the Bird Sale form."""
    return (BroilerBatch.objects.filter(broiler_farm_id=farm_id, end_date__isnull=True)
            .order_by("-start_date", "-id").first()
            or BroilerBatch.objects.filter(broiler_farm_id=farm_id)
            .order_by("-start_date", "-id").first())


class BirdSaleSerializer(serializer_factory(BirdSale)):
    """Bird Sale write logic identical to the web form: the batch and the buyer
    are derived from the chosen farm, never trusted from the client.

    * batch  → the farm's active batch
    * farmer → the farm's owner (a Farmer Sale is that farmer buying back)
    * customer required for a Customer Sale; farmer must exist for a Farmer Sale

    ``avg_weight``/``amount``/``sale_no`` stay server-computed in ``Model.save``.
    """

    def validate(self, attrs):
        attrs = super().validate(attrs)
        farm = attrs.get("farm") or getattr(self.instance, "farm", None)
        sale_type = attrs.get("sale_type") or getattr(self.instance, "sale_type", "customer")

        if farm is not None:
            attrs["batch"] = _active_batch_for_farm(farm.id)
            if sale_type == "farmer":
                attrs["farmer"] = farm.farmer
                attrs["customer"] = None
            else:
                attrs["farmer"] = None

        if sale_type == "customer" and not attrs.get("customer"):
            raise serializers.ValidationError({"customer": "Customer is required for a Customer Sale."})
        if sale_type == "farmer" and not attrs.get("farmer"):
            raise serializers.ValidationError(
                {"farmer": "The selected farm has no farmer on record — pick a different farm."}
            )
        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        if request is not None and not validated_data.get("entry_by"):
            validated_data["entry_by"] = request.user
        return super().create(validated_data)


class BirdSaleFarmLookupView(V1ViewMixin, APIView):
    """GET /api/v1/broiler/farm-lookup?farm=<id> — the farm's active batch,
    owning farmer, batch age, and next entry date. Serves the auto-filled
    fields on the Bird Sale, Daily Entry, and Medicine Entry forms (mirrors the
    web ``bird_sale_farm_lookup`` + ``daily_entry_farm_lookup``)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from datetime import timedelta

        from django.utils import timezone

        farm_id = request.query_params.get("farm")
        batch = _active_batch_for_farm(farm_id) if farm_id else None
        farm = (BroilerFarm.objects.filter(id=farm_id).select_related("farmer").first()
                if farm_id else None)

        age_days = 0
        if batch and batch.start_date:
            age_days = max((timezone.localdate() - batch.start_date).days, 0)

        last_entry = (DailyEntry.objects.filter(farm_id=farm_id).order_by("-date", "-id").first()
                      if farm_id else None)
        next_date = (last_entry.date + timedelta(days=1)) if last_entry else timezone.localdate()

        return Response({
            "batch": batch.id if batch else None,
            "batch_name": batch.batch_name if batch else "",
            "farmer": farm.farmer_id if farm else None,
            "farmer_name": farm.farmer.farmer_name if farm and farm.farmer_id else "",
            "age_days": age_days,
            "start_date": batch.start_date.isoformat() if batch and batch.start_date else None,
            "next_date": next_date.isoformat(),
        })


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
    register_model(router, "broiler/bird-sales", BirdSale, serializer=BirdSaleSerializer,
                   search_fields=["sale_no", "doc_no", "vehicle", "driver"], cursor=True)
    register_model(router, "broiler/bird-sale-receipts", BirdSaleReceipt, cursor=True)

    # --- Growing-charge settlement / batch closing (read-only) ----------
    register_model(router, "broiler/gc-settlements", GrowingChargeSettlement, read_only=True,
                   search_fields=["settlement_code"], ordering=["-id"])
