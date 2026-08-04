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

from urllib.parse import quote

from django.core.cache import cache
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
    DailyEntryPhoto,
    FarmCaptureFile,
    FarmLocationCapture,
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


class DailyEntryPhotoSerializer(serializer_factory(DailyEntryPhoto)):
    """Extra photo evidence on a Daily Entry.

    The per-category cap is enforced here rather than left to the client: the
    phone counts what it has on screen, which is not what the server has if the
    same entry was photographed from two devices, or if a retry re-sent a batch
    that had already landed.
    """

    def validate(self, attrs):
        attrs = super().validate(attrs)
        entry = attrs.get("entry") or getattr(self.instance, "entry", None)
        kind = attrs.get("kind") or getattr(self.instance, "kind", None)
        if entry is not None and kind:
            existing = DailyEntryPhoto.objects.filter(entry=entry, kind=kind)
            if self.instance is not None:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.count() >= DailyEntryPhoto.MAX_PER_KIND:
                raise serializers.ValidationError({
                    "image": (
                        f"This entry already has {DailyEntryPhoto.MAX_PER_KIND} "
                        f"{kind} photos, which is the limit."
                    )
                })
        return attrs


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
        from .views import _resolve_batch

        attrs = super().validate(attrs)
        farm = attrs.get("farm") or getattr(self.instance, "farm", None)
        if farm is not None:
            # The chosen batch, checked against the farm, falling back to the
            # farm's active one — the web form's rule. Overriding with the
            # active batch unconditionally meant a supervisor who picked one of
            # two open flocks had the entry filed against the other.
            chosen = attrs.get("batch") or getattr(self.instance, "batch", None)
            attrs["batch"] = _resolve_batch(farm.id, chosen.id if chosen else None)
        return attrs

    def _current(self, validated_data, name, default=None):
        """Field value for this write: the incoming value when supplied,
        otherwise the instance's existing one (PATCH sends partial data)."""
        if name in validated_data:
            return validated_data[name]
        return getattr(self.instance, name, default) if self.instance else default

    def _apply_derived(self, validated_data):
        from .views import _placement_date

        entry_date = self._current(validated_data, "date") or timezone.localdate()
        batch = self._current(validated_data, "batch")
        farm = self._current(validated_data, "farm")
        farm_id = farm.id if farm else None

        # Placement day is Age 0; the first entry day (the day after placement)
        # is Age 1 — same rule as the web form, and the same *source* for the
        # placement day. Reading `batch.start_date` here was the drift: a batch
        # created from a chicks placement leaves it blank, so every entry the
        # phone saved for such a flock stored age 0 while the ERP showed its
        # real age. `_placement_date` falls back to the placement transfer.
        placed_on = _placement_date(batch)
        validated_data["age_days"] = (
            max((entry_date - placed_on).days, 0) if placed_on else 0)

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


class MedicineVaccineEntrySerializer(serializer_factory(MedicineVaccineEntry)):
    """The Daily Entry treatment applied to Medicine/Vaccine Consumption.

    Same shape, same trap: ``age_days`` and ``stock`` are ``editable=False``,
    so DRF never takes them from the request and they save as 0 unless derived
    here — and ``MedicineVaccineEntry.previous_stock`` chains each row's
    opening balance off the previous row's closing balance, so one zeroed row
    corrupts that item's ledger at that farm from then on.

    New records normally arrive at ``/broiler/medicine-entries/save``, which
    runs the web view itself. This covers the other door: correcting one saved
    line through the generic resource route.
    """

    def validate(self, attrs):
        from .views import _resolve_batch

        attrs = super().validate(attrs)
        farm = attrs.get("farm") or getattr(self.instance, "farm", None)
        if farm is not None:
            chosen = attrs.get("batch") or getattr(self.instance, "batch", None)
            attrs["batch"] = _resolve_batch(farm.id, chosen.id if chosen else None)
        return attrs

    def _apply_derived(self, validated_data):
        from .views import _placement_date

        def current(name, default=None):
            if name in validated_data:
                return validated_data[name]
            return getattr(self.instance, name, default) if self.instance else default

        entry_date = current("date") or timezone.localdate()
        farm, item = current("farm"), current("item")
        placed_on = _placement_date(current("batch"))
        validated_data["age_days"] = (
            max((entry_date - placed_on).days, 0) if placed_on else 0)

        before_id = self.instance.pk if self.instance else None
        qty = current("qty") or Decimal("0")
        prev = MedicineVaccineEntry.previous_stock(
            farm.id if farm else None, item.id if item else None, entry_date, before_id)
        validated_data["stock"] = Decimal(str(prev)) - Decimal(str(qty))
        return validated_data

    def _recompute(self, farm_id, item_id):
        from .views import _recompute_medicine_stock_chain

        _recompute_medicine_stock_chain(farm_id, item_id)

    def create(self, validated_data):
        request = self.context.get("request")
        if request is not None and not validated_data.get("entry_by"):
            validated_data["entry_by"] = request.user
        instance = super().create(self._apply_derived(validated_data))
        self._recompute(instance.farm_id, instance.item_id)
        return instance

    def update(self, instance, validated_data):
        # Moving a row onto a different item still changes the old item's
        # chain for every row that followed it.
        was = (instance.farm_id, instance.item_id)
        instance = super().update(instance, self._apply_derived(validated_data))
        self._recompute(instance.farm_id, instance.item_id)
        if was != (instance.farm_id, instance.item_id):
            self._recompute(*was)
        return instance


class FarmLocationCaptureSerializer(serializer_factory(FarmLocationCapture)):
    """A capture as the phone's register and form want it.

    ``farmer`` is a property reading through to ``farm.farmer`` — the model
    deliberately does not store its own copy, so a farm changing hands cannot
    leave a capture pointing at the wrong person. It is surfaced here because
    the form shows it, and a per-row lookup to rebuild it would be one request
    per line of the register.

    Attachments come as a list rather than a count: the form has to show which
    slots are already filled, and "3 files" does not say whether the PAN card
    is one of them.
    """

    farmer_label = serializers.SerializerMethodField()
    files = serializers.SerializerMethodField()

    def get_farmer_label(self, obj) -> str:
        farmer = obj.farmer
        return farmer.farmer_name if farmer else ""

    def get_files(self, obj) -> list:
        return [{
            "id": f.id,
            "kind": f.kind,
            "label": f.get_kind_display(),
            "name": f.file.name.rsplit("/", 1)[-1] if f.file else "",
            "url": f.file.url if f.file else "",
        } for f in obj.files.all()]


class ReverseGeocodeView(V1ViewMixin, APIView):
    """GET /api/v1/geo/reverse?lat=&lon= — a pin as an address.

    Proxied rather than called from the device. Nominatim refuses a request
    with no User-Agent (403), which is exactly what React Native's fetch sends,
    so the phone's Farm Location Capture silently got no address while the ERP
    — a browser, which always sends one — filled it in. Going through the
    server also means both clients read the same reply the same way.

    A failure is an empty answer, never an error: the coordinates are the
    record and the address is a convenience on top, so a capture taken where
    the lookup times out still saves the pin it has.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        import json
        from urllib.error import URLError
        from urllib.request import Request, urlopen

        lat = request.query_params.get("lat")
        lon = request.query_params.get("lon")
        if not lat or not lon:
            return Response({"display": "", "state": "", "district": "", "area": ""})

        cache_key = f"geo:reverse:{lat}:{lon}"
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        url = ("https://nominatim.openstreetmap.org/reverse?format=jsonv2"
               f"&lat={quote(str(lat))}&lon={quote(str(lon))}"
               "&zoom=18&addressdetails=1")
        # Nominatim's usage policy wants an identifying User-Agent; without one
        # it answers 403 rather than an address.
        req = Request(url, headers={
            "User-Agent": "HitechBIMS/1.0 (+farm location capture)",
            "Accept": "application/json",
        })
        try:
            with urlopen(req, timeout=8) as resp:
                data = json.load(resp)
        except (URLError, ValueError, TimeoutError, OSError):
            return Response({"display": "", "state": "", "district": "", "area": ""})

        a = data.get("address") or {}
        first = lambda *keys: next((a[k] for k in keys if a.get(k)), "")
        place = {
            "display": data.get("display_name") or "",
            "state": first("state"),
            "district": first("state_district", "county", "district"),
            "area": first("suburb", "village", "town", "city_district",
                          "neighbourhood", "hamlet", "city"),
        }
        # The same pin resolves to the same place; a day is generous and keeps
        # a supervisor re-reading their location off Nominatim entirely.
        cache.set(cache_key, place, 60 * 60 * 24)
        return Response(place)


class MedicineItemLookupView(V1ViewMixin, APIView):
    """GET /api/v1/broiler/medicine-item-lookup?item=<id> — the item's
    consumption unit, for the auto-filled Unit column on the phone's
    Medicine/Vaccine Consumption form.

    Mirrors the web ``medicine_entry_item_lookup``, and reuses its label
    helper rather than formatting the UOM again: a unit that reads "ml" on
    the desktop and "MILLILITRE" on the phone is the same drift the shared
    registries exist to prevent.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from inventory.models import Item

        from .views import _uom_label

        item_id = request.query_params.get("item")
        item = Item.objects.filter(id=item_id).first() if item_id else None
        return Response({"unit": _uom_label(item.consumption_uom) if item else ""})


class MedicineStockLookupView(V1ViewMixin, APIView):
    """GET /api/v1/broiler/medicine-stock-lookup?farm=&item=&date= — the
    opening stock for that farm and item on that date.

    The closing balance of the last saved entry before the date, or 0. It is a
    running balance the server owns, not a number the client can compute, which
    is why the phone reads it rather than deriving it — the same reason the
    field is read-only on the web form.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .models import MedicineVaccineEntry

        farm_id = request.query_params.get("farm")
        item_id = request.query_params.get("item")
        raw_date = request.query_params.get("date")
        if not (farm_id and item_id and raw_date):
            return Response({"stock": "0"})
        try:
            on = timezone.datetime.fromisoformat(raw_date).date()
        except ValueError:
            return Response({"stock": "0"})
        stock = MedicineVaccineEntry.previous_stock(farm_id, int(item_id), on, None)
        return Response({"stock": str(stock)})


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
    # Extra photo evidence, one row per picture. Uploaded after the entry
    # itself, since each photo needs the entry's id to hang off.
    register_model(router, "broiler/daily-entry-photos", DailyEntryPhoto,
                   serializer=DailyEntryPhotoSerializer, ordering=["kind", "id"])
    # Creates and edits go to broiler/location-captures/save, where the web
    # form's own _save_capture places the attached files and mirrors them onto
    # the farm and farmer masters. Full CRUD is registered here anyway for the
    # register's Delete, which has to run the model's delete() — a cascade
    # would skip FarmCaptureFile.delete() and orphan the mirrored pictures.
    register_model(router, "broiler/location-captures", FarmLocationCapture,
                   serializer=FarmLocationCaptureSerializer,
                   search_fields=["capture_no", "state", "district", "area"],
                   ordering=["-date", "-id"], cursor=True)
    register_model(router, "broiler/medicine-vaccine-entries", MedicineVaccineEntry,
                   serializer=MedicineVaccineEntrySerializer, cursor=True)
    register_model(router, "broiler/bird-sales", BirdSale, serializer=BirdSaleSerializer,
                   search_fields=["sale_no", "doc_no", "vehicle", "driver"], cursor=True)
    register_model(router, "broiler/bird-sale-receipts", BirdSaleReceipt, cursor=True)

    # --- Growing-charge settlement / batch closing (read-only) ----------
    register_model(router, "broiler/gc-settlements", GrowingChargeSettlement, read_only=True,
                   search_fields=["settlement_code"], ordering=["-id"])
