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

from decimal import Decimal

from django.utils import timezone
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


class DailyEntrySerializer(serializer_factory(DailyEntry)):
    """Daily Entry write logic identical to the web form's
    ``broiler.views._apply_daily_entry_row``: the batch, the birds' age and the
    running feed stock are all derived server-side, never trusted from (or
    expected from) the client.

    ``age_days``, ``feed_1_stock`` and ``feed_2_stock`` are ``editable=False``,
    so DRF never accepts them from the request and they would otherwise save as
    0. That matters well beyond the one row: ``DailyEntry.previous_stock``
    chains each entry's opening balance off the previous entry's closing
    balance, so a single zeroed row silently corrupts the feed-stock ledger for
    every later entry on that farm.

    After the write, the affected feed items' whole chain is recomputed — an
    edit to a row's date, quantity or feed item changes the opening balance of
    every row after it (same reason the web form calls it).
    """

    def validate(self, attrs):
        attrs = super().validate(attrs)
        farm = attrs.get("farm") or getattr(self.instance, "farm", None)
        if farm is not None:
            attrs["batch"] = _active_batch_for_farm(farm.id)
        return attrs

    def _current(self, validated_data, name, default=None):
        """Field value for this write: the incoming value when supplied,
        otherwise the instance's existing one (PATCH sends partial data)."""
        if name in validated_data:
            return validated_data[name]
        return getattr(self.instance, name, default) if self.instance else default

    def _apply_derived(self, validated_data):
        entry_date = self._current(validated_data, "date") or timezone.localdate()
        batch = self._current(validated_data, "batch")
        farm = self._current(validated_data, "farm")
        farm_id = farm.id if farm else None

        # Placement day is Age 0; the first entry day (the day after placement)
        # is Age 1 — same rule as the web form.
        if batch and batch.start_date:
            validated_data["age_days"] = max((entry_date - batch.start_date).days, 0)
        else:
            validated_data["age_days"] = 0

        # An existing row must exclude itself from its own "previous" lookup;
        # a new row has no pk to compare against yet.
        before_id = self.instance.pk if self.instance else None
        for slot in ("feed_1", "feed_2"):
            item = self._current(validated_data, slot)
            qty = self._current(validated_data, f"{slot}_qty") or Decimal("0")
            if item:
                prev = DailyEntry.previous_stock(farm_id, item.id, entry_date, before_id)
                validated_data[f"{slot}_stock"] = Decimal(str(prev)) - Decimal(str(qty))
            else:
                validated_data[f"{slot}_stock"] = Decimal("0")
        return validated_data

    def _recompute_chains(self, instance):
        from .views import _recompute_stock_chain

        _recompute_stock_chain(instance.farm_id, instance.feed_1_id)
        _recompute_stock_chain(instance.farm_id, instance.feed_2_id)

    def create(self, validated_data):
        request = self.context.get("request")
        if request is not None and not validated_data.get("entry_by"):
            validated_data["entry_by"] = request.user
        instance = super().create(self._apply_derived(validated_data))
        self._recompute_chains(instance)
        return instance

    def update(self, instance, validated_data):
        # Capture the pre-edit items too: moving a row off a feed item still
        # changes that item's chain for every row that followed it.
        previous_items = (instance.feed_1_id, instance.feed_2_id)
        previous_farm_id = instance.farm_id
        instance = super().update(instance, self._apply_derived(validated_data))
        self._recompute_chains(instance)

        from .views import _recompute_stock_chain

        for item_id in previous_items:
            if item_id and item_id not in (instance.feed_1_id, instance.feed_2_id):
                _recompute_stock_chain(previous_farm_id, item_id)
        return instance


class BirdSaleFarmLookupView(V1ViewMixin, APIView):
    """GET /api/v1/broiler/farm-lookup?farm=<id> — the farm's active batch,
    owning farmer, batch age, and next entry date. Serves the auto-filled
    fields on the Bird Sale, Daily Entry, and Medicine Entry forms (mirrors the
    web ``bird_sale_farm_lookup`` + ``daily_entry_farm_lookup``)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        # The batch/day/age resolution is shared with the web form rather than
        # repeated here: this endpoint's own copy had drifted on all three
        # counts (age from a raw start_date, dating from the farm's last entry
        # instead of the batch's, and falling back to today rather than the day
        # after placement), so a newly placed flock reported age 0 dated today.
        from .views import _batch_options, placement_context

        farm_id = request.query_params.get("farm")
        ctx = placement_context(farm_id, request.query_params.get("date"),
                                request.query_params.get("batch"))
        batch = ctx["batch"]
        farm = (BroilerFarm.objects.filter(id=farm_id).select_related("farmer").first()
                if farm_id else None)

        return Response({
            "batch": batch.id if batch else None,
            "batch_name": batch.batch_name if batch else "",
            "batches": _batch_options(farm_id),
            "farmer": farm.farmer_id if farm else None,
            "farmer_name": farm.farmer.farmer_name if farm and farm.farmer_id else "",
            "age_days": ctx["age_days"],
            # The resolved placement, not the raw column: a batch placed by
            # stock transfer has no start_date, and sending None there is what
            # left the app computing age 0.
            "start_date": ctx["placed_on"].isoformat() if ctx["placed_on"] else None,
            "next_date": ctx["next_date"].isoformat(),
        })


class DailyEntryLookupView(V1ViewMixin, APIView):
    """GET /api/v1/broiler/daily-entry-lookup?farm=<id>&date=<iso> — everything
    the Daily Entry form needs to advise the user: the active batch and age,
    plus the feed phase for that age, the breed-standard feed/weight targets,
    the live-bird count and the feed consumed so far.

    Separate from ``farm-lookup`` on purpose. That endpoint is shared with the
    Bird Sale and Medicine Entry forms, and this payload walks every prior
    entry of the batch to weight feed per surviving bird — cost those two
    forms have no use for.

    Delegates to ``broiler.views.daily_entry_lookup_payload``, the same
    function backing the web form, so a rule can never apply on one client and
    not the other.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .views import daily_entry_lookup_payload

        return Response(daily_entry_lookup_payload(
            request.query_params.get("farm"),
            request.query_params.get("date"),
            # A farm running two flocks is asked which one; without passing the
            # answer on, age, phase and standards would come back for whichever
            # batch the server picked by default.
            request.query_params.get("batch"),
        ))


class DailyEntryStockLookupView(V1ViewMixin, APIView):
    """GET /api/v1/broiler/daily-entry-stock?farm=<id>&item=<id>&date=<iso> —
    opening stock for a farm+feed item on that date, i.e. the closing balance
    of the most recent entry before it (0 when there is none).

    Seeds the form's running-stock preview; the client then subtracts what is
    typed. Mirrors the web ``daily_entry_stock_lookup``.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.utils.dateparse import parse_date

        farm_id = request.query_params.get("farm")
        item_id = request.query_params.get("item")
        entry_date = parse_date(request.query_params.get("date") or "")
        if not farm_id or not item_id or not entry_date:
            return Response({"stock": "0"})
        stock = DailyEntry.previous_stock(farm_id, int(item_id), entry_date, None)
        return Response({"stock": str(stock)})


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
    register_model(router, "broiler/daily-entries", DailyEntry,
                   serializer=DailyEntrySerializer, cursor=True)
    register_model(router, "broiler/medicine-vaccine-entries", MedicineVaccineEntry, cursor=True)
    register_model(router, "broiler/bird-sales", BirdSale, serializer=BirdSaleSerializer,
                   search_fields=["sale_no", "doc_no", "vehicle", "driver"], cursor=True)
    register_model(router, "broiler/bird-sale-receipts", BirdSaleReceipt, cursor=True)

    # --- Growing-charge settlement / batch closing (read-only) ----------
    register_model(router, "broiler/gc-settlements", GrowingChargeSettlement, read_only=True,
                   search_fields=["settlement_code"], ordering=["-id"])
