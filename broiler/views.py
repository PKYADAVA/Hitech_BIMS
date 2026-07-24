#pylint: disable=no-member

from typing import Dict, List, Optional, Union
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views import View
from django.http import Http404, JsonResponse
from django.db.models import F, Prefetch, Q, Sum
from django.core.files.storage import default_storage
from django.core.exceptions import ValidationError
from django.db import transaction
from django.core.cache import cache
from django.conf import settings
from .models import (
    BirdSale, BirdSaleReceipt, Branch, Breed, BreedStandard, BroilerBatch, BroilerDisease, BroilerFarm, BroilerFarmImage,
    BroilerFarmShed, BroilerLine, DailyEntry, Farmer, FarmerGroup,
    GrowingChargeScheme, GCProductionCostIncentive, GCSalesIncentive, GCMortalityIncentive,
    GCFCRIncentive, GCSummerIncentive, GCProductionCostDecentive, GCMortalityDecentive,
    GCFCRRecovery, GCFarmerClassification, GrowingChargeSettlement, MedicineVaccineEntry,
    Region, Supervisor,
)
from account.models import ChartOfAccount
from inventory.models import Item, Warehouse
from sales.models import Customer
from hatchery_master.models import Hatchery
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from datetime import timedelta
from django.utils import timezone
import json
import logging

logger = logging.getLogger(__name__)


def _uom_label(uom):
    """Display text for a UnitOfMeasurement FK (symbol if set, else name)."""
    if not uom:
        return ""
    return uom.symbol or uom.name

# Constants
STATES_AND_TERRITORIES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
    "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka",
    "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram",
    "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu",
    "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
    "Andaman and Nicobar Islands", "Chandigarh",
    "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Jammu and Kashmir",
    "Ladakh", "Lakshadweep", "Puducherry",
]

class BaseAPIView(View):
    """Base class for API views with common functionality."""
    
    def handle_exception(self, e: Exception) -> JsonResponse:
        """Handle common exceptions and return appropriate responses."""
        logger.error(f"Error in {self.__class__.__name__}: {str(e)}", exc_info=True)
        if isinstance(e, Http404):
            return JsonResponse({"error": str(e)}, status=404)
        if isinstance(e, ValidationError):
            if hasattr(e, "message_dict"):
                message = "; ".join(
                    f"{field}: {' '.join(msgs)}" for field, msgs in e.message_dict.items()
                )
            else:
                message = "; ".join(e.messages)
            return JsonResponse({"error": message}, status=400)
        return JsonResponse({"error": "Internal server error"}, status=500)

    def get_cached_data(self, cache_key: str, ttl: int = 300) -> Optional[List]:
        """Get data from cache or return None if not found."""
        return cache.get(cache_key)

    def set_cached_data(self, cache_key: str, data: List, ttl: int = 300) -> None:
        """Set data in cache with specified TTL."""
        cache.set(cache_key, data, ttl)

@method_decorator(login_required, name="dispatch")
class FarmerGroupTemplateView(View):
    """View for rendering the farmer group template."""

    def get(self, request):
        context = {"chart_of_accounts": ChartOfAccount.objects.filter(status='Active')}
        return render(request, "farmer_group.html", context)

@method_decorator(login_required, name="dispatch")
class FarmerGroupAPI(BaseAPIView):
    """API endpoints for FarmerGroup operations."""

    def get(self, request, id: Optional[int] = None) -> JsonResponse:
        try:
            if id:
                fg = FarmerGroup.objects.get(id=id)
                return JsonResponse({
                    "id": fg.id,
                    "code": fg.code,
                    "description": fg.description,
                    "pay_account_id": fg.pay_account_id,
                    "pay_account_name": fg.pay_account.description,
                    "advance_account_id": fg.advance_account_id,
                    "advance_account_name": fg.advance_account.description,
                    "is_active": fg.is_active,
                    "is_locked": fg.is_locked,
                })

            farmer_groups = FarmerGroup.objects.select_related("pay_account", "advance_account").all()
            results = [{
                "id": fg.id,
                "code": fg.code,
                "description": fg.description,
                "pay_account_name": fg.pay_account.description,
                "advance_account_name": fg.advance_account.description,
                "is_active": fg.is_active,
                "is_locked": fg.is_locked,
            } for fg in farmer_groups]
            return JsonResponse(results, safe=False)
        except Exception as e:
            return self.handle_exception(e)

    def post(self, request) -> JsonResponse:
        try:
            data = request.POST
            with transaction.atomic():
                FarmerGroup.objects.create(
                    description=data["description"],
                    pay_account_id=data["pay_account"],
                    advance_account_id=data["advance_account"],
                )
            return JsonResponse({"message": "Farmer group created"}, status=201)
        except Exception as e:
            return self.handle_exception(e)

    def put(self, request, id: int) -> JsonResponse:
        try:
            fg = FarmerGroup.objects.get(id=id)
            if fg.is_locked:
                return JsonResponse({"error": "This farmer group is locked."}, status=400)
            data = json.loads(request.body)
            with transaction.atomic():
                fg.description = data["description"]
                fg.pay_account_id = data["pay_account"]
                fg.advance_account_id = data["advance_account"]
                fg.save()
            return JsonResponse({"message": "Farmer group updated"})
        except Exception as e:
            return self.handle_exception(e)

    def delete(self, request, id: int) -> JsonResponse:
        try:
            fg = FarmerGroup.objects.get(id=id)
            if fg.is_locked:
                return JsonResponse({"error": "This farmer group is locked."}, status=400)
            with transaction.atomic():
                fg.delete()
            return JsonResponse({"message": "Farmer group deleted"})
        except Exception as e:
            return self.handle_exception(e)


@login_required
def toggle_farmer_group_active(request, id):
    """Toggle a farmer group's active/inactive status."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=400)
    try:
        fg = FarmerGroup.objects.get(id=id)
        if fg.is_locked:
            return JsonResponse({"error": "This farmer group is locked."}, status=400)
        fg.is_active = not fg.is_active
        fg.save(update_fields=["is_active"])
        return JsonResponse({"message": "Farmer group updated", "is_active": fg.is_active})
    except FarmerGroup.DoesNotExist:
        return JsonResponse({"error": "Farmer group not found."}, status=404)


@login_required
def toggle_farmer_group_lock(request, id):
    """Toggle a farmer group's locked status."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=400)
    try:
        fg = FarmerGroup.objects.get(id=id)
        fg.is_locked = not fg.is_locked
        fg.save(update_fields=["is_locked"])
        return JsonResponse({"message": "Farmer group updated", "is_locked": fg.is_locked})
    except FarmerGroup.DoesNotExist:
        return JsonResponse({"error": "Farmer group not found."}, status=404)


@method_decorator(login_required, name="dispatch")
class RegionTemplateView(View):
    """View for rendering the region template."""

    def get(self, request):
        context = {"states_and_union_territories": STATES_AND_TERRITORIES}
        return render(request, "region.html", context)

@method_decorator(login_required, name="dispatch")
class RegionAPI(BaseAPIView):
    """API endpoints for Region operations."""

    def get(self, request, id: Optional[int] = None) -> JsonResponse:
        try:
            if id:
                region = Region.objects.get(id=id)
                return JsonResponse({
                    "id": region.id,
                    "code": region.code,
                    "description": region.description,
                    "is_active": region.is_active,
                    "is_locked": region.is_locked,
                })

            regions = Region.objects.all()
            results = [{
                "id": region.id,
                "code": region.code,
                "description": region.description,
                "is_active": region.is_active,
                "is_locked": region.is_locked,
            } for region in regions]
            return JsonResponse(results, safe=False)
        except Exception as e:
            return self.handle_exception(e)

    def post(self, request) -> JsonResponse:
        try:
            data = request.POST
            with transaction.atomic():
                Region.objects.create(description=data["description"])
            return JsonResponse({"message": "Region created"}, status=201)
        except Exception as e:
            return self.handle_exception(e)

    def put(self, request, id: int) -> JsonResponse:
        try:
            region = Region.objects.get(id=id)
            if region.is_locked:
                return JsonResponse({"error": "This region is locked."}, status=400)
            data = json.loads(request.body)
            with transaction.atomic():
                region.description = data["description"]
                region.save()
            return JsonResponse({"message": "Region updated"})
        except Exception as e:
            return self.handle_exception(e)

    def delete(self, request, id: int) -> JsonResponse:
        try:
            region = Region.objects.get(id=id)
            if region.is_locked:
                return JsonResponse({"error": "This region is locked."}, status=400)
            with transaction.atomic():
                region.delete()
            return JsonResponse({"message": "Region deleted"})
        except Exception as e:
            return self.handle_exception(e)


@login_required
def toggle_region_active(request, id):
    """Toggle a region's active/inactive status."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=400)
    try:
        region = Region.objects.get(id=id)
        if region.is_locked:
            return JsonResponse({"error": "This region is locked."}, status=400)
        region.is_active = not region.is_active
        region.save(update_fields=["is_active"])
        return JsonResponse({"message": "Region updated", "is_active": region.is_active})
    except Region.DoesNotExist:
        return JsonResponse({"error": "Region not found."}, status=404)


@login_required
def toggle_region_lock(request, id):
    """Toggle a region's locked status."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=400)
    try:
        region = Region.objects.get(id=id)
        region.is_locked = not region.is_locked
        region.save(update_fields=["is_locked"])
        return JsonResponse({"message": "Region updated", "is_locked": region.is_locked})
    except Region.DoesNotExist:
        return JsonResponse({"error": "Region not found."}, status=404)


@method_decorator(login_required, name="dispatch")
class BreedTemplateView(View):
    """View for rendering the breed template."""

    def get(self, request):
        return render(request, "breed.html")


@method_decorator(login_required, name="dispatch")
class BreedAPI(BaseAPIView):
    """API endpoints for Breed operations."""

    def get(self, request, id: Optional[int] = None) -> JsonResponse:
        try:
            if id:
                breed = Breed.objects.get(id=id)
                return JsonResponse({
                    "id": breed.id,
                    "code": breed.code,
                    "description": breed.description,
                    "is_active": breed.is_active,
                    "is_locked": breed.is_locked,
                })

            breeds = Breed.objects.all()
            results = [{
                "id": breed.id,
                "code": breed.code,
                "description": breed.description,
                "is_active": breed.is_active,
                "is_locked": breed.is_locked,
            } for breed in breeds]
            return JsonResponse(results, safe=False)
        except Breed.DoesNotExist:
            return JsonResponse({"error": "Breed not found."}, status=404)
        except Exception as e:
            return self.handle_exception(e)

    def post(self, request) -> JsonResponse:
        try:
            data = request.POST
            with transaction.atomic():
                Breed.objects.create(description=data["description"])
            return JsonResponse({"message": "Breed created"}, status=201)
        except Exception as e:
            return self.handle_exception(e)

    def put(self, request, id: int) -> JsonResponse:
        try:
            breed = Breed.objects.get(id=id)
            if breed.is_locked:
                return JsonResponse({"error": "This breed is locked."}, status=400)
            data = json.loads(request.body)
            with transaction.atomic():
                breed.description = data["description"]
                breed.save()
            return JsonResponse({"message": "Breed updated"})
        except Breed.DoesNotExist:
            return JsonResponse({"error": "Breed not found."}, status=404)
        except Exception as e:
            return self.handle_exception(e)

    def delete(self, request, id: int) -> JsonResponse:
        try:
            breed = Breed.objects.get(id=id)
            if breed.is_locked:
                return JsonResponse({"error": "This breed is locked."}, status=400)
            with transaction.atomic():
                breed.delete()
            return JsonResponse({"message": "Breed deleted"})
        except Breed.DoesNotExist:
            return JsonResponse({"error": "Breed not found."}, status=404)
        except Exception as e:
            return self.handle_exception(e)


@login_required
def toggle_breed_active(request, id):
    """Toggle a breed's active/inactive status."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=400)
    try:
        breed = Breed.objects.get(id=id)
        if breed.is_locked:
            return JsonResponse({"error": "This breed is locked."}, status=400)
        breed.is_active = not breed.is_active
        breed.save(update_fields=["is_active"])
        return JsonResponse({"message": "Breed updated", "is_active": breed.is_active})
    except Breed.DoesNotExist:
        return JsonResponse({"error": "Breed not found."}, status=404)


@login_required
def toggle_breed_lock(request, id):
    """Toggle a breed's locked status."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=400)
    try:
        breed = Breed.objects.get(id=id)
        breed.is_locked = not breed.is_locked
        breed.save(update_fields=["is_locked"])
        return JsonResponse({"message": "Breed updated", "is_locked": breed.is_locked})
    except Breed.DoesNotExist:
        return JsonResponse({"error": "Breed not found."}, status=404)


def _to_decimal(value):
    """Parse a user-supplied number, treating blanks as 0."""
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def _fmt(value):
    """Render a Decimal without trailing zeros (12.00 -> '12', 0.240 -> '0.24')."""
    s = f"{Decimal(value):f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


@method_decorator(login_required, name="dispatch")
class BreedStandardTemplateView(View):
    """View for rendering the breed standard template."""

    def get(self, request):
        context = {"breeds": Breed.objects.filter(is_active=True)}
        return render(request, "breed_standard.html", context)


def _breed_standard_row(bs):
    return {
        "id": bs.id,
        "code": bs.code,
        "age": bs.age,
        "body_weight": _fmt(bs.body_weight),
        "feed_intake": _fmt(bs.feed_intake),
        "avg_daily_gain": _fmt(bs.avg_daily_gain),
        "fcr": _fmt(bs.fcr),
        "cum_feed": _fmt(bs.cum_feed),
        "is_active": bs.is_active,
        "is_locked": bs.is_locked,
    }


@method_decorator(login_required, name="dispatch")
class BreedStandardAPI(BaseAPIView):
    """API endpoints for Breed Standard operations. The list is grouped
    into one folder per breed."""

    def get(self, request, id: Optional[int] = None) -> JsonResponse:
        try:
            if id:
                bs = BreedStandard.objects.select_related("breed").get(id=id)
                data = _breed_standard_row(bs)
                data.update({"breed_id": bs.breed_id, "breed_name": bs.breed.description})
                return JsonResponse(data)

            # Flat list, ordered by breed then age (keeps each breed's rows together).
            rows = (
                BreedStandard.objects.select_related("breed")
                .order_by("breed__code", "age")
            )
            results = []
            for bs in rows:
                data = _breed_standard_row(bs)
                data.update({
                    "breed_id": bs.breed_id,
                    "breed_code": bs.breed.code,
                    "breed_name": bs.breed.description,
                })
                results.append(data)
            return JsonResponse(results, safe=False)
        except BreedStandard.DoesNotExist:
            return JsonResponse({"error": "Breed standard not found."}, status=404)
        except Exception as e:
            return self.handle_exception(e)

    def delete(self, request, id: int) -> JsonResponse:
        try:
            bs = BreedStandard.objects.get(id=id)
            if bs.is_locked:
                return JsonResponse({"error": "This breed standard row is locked."}, status=400)
            with transaction.atomic():
                bs.delete()
            return JsonResponse({"message": "Breed standard deleted"})
        except BreedStandard.DoesNotExist:
            return JsonResponse({"error": "Breed standard not found."}, status=404)
        except Exception as e:
            return self.handle_exception(e)


@login_required
def breed_standard_by_breed(request, breed_id: int):
    """Return all standard rows for a breed (used to load the edit form)."""
    try:
        breed = Breed.objects.get(id=breed_id)
    except Breed.DoesNotExist:
        return JsonResponse({"error": "Breed not found."}, status=404)
    rows = [
        _breed_standard_row(bs)
        for bs in BreedStandard.objects.filter(breed=breed).order_by("age")
    ]
    return JsonResponse({
        "breed_id": breed.id,
        "breed_name": breed.description,
        "rows": rows,
    })


@login_required
def save_breed_standard(request):
    """Create/replace the whole standard curve for a breed. Rows are
    re-numbered by age (1..N) in submitted order."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=400)
    try:
        data = json.loads(request.body or "{}")
        breed_id = data.get("breed_id")
        rows = data.get("rows") or []
        if not breed_id:
            return JsonResponse({"error": "Please select a breed."}, status=400)
        if not rows:
            return JsonResponse({"error": "Add at least one row."}, status=400)
        try:
            breed = Breed.objects.get(id=breed_id)
        except Breed.DoesNotExist:
            return JsonResponse({"error": "Invalid breed."}, status=400)

        existing = BreedStandard.objects.filter(breed=breed)
        if existing.filter(is_locked=True).exists():
            return JsonResponse(
                {"error": "This breed has locked rows. Unlock them before editing."},
                status=400,
            )

        # Resolve ages first (Age is editable; blanks default to row position) and
        # reject duplicates before we touch the DB, so nothing is half-written.
        ages = []
        seen = set()
        for idx, row in enumerate(rows, start=1):
            try:
                age = int(row.get("age"))
            except (TypeError, ValueError):
                age = idx
            if age <= 0:
                age = idx
            if age in seen:
                return JsonResponse(
                    {"error": f"Duplicate age {age}. Each row must have a unique age."},
                    status=400,
                )
            seen.add(age)
            ages.append(age)

        with transaction.atomic():
            existing.delete()
            cum_running = Decimal("0")  # running total, anchored to whatever is stored
            prev_body_weight = None     # previous row's body weight, for Avg Daily Gain
            for age, row in zip(ages, rows):
                body_weight = _to_decimal(row.get("body_weight"))
                feed_intake = _to_decimal(row.get("feed_intake"))

                # Cum. Feed: manual override if given, else previous cumulative + feed intake
                cum_raw = row.get("cum_feed")
                if cum_raw not in (None, ""):
                    cum_feed = _to_decimal(cum_raw)
                else:
                    cum_feed = cum_running + feed_intake
                cum_running = cum_feed

                # FCR: manual override if given, else cumulative feed / body weight
                fcr_raw = row.get("fcr")
                if fcr_raw not in (None, ""):
                    fcr = _to_decimal(fcr_raw)
                elif body_weight > 0:
                    fcr = (cum_feed / body_weight).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                else:
                    fcr = Decimal("0")

                # Avg Daily Gain: manual override if given, else this row's body
                # weight minus the previous row's (the first row has no previous
                # weight to diff against, so it falls back to 0 unless overridden).
                gain_raw = row.get("avg_daily_gain")
                if gain_raw not in (None, ""):
                    avg_daily_gain = _to_decimal(gain_raw)
                elif prev_body_weight is not None:
                    avg_daily_gain = body_weight - prev_body_weight
                else:
                    avg_daily_gain = Decimal("0")
                prev_body_weight = body_weight

                BreedStandard.objects.create(
                    breed=breed,
                    age=age,
                    body_weight=body_weight,
                    feed_intake=feed_intake,
                    avg_daily_gain=avg_daily_gain,
                    fcr=fcr,
                    cum_feed=cum_feed,
                )
        return JsonResponse({"message": "Breed standard saved"}, status=201)
    except Exception as e:
        logger.error(f"Error in save_breed_standard: {str(e)}", exc_info=True)
        return JsonResponse({"error": "Internal server error"}, status=500)


@login_required
def toggle_breed_standard_active(request, id):
    """Toggle a breed standard row's active/inactive status."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=400)
    try:
        bs = BreedStandard.objects.get(id=id)
        if bs.is_locked:
            return JsonResponse({"error": "This breed standard row is locked."}, status=400)
        bs.is_active = not bs.is_active
        bs.save(update_fields=["is_active"])
        return JsonResponse({"message": "Breed standard updated", "is_active": bs.is_active})
    except BreedStandard.DoesNotExist:
        return JsonResponse({"error": "Breed standard not found."}, status=404)


@login_required
def toggle_breed_standard_lock(request, id):
    """Toggle a breed standard row's locked status."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=400)
    try:
        bs = BreedStandard.objects.get(id=id)
        bs.is_locked = not bs.is_locked
        bs.save(update_fields=["is_locked"])
        return JsonResponse({"message": "Breed standard updated", "is_locked": bs.is_locked})
    except BreedStandard.DoesNotExist:
        return JsonResponse({"error": "Breed standard not found."}, status=404)


@method_decorator(login_required, name="dispatch")
class BranchTemplateView(View):
    """View for rendering the branch template."""

    def get(self, request):
        context = {
            "regions": Region.objects.filter(is_active=True),
        }
        return render(request, "branch.html", context)

def _branch_to_dict(branch: Branch) -> dict:
    return {
        "id": branch.id,
        "code": branch.code,
        "branch_name": branch.branch_name,
        "region_id": branch.region_id,
        "region_name": branch.region.description,
        "prefix": branch.prefix,
        "is_active": branch.is_active,
        "is_locked": branch.is_locked,
    }


@method_decorator(login_required, name="dispatch")
class BranchAPI(BaseAPIView):
    """API endpoints for Branch operations."""

    def get(self, request, id: Optional[int] = None) -> JsonResponse:
        try:
            if id:
                branch = Branch.objects.select_related("region").get(id=id)
                return JsonResponse(_branch_to_dict(branch))

            branches = Branch.objects.select_related("region").all()
            return JsonResponse([_branch_to_dict(b) for b in branches], safe=False)
        except Exception as e:
            return self.handle_exception(e)

    def post(self, request) -> JsonResponse:
        """Create one or more branches against a single region in one submit."""
        try:
            data = request.POST
            region = Region.objects.filter(id=data.get("region")).first()
            if not region:
                return JsonResponse({"error": "Select a valid region."}, status=400)

            branch_names = data.getlist("branch_name[]")
            prefixes = data.getlist("prefix[]")

            # Validate every row before creating anything.
            rows = []
            for branch_name, prefix in zip(branch_names, prefixes):
                branch_name = branch_name.strip()
                prefix = prefix.strip()
                if not branch_name and not prefix:
                    continue
                if not branch_name or not prefix:
                    return JsonResponse({"error": "Enter both a branch name and a prefix for every row."}, status=400)
                rows.append((branch_name, prefix))

            if not rows:
                return JsonResponse({"error": "Enter at least one branch name and prefix."}, status=400)

            created = 0
            with transaction.atomic():
                for branch_name, prefix in rows:
                    Branch.objects.create(region=region, branch_name=branch_name, prefix=prefix)
                    created += 1
                cache.delete("branch_list")

            return JsonResponse({"message": f"{created} branch(es) created"}, status=201)
        except Exception as e:
            return self.handle_exception(e)

    def put(self, request, id: int) -> JsonResponse:
        """Update the branch."""
        try:
            branch = Branch.objects.get(id=id)
            if branch.is_locked:
                return JsonResponse({"error": "This branch is locked."}, status=400)
            data = json.loads(request.body)
            region = Region.objects.filter(id=data.get("region")).first()
            if not region:
                return JsonResponse({"error": "Select a valid region."}, status=400)

            with transaction.atomic():
                branch.region = region
                branch.branch_name = data["branch_name"]
                branch.prefix = data["prefix"]
                branch.save()
                cache.delete("branch_list")
            return JsonResponse({"message": "Branch updated"})
        except Exception as e:
            return self.handle_exception(e)

    def delete(self, request, id: int) -> JsonResponse:
        try:
            branch = Branch.objects.get(id=id)
            if branch.is_locked:
                return JsonResponse({"error": "This branch is locked."}, status=400)
            with transaction.atomic():
                branch.delete()
                cache.delete("branch_list")
            return JsonResponse({"message": "Branch deleted"})
        except Exception as e:
            return self.handle_exception(e)


@login_required
def toggle_branch_active(request, id):
    """Toggle a branch's active/inactive status."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=400)
    try:
        branch = Branch.objects.get(id=id)
        if branch.is_locked:
            return JsonResponse({"error": "This branch is locked."}, status=400)
        branch.is_active = not branch.is_active
        branch.save(update_fields=["is_active"])
        cache.delete("branch_list")
        return JsonResponse({"message": "Branch updated", "is_active": branch.is_active})
    except Branch.DoesNotExist:
        return JsonResponse({"error": "Branch not found."}, status=404)


@login_required
def toggle_branch_lock(request, id):
    """Toggle a branch's locked status."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=400)
    try:
        branch = Branch.objects.get(id=id)
        branch.is_locked = not branch.is_locked
        branch.save(update_fields=["is_locked"])
        cache.delete("branch_list")
        return JsonResponse({"message": "Branch updated", "is_locked": branch.is_locked})
    except Branch.DoesNotExist:
        return JsonResponse({"error": "Branch not found."}, status=404)

@method_decorator(login_required, name="dispatch")
class SupervisorTemplateView(View):
    """View for rendering the supervisor template."""
    
    def get(self, request):
        from hr.models import Employee

        cache_key = "branch_list"
        branches = cache.get(cache_key)
        if not branches:
            branches = list(Branch.objects.values())
            cache.set(cache_key, branches)
        context = {
            "branches": branches,
            "employees": Employee.objects.filter(relieve=False).order_by("full_name"),
        }
        return render(request, "supervisor.html", context)

@method_decorator(login_required, name="dispatch")
class BroilerLineTemplateView(View):
    """View for rendering the broiler line template."""

    def get(self, request):
        context = {"regions": Region.objects.filter(is_active=True)}
        return render(request, "broiler_line.html", context)

@method_decorator(login_required, name="dispatch")
class BroilerFarmTemplateView(View):
    """View for rendering the broiler farm template (Add Farmer + Add Farm tabs)."""

    def get(self, request):
        farmers = list(Farmer.objects.values("id", "farmer_name"))
        context = {
            "regions": Region.objects.filter(is_active=True),
            "farmers": farmers,
            "farmer_groups": FarmerGroup.objects.filter(is_active=True),
            "shed_types": BroilerFarmShed.SHED_TYPE_CHOICES,
        }
        return render(request, "broiler_farm.html", context)

@method_decorator(login_required, name="dispatch")
class BroilerBatchTemplateView(View):
    """View for rendering the broiler batch template."""
    
    def get(self, request):
        cache_key = "broiler_farm_list"
        broiler_farms = cache.get(cache_key)
        if not broiler_farms:
            broiler_farms = list(BroilerFarm.objects.values())
            cache.set(cache_key, broiler_farms)
        context = {
            "broiler_farms": broiler_farms,
            "breeds": Breed.objects.filter(is_active=True).order_by("description"),
        }
        return render(request, "broiler_batch.html", context)

@method_decorator(login_required, name="dispatch")
class BroilerDiseaseTemplateView(View):
    """View for rendering the broiler disease template."""
    
    def get(self, request):
        cache_key = "broiler_farm_list"
        broiler_farms = cache.get(cache_key)
        if not broiler_farms:
            broiler_farms = list(BroilerFarm.objects.values())
            cache.set(cache_key, broiler_farms)
        context = {"broiler_farms": broiler_farms}
        return render(request, "broiler_disease.html", context)

@method_decorator(login_required, name="dispatch")
class SupervisorAPI(BaseAPIView):
    """API endpoints for Supervisor operations."""
    
    def get(self, request, id: Optional[int] = None) -> JsonResponse:
        try:
            if id:
                supervisor = Supervisor.objects.select_related("branch", "employee").get(id=id)
                return JsonResponse({
                    "id": supervisor.id,
                    "supervisor": supervisor.name,
                    "branch": supervisor.branch_id,
                    "branch_name": supervisor.branch.branch_name,
                    "employee": supervisor.employee_id,
                })

            cache_key = "supervisor_list"
            cached_data = self.get_cached_data(cache_key)
            if cached_data:
                return JsonResponse(cached_data, safe=False)

            supervisors = list(
                Supervisor.objects.select_related("branch")
                .annotate(branch_name=F("branch__branch_name"))
                .values("id", "name", "branch_name", "branch", "employee")
            )
            self.set_cached_data(cache_key, supervisors)
            return JsonResponse(supervisors, safe=False)
        except Exception as e:
            return self.handle_exception(e)

    @staticmethod
    def _apply_employee(supervisor, employee):
        """Supervisor's name/phone/address are always a copy of the chosen
        HR Employee record — Supervisor is picked from the Employee list,
        not typed in freehand."""
        supervisor.employee = employee
        supervisor.name = employee.full_name or ""
        supervisor.phone_no = str(employee.personal_contact) if employee.personal_contact else ""
        supervisor.address = employee.correspondence_address or ""

    def post(self, request) -> JsonResponse:
        from hr.models import Employee
        try:
            data = json.loads(request.body or "{}")
            try:
                branch = Branch.objects.get(id=data.get("branch"))
            except Branch.DoesNotExist:
                return JsonResponse({"error": "Invalid branch"}, status=400)
            try:
                employee = Employee.objects.get(id=data.get("employee"))
            except Employee.DoesNotExist:
                return JsonResponse({"error": "Select an employee"}, status=400)
            with transaction.atomic():
                supervisor = Supervisor(branch=branch)
                self._apply_employee(supervisor, employee)
                supervisor.save()
                cache.delete("supervisor_list")
            return JsonResponse({"message": "Supervisor created"}, status=201)
        except Exception as e:
            return self.handle_exception(e)

    def put(self, request, id: int) -> JsonResponse:
        from hr.models import Employee
        try:
            supervisor = Supervisor.objects.get(id=id)
            data = json.loads(request.body or "{}")
            with transaction.atomic():
                if data.get("branch"):
                    supervisor.branch_id = data["branch"]
                if data.get("employee"):
                    try:
                        employee = Employee.objects.get(id=data["employee"])
                    except Employee.DoesNotExist:
                        return JsonResponse({"error": "Invalid employee"}, status=400)
                    self._apply_employee(supervisor, employee)
                supervisor.save()
                cache.delete("supervisor_list")
            return JsonResponse({"message": "Supervisor updated"})
        except Supervisor.DoesNotExist:
            raise Http404("Supervisor not found")
        except Exception as e:
            return self.handle_exception(e)

    def delete(self, request, id: int) -> JsonResponse:
        try:
            supervisor = Supervisor.objects.get(id=id)
            with transaction.atomic():
                supervisor.delete()
                cache.delete("supervisor_list")
            return JsonResponse({"message": "Supervisor deleted"})
        except Exception as e:
            return self.handle_exception(e)

def _broiler_line_to_dict(line: BroilerLine) -> dict:
    return {
        "id": line.id,
        "code": line.code,
        "description": line.description,
        "region_id": line.region_id,
        "region_name": line.region.description,
        "branch_id": line.branch_id,
        "branch_name": line.branch.branch_name,
        "is_active": line.is_active,
        "is_locked": line.is_locked,
    }

@method_decorator(login_required, name="dispatch")
class BroilerLineAPI(BaseAPIView):
    """API endpoints for BroilerLine operations."""

    def get(self, request, id: Optional[int] = None) -> JsonResponse:
        try:
            if id:
                line = BroilerLine.objects.select_related("region", "branch").get(id=id)
                return JsonResponse(_broiler_line_to_dict(line))

            lines = BroilerLine.objects.select_related("region", "branch").all()
            return JsonResponse([_broiler_line_to_dict(l) for l in lines], safe=False)
        except Exception as e:
            return self.handle_exception(e)

    def post(self, request) -> JsonResponse:
        """Create one or more lines against a single region/branch in one submit."""
        try:
            data = request.POST
            region = Region.objects.filter(id=data.get("region")).first()
            branch = Branch.objects.filter(id=data.get("branch")).first()
            if not region or not branch:
                return JsonResponse({"error": "Select a valid region and branch."}, status=400)

            descriptions = data.getlist("description[]")

            created = 0
            with transaction.atomic():
                for description in descriptions:
                    description = description.strip()
                    if not description:
                        continue
                    BroilerLine.objects.create(region=region, branch=branch, description=description)
                    created += 1

            if not created:
                return JsonResponse({"error": "Enter at least one line."}, status=400)
            return JsonResponse({"message": f"{created} line(s) created"}, status=201)
        except Exception as e:
            return self.handle_exception(e)

    def put(self, request, id: int) -> JsonResponse:
        try:
            line = BroilerLine.objects.get(id=id)
            if line.is_locked:
                return JsonResponse({"error": "This line is locked."}, status=400)
            data = json.loads(request.body)
            region = Region.objects.filter(id=data.get("region")).first()
            branch = Branch.objects.filter(id=data.get("branch")).first()
            if not region or not branch:
                return JsonResponse({"error": "Select a valid region and branch."}, status=400)
            with transaction.atomic():
                line.region = region
                line.branch = branch
                line.description = data["description"]
                line.save()
            return JsonResponse({"message": "Line updated"})
        except Exception as e:
            return self.handle_exception(e)

    def delete(self, request, id: int) -> JsonResponse:
        try:
            line = BroilerLine.objects.get(id=id)
            if line.is_locked:
                return JsonResponse({"error": "This line is locked."}, status=400)
            with transaction.atomic():
                line.delete()
            return JsonResponse({"message": "Line deleted"})
        except Exception as e:
            return self.handle_exception(e)


@login_required
def toggle_broiler_line_active(request, id):
    """Toggle a broiler line's active/inactive status."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=400)
    try:
        line = BroilerLine.objects.get(id=id)
        if line.is_locked:
            return JsonResponse({"error": "This line is locked."}, status=400)
        line.is_active = not line.is_active
        line.save(update_fields=["is_active"])
        return JsonResponse({"message": "Line updated", "is_active": line.is_active})
    except BroilerLine.DoesNotExist:
        return JsonResponse({"error": "Line not found."}, status=404)


@login_required
def toggle_broiler_line_lock(request, id):
    """Toggle a broiler line's locked status."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=400)
    try:
        line = BroilerLine.objects.get(id=id)
        line.is_locked = not line.is_locked
        line.save(update_fields=["is_locked"])
        return JsonResponse({"message": "Line updated", "is_locked": line.is_locked})
    except BroilerLine.DoesNotExist:
        return JsonResponse({"error": "Line not found."}, status=404)


@login_required
def get_branches_by_region(request) -> JsonResponse:
    """Get branches for a specific region."""
    try:
        region_id = request.GET.get('region_id')
        branches = list(Branch.objects.filter(region_id=region_id, is_active=True).values('id', 'branch_name'))
        return JsonResponse({'branches': branches})
    except Exception as e:
        logger.error(f"Error in get_branches_by_region: {str(e)}", exc_info=True)
        return JsonResponse({"error": str(e)}, status=500)

@login_required
def get_lines_by_branch(request) -> JsonResponse:
    """Get broiler lines for a specific branch."""
    try:
        branch_id = request.GET.get('branch_id')
        lines = list(BroilerLine.objects.filter(branch_id=branch_id, is_active=True).values('id', 'description'))
        return JsonResponse({'lines': lines})
    except Exception as e:
        logger.error(f"Error in get_lines_by_branch: {str(e)}", exc_info=True)
        return JsonResponse({"error": str(e)}, status=500)

@method_decorator(login_required, name="dispatch")
class FarmerAPI(BaseAPIView):
    """API endpoints for Farmer operations."""

    FILE_FIELDS = ["farmer_photo", "pan_upload", "aadhar_upload_front", "aadhar_upload_back"]
    FORM_FIELDS = [
        "farmer_name", "phone_no", "mobile_no", "mobile_2", "pan_no", "aadhar_no",
        "national_id", "usc", "service_no", "tds_percent",
        "account_holder_name", "acc_no", "ifsc_code", "bank_name", "bank_branch", "address",
    ]

    def get(self, request, id: Optional[int] = None) -> JsonResponse:
        try:
            if id:
                farmer = Farmer.objects.select_related("farmer_group").get(id=id)
                data = {field: getattr(farmer, field) for field in self.FORM_FIELDS}
                data["id"] = farmer.id
                data["tds_percent"] = str(farmer.tds_percent) if farmer.tds_percent is not None else None
                data["farmer_group_id"] = farmer.farmer_group_id
                data["farmer_group"] = farmer.farmer_group.description if farmer.farmer_group_id else None
                for field in self.FILE_FIELDS:
                    file_obj = getattr(farmer, field)
                    data[field] = file_obj.url if file_obj else None
                return JsonResponse(data)

            cache_key = "farmer_list"
            cached_data = self.get_cached_data(cache_key)
            if cached_data:
                return JsonResponse(cached_data, safe=False)

            farmers = list(
                Farmer.objects.select_related("farmer_group").values(
                    "id", "farmer_name", "mobile_no", "usc", "service_no",
                    farmer_group_name=F("farmer_group__description"),
                )
            )
            self.set_cached_data(cache_key, farmers)
            return JsonResponse(farmers, safe=False)
        except Exception as e:
            return self.handle_exception(e)

    def post(self, request, id: Optional[int] = None) -> JsonResponse:
        try:
            data = request.POST
            with transaction.atomic():
                farmer = Farmer.objects.get(id=id) if id else Farmer()
                for field in self.FORM_FIELDS:
                    if field not in data:
                        continue
                    setattr(farmer, field, data[field] or None if field == "tds_percent" else data[field])
                if "farmer_group" in data:
                    farmer.farmer_group_id = data["farmer_group"] or None
                for field in self.FILE_FIELDS:
                    if field in request.FILES:
                        setattr(farmer, field, request.FILES[field])
                farmer.full_clean(exclude=self.FILE_FIELDS)
                farmer.save()
                cache.delete("farmer_list")
            return JsonResponse(
                {"message": "Farmer updated" if id else "Farmer created", "id": farmer.id},
                status=200 if id else 201,
            )
        except Exception as e:
            return self.handle_exception(e)

    def delete(self, request, id: int) -> JsonResponse:
        try:
            farmer = Farmer.objects.get(id=id)
            with transaction.atomic():
                farmer.delete()
                cache.delete("farmer_list")
            return JsonResponse({"message": "Farmer deleted"})
        except Exception as e:
            return self.handle_exception(e)

@method_decorator(login_required, name="dispatch")
class BroilerBatchAPI(BaseAPIView):
    """API endpoints for BroilerBatch operations."""
    
    def get(self, request, id: Optional[int] = None) -> JsonResponse:
        try:
            if id:
                broiler_batch = BroilerBatch.objects.select_related("broiler_farm").get(id=id)
                return JsonResponse({
                    "id": broiler_batch.id,
                    "name": broiler_batch.batch_name,
                    "book_number": broiler_batch.book_number,
                    "lot_no": broiler_batch.lot_no,
                    "breed_id": broiler_batch.breed_id,
                    "broiler_farm_name": broiler_batch.broiler_farm.farm_name,
                })

            cache_key = "broiler_batch_list"
            cached_data = self.get_cached_data(cache_key)
            if cached_data:
                return JsonResponse(cached_data, safe=False)

            broiler_batches = list(
                BroilerBatch.objects.select_related("broiler_farm", "breed")
                .annotate(broiler_farm_name=F("broiler_farm__farm_name"),
                          breed_name=F("breed__description"))
                .values("id", "batch_name", "book_number", "lot_no", "broiler_farm_name",
                        "breed_id", "breed_name")
            )
            self.set_cached_data(cache_key, broiler_batches)
            return JsonResponse(broiler_batches, safe=False)
        except Exception as e:
            return self.handle_exception(e)

    def post(self, request) -> JsonResponse:
        try:
            data = request.POST
            farm_obj = BroilerFarm.objects.get(id=data["broiler_farm_id"])
            with transaction.atomic():
                # batch_name is auto-generated (<farm code minus FRM/>-<n>,
                # e.g. BAH-0201-1) in BroilerBatch.save() — never accepted
                # from the form.
                batch = BroilerBatch.objects.create(
                    broiler_farm=farm_obj,
                    book_number=data.get("book_number") or "",
                    lot_no=data.get("lot_no") or "",
                    breed_id=data.get("breed") or None,
                )
                cache.delete("broiler_batch_list")
            return JsonResponse({"message": "BroilerBatch created", "batch_name": batch.batch_name}, status=201)
        except Exception as e:
            return self.handle_exception(e)

    def put(self, request, id: int) -> JsonResponse:
        try:
            broiler_batch = BroilerBatch.objects.get(id=id)
            data = json.loads(request.body or "{}")
            with transaction.atomic():
                # Only Book Number / Lot No are editable — batch_name is an
                # auto-generated code and the farm is fixed at creation.
                if "book_number" in data:
                    broiler_batch.book_number = data["book_number"] or ""
                if "lot_no" in data:
                    broiler_batch.lot_no = data["lot_no"] or ""
                if "breed" in data:
                    broiler_batch.breed_id = data["breed"] or None
                broiler_batch.save()
                cache.delete("broiler_batch_list")
            return JsonResponse({"message": "BroilerBatch updated"})
        except BroilerBatch.DoesNotExist:
            raise Http404("Broiler batch not found")
        except Exception as e:
            return self.handle_exception(e)

    def delete(self, request, id: int) -> JsonResponse:
        try:
            broiler_batch = BroilerBatch.objects.get(id=id)
            with transaction.atomic():
                broiler_batch.delete()
                cache.delete("broiler_batch_list")
            return JsonResponse({"message": "BroilerBatch deleted"})
        except Exception as e:
            return self.handle_exception(e)

@method_decorator(login_required, name="dispatch")
class BroilerDiseaseAPI(BaseAPIView):
    """API endpoints for BroilerDisease operations."""
    
    def get(self, request, id: Optional[int] = None) -> JsonResponse:
        try:
            if id:
                broiler_disease = BroilerDisease.objects.get(id=id)
                return JsonResponse({
                    "id": broiler_disease.id,
                    "disease_code": broiler_disease.disease_code,
                    "disease_name": broiler_disease.disease_name,
                    "symptoms": broiler_disease.symptoms,
                    "diagnosis": broiler_disease.diagnosis,
                    "image": broiler_disease.image.url if broiler_disease.image else None,
                })
            
            cache_key = "broiler_disease_list"
            cached_data = self.get_cached_data(cache_key)
            if cached_data:
                return JsonResponse(cached_data, safe=False)
            
            broiler_diseases = list(
                BroilerDisease.objects.values(
                    "id", "disease_code", "disease_name", "symptoms", "diagnosis", "image"
                )
            )
            for disease in broiler_diseases:
                disease["image"] = request.build_absolute_uri(disease["image"]) if disease["image"] else None
            
            self.set_cached_data(cache_key, broiler_diseases)
            return JsonResponse(broiler_diseases, safe=False)
        except Exception as e:
            return self.handle_exception(e)

    def post(self, request) -> JsonResponse:
        try:
            data = request.POST
            image = request.FILES.get("image")
            with transaction.atomic():
                BroilerDisease.objects.create(
                    disease_code=data["disease_code"],
                    disease_name=data["disease_name"],
                    symptoms=data["symptoms"],
                    diagnosis=data["diagnosis"],
                    image=image,
                )
                cache.delete("broiler_disease_list")
            return JsonResponse({"message": "BroilerDisease created"}, status=201)
        except Exception as e:
            return self.handle_exception(e)

    def put(self, request, id: int) -> JsonResponse:
        try:
            broiler_disease = BroilerDisease.objects.get(id=id)
            data = json.loads(request.body.decode("utf-8"))
            with transaction.atomic():
                broiler_disease.disease_code = data.get("disease_code", broiler_disease.disease_code)
                broiler_disease.disease_name = data.get("disease_name", broiler_disease.disease_name)
                broiler_disease.symptoms = data.get("symptoms", broiler_disease.symptoms)
                broiler_disease.diagnosis = data.get("diagnosis", broiler_disease.diagnosis)
                broiler_disease.save()
                cache.delete("broiler_disease_list")
            return JsonResponse({"message": "BroilerDisease updated"})
        except Exception as e:
            return self.handle_exception(e)

    def delete(self, request, id: int) -> JsonResponse:
        try:
            broiler_disease = BroilerDisease.objects.get(id=id)
            with transaction.atomic():
                if broiler_disease.image:
                    default_storage.delete(broiler_disease.image.path)
                broiler_disease.delete()
                cache.delete("broiler_disease_list")
            return JsonResponse({"message": "BroilerDisease deleted"})
        except Exception as e:
            return self.handle_exception(e)

@method_decorator(login_required, name="dispatch")
class BroilerFarmShedTemplateView(View):
    """Broiler > Master > Farm Shed — manage the sheds that belong to each farm.
    Organization Centre / Branch / Company auto-fill from the chosen farm."""

    def get(self, request):
        from account.models import OrganizationCentre, CompanyProfile
        company_name = CompanyProfile.get_solo().name
        oc_by_branch = {oc.branch_id: oc for oc
                        in OrganizationCentre.objects.select_related("company").all()
                        if oc.branch_id}
        farms = []
        for f in BroilerFarm.objects.select_related("branch").order_by("farm_code"):
            oc = oc_by_branch.get(f.branch_id)
            farms.append({
                "id": f.id, "farm_code": f.farm_code, "farm_name": f.farm_name,
                "branch_name": f.branch.branch_name if f.branch_id else "",
                "org_centre_name": oc.name if oc else "",
                "company_name": (oc.company.name if oc and oc.company_id else company_name),
            })
        return render(request, "broiler_farm_shed.html", {
            "farms": farms,
            "shed_types": BroilerFarmShed.SHED_TYPE_CHOICES,
        })


def _farm_shed_to_dict(s: BroilerFarmShed) -> dict:
    from account.models import CompanyProfile
    oc = s.organization_centre
    if oc and oc.company_id:
        company_name = oc.company.name
    else:
        company_name = CompanyProfile.get_solo().name
    return {
        "id": s.id,
        "shed_code": s.shed_code,
        "shed_name": s.shed_name or "",
        "farm_id": s.farm_id,
        "farm_code": s.farm.farm_code if s.farm_id else "",
        "farm_name": s.farm.farm_name if s.farm_id else "",
        "org_centre_id": s.organization_centre_id,
        "org_centre_name": oc.name if oc else "",
        "branch_name": s.farm.branch.branch_name if s.farm_id and s.farm.branch_id else "",
        "company_name": company_name,
        "shed_type": s.shed_type,
        "shed_type_display": s.get_shed_type_display(),
        "unit_no": s.unit_no,
        "is_active": s.is_active,
        "length": str(s.length) if s.length is not None else "",
        "width": str(s.width) if s.width is not None else "",
        "dimensions": s.dimensions or "",
        "sq_feet": s.sq_feet or "",
        "capacity": s.capacity,
        "occupied": s.occupied,
        "free_space": s.free_space,
        "utilization_pct": s.utilization_pct,
    }


@method_decorator(login_required, name="dispatch")
class BroilerFarmShedAPI(BaseAPIView):
    """CRUD for BroilerFarmShed (Broiler > Master > Farm Shed)."""

    def get(self, request, id: Optional[int] = None) -> JsonResponse:
        try:
            if id:
                s = BroilerFarmShed.objects.select_related("farm").get(id=id)
                return JsonResponse(_farm_shed_to_dict(s))
            sheds = (BroilerFarmShed.objects.select_related("farm")
                     .order_by("farm__farm_code", "shed_no"))
            return JsonResponse([_farm_shed_to_dict(s) for s in sheds], safe=False)
        except Exception as e:
            return self.handle_exception(e)

    _VALID_TYPES = {c[0] for c in BroilerFarmShed.SHED_TYPE_CHOICES}

    def _clean(self, data):
        farm = BroilerFarm.objects.filter(id=data.get("farm")).first()
        if not farm:
            return None, "Select a valid farm."
        shed_name = (data.get("shed_name") or "").strip()  # blank -> auto in model.save()
        shed_type = (data.get("shed_type") or "broiler").strip()
        if shed_type not in self._VALID_TYPES:
            return None, "Select a valid shed type."

        def _int(v):
            try:
                return max(int(float(v)), 0)
            except (TypeError, ValueError):
                return 0

        def _dec(v):
            v = (str(v) if v is not None else "").strip()
            if not v:
                return None
            try:
                return max(Decimal(v), Decimal("0"))
            except (InvalidOperation, ValueError):
                return None
        capacity = _int(data.get("capacity"))
        occupied = _int(data.get("occupied"))
        if occupied > capacity:
            return None, "Occupied cannot exceed capacity."
        return {"farm": farm, "shed_name": shed_name, "shed_type": shed_type,
                "is_active": str(data.get("is_active", "true")).lower() in ("true", "1", "on", "yes"),
                "length": _dec(data.get("length")), "width": _dec(data.get("width")),
                "capacity": capacity, "occupied": occupied}, None

    def post(self, request) -> JsonResponse:
        try:
            vals, err = self._clean(request.POST)
            if err:
                return JsonResponse({"error": err}, status=400)
            with transaction.atomic():
                # shed_code, unit_no, organization_centre are auto-set in .save()
                BroilerFarmShed.objects.create(
                    farm=vals["farm"], shed_name=vals["shed_name"],
                    shed_no=vals["shed_name"], shed_type=vals["shed_type"],
                    is_active=vals["is_active"], length=vals["length"],
                    width=vals["width"], capacity=vals["capacity"],
                    occupied=vals["occupied"])
            return JsonResponse({"message": "Shed created"}, status=201)
        except Exception as e:
            return self.handle_exception(e)

    def put(self, request, id: int) -> JsonResponse:
        try:
            s = BroilerFarmShed.objects.get(id=id)
            vals, err = self._clean(json.loads(request.body.decode("utf-8")))
            if err:
                return JsonResponse({"error": err}, status=400)
            with transaction.atomic():
                farm_changed = s.farm_id != vals["farm"].id
                s.farm = vals["farm"]
                s.shed_name = vals["shed_name"]
                s.shed_no = vals["shed_name"]
                s.shed_type = vals["shed_type"]
                s.is_active = vals["is_active"]
                s.length = vals["length"]
                s.width = vals["width"]
                s.capacity = vals["capacity"]
                s.occupied = vals["occupied"]
                if farm_changed:  # re-derive centre for the new farm's branch
                    s.organization_centre = None
                s.save()
            return JsonResponse({"message": "Shed updated"})
        except Exception as e:
            return self.handle_exception(e)

    def delete(self, request, id: int) -> JsonResponse:
        try:
            s = BroilerFarmShed.objects.get(id=id)
            with transaction.atomic():
                s.delete()
            return JsonResponse({"message": "Shed deleted"})
        except Exception as e:
            return self.handle_exception(e)


@method_decorator(login_required, name="dispatch")
class BroilerFarmAPI(BaseAPIView):
    """API endpoints for BroilerFarm operations."""

    FILE_FIELDS = [
        "agreement_copy", "other_documents",
        "cheque_1_file", "cheque_2_file", "cheque_3_file", "cheque_4_file",
    ]
    # farm_code is auto-generated (<branch prefix>-<branch suffix><serial>,
    # e.g. AKB-0203) in BroilerFarm.save() — never accepted from the form.
    FORM_FIELDS = [
        "farm_name", "region", "line", "farm_pincode", "farm_capacity",
        "farm_type", "state", "district", "area", "farm_address", "farm_latitude",
        "farm_longitude", "agreement_start_date", "agreement_end_date", "agreement_months",
        "farm_sqft", "cheque_1_no", "cheque_2_no", "cheque_3_no", "cheque_4_no", "remarks",
    ]

    def get(self, request, id: Optional[int] = None) -> JsonResponse:
        try:
            if id:
                broiler_farm = BroilerFarm.objects.select_related(
                    "branch", "supervisor", "farmer"
                ).prefetch_related("sheds", "images").get(id=id)
                data = {field: getattr(broiler_farm, field) for field in self.FORM_FIELDS}
                data.update({
                    "id": broiler_farm.id,
                    "farm_code": broiler_farm.farm_code,
                    "branch_id": broiler_farm.branch_id,
                    "supervisor_id": broiler_farm.supervisor_id,
                    "farmer_id": broiler_farm.farmer_id,
                    "agreement_start_date": broiler_farm.agreement_start_date.isoformat() if broiler_farm.agreement_start_date else None,
                    "agreement_end_date": broiler_farm.agreement_end_date.isoformat() if broiler_farm.agreement_end_date else None,
                    "sheds": list(broiler_farm.sheds.values(
                        "id", "shed_code", "shed_name", "shed_type",
                        "length", "width", "capacity", "sq_feet")),
                    "images": [{"id": img.id, "url": img.image.url} for img in broiler_farm.images.all()],
                })
                for field in self.FILE_FIELDS:
                    file_obj = getattr(broiler_farm, field)
                    data[field] = file_obj.url if file_obj else None
                return JsonResponse(data)

            cache_key = "broiler_farm_list"
            cached_data = self.get_cached_data(cache_key)
            if cached_data:
                return JsonResponse(cached_data, safe=False)

            broiler_farms = list(
                BroilerFarm.objects.select_related("branch", "supervisor", "farmer")
                .values(
                    "id", "farm_code", "farm_name", "region", "line", "farm_type",
                    "agreement_start_date", "agreement_end_date",
                    branch_name=F("branch__branch_name"),
                    supervisor_name=F("supervisor__name"),
                    farmer_name=F("farmer__farmer_name"),
                )
            )
            self.set_cached_data(cache_key, broiler_farms)
            return JsonResponse(broiler_farms, safe=False)
        except Exception as e:
            return self.handle_exception(e)

    def _save_sheds(self, broiler_farm, sheds_json: str) -> None:
        """Upsert this farm's sheds from the form rows, sharing the Farm Shed
        master's model logic (auto code / unit / name / org-centre / sq-ft /
        status). Existing rows are matched by id so master-only fields (occupied,
        organization centre) are preserved; rows removed from the editor are
        deleted. Non-destructive to sheds the editor still shows."""
        sheds = json.loads(sheds_json) if sheds_json else []
        valid_types = {c[0] for c in BroilerFarmShed.SHED_TYPE_CHOICES}

        def _dec(v):
            v = (str(v) if v is not None else "").strip()
            if not v:
                return None
            try:
                return max(Decimal(v), Decimal("0"))
            except (InvalidOperation, ValueError):
                return None

        def _int(v):
            try:
                return max(int(float(v)), 0)
            except (TypeError, ValueError):
                return 0

        kept_ids = []
        for shed in sheds:
            shed_name = (shed.get("shed_name") or "").strip()
            length, width = _dec(shed.get("length")), _dec(shed.get("width"))
            capacity = _int(shed.get("capacity"))
            shed_type = shed.get("shed_type") or "broiler"
            if shed_type not in valid_types:
                shed_type = "broiler"
            sid = shed.get("id")
            if not sid and not (shed_name or length or width or capacity):
                continue  # skip a blank new row
            obj = broiler_farm.sheds.filter(id=sid).first() if sid else None
            if obj is None:
                obj = BroilerFarmShed(farm=broiler_farm)
            obj.shed_name = shed_name
            obj.shed_type = shed_type
            obj.length, obj.width = length, width
            obj.capacity = capacity
            obj.save()  # auto: shed_code, unit_no, shed_name, org centre, sq_ft, status
            kept_ids.append(obj.id)
        broiler_farm.sheds.exclude(id__in=kept_ids).delete()

    def post(self, request, id: Optional[int] = None) -> JsonResponse:
        try:
            data = request.POST
            with transaction.atomic():
                broiler_farm = BroilerFarm.objects.get(id=id) if id else BroilerFarm()

                broiler_farm.branch = Branch.objects.get(id=data["branch_id"])
                broiler_farm.supervisor = Supervisor.objects.get(id=data["supervisor_id"])
                broiler_farm.farmer = Farmer.objects.get(id=data["farmer_id"])

                for field in self.FORM_FIELDS:
                    if field in data:
                        value = data[field]
                        if value == "" and BroilerFarm._meta.get_field(field).null:
                            value = None
                        setattr(broiler_farm, field, value)

                for field in self.FILE_FIELDS:
                    if field in request.FILES:
                        setattr(broiler_farm, field, request.FILES[field])

                broiler_farm.full_clean(exclude=self.FILE_FIELDS)
                broiler_farm.save()

                self._save_sheds(broiler_farm, data.get("sheds", "[]"))

                for picture in request.FILES.getlist("farm_pictures"):
                    BroilerFarmImage.objects.create(farm=broiler_farm, image=picture)

                cache.delete("broiler_farm_list")
            return JsonResponse(
                {"message": "BroilerFarm updated" if id else "BroilerFarm created", "id": broiler_farm.id},
                status=200 if id else 201,
            )
        except Exception as e:
            return self.handle_exception(e)

    def delete(self, request, id: int) -> JsonResponse:
        try:
            broiler_farm = BroilerFarm.objects.get(id=id)
            with transaction.atomic():
                broiler_farm.delete()
                cache.delete("broiler_farm_list")
            return JsonResponse({"message": "BroilerFarm deleted"})
        except Exception as e:
            return self.handle_exception(e)

@login_required()
def get_supervisors(request) -> JsonResponse:
    """Get supervisors for a specific branch."""
    try:
        branch_id = request.GET.get('branch_id')
        cache_key = f"supervisors_branch_{branch_id}"
        
        cached_data = cache.get(cache_key)
        if cached_data:
            return JsonResponse({'supervisors': cached_data})
        
        supervisors = list(Supervisor.objects.filter(branch_id=branch_id).values('id', 'name'))
        cache.set(cache_key, supervisors, 300)  # Cache for 5 minutes
        return JsonResponse({'supervisors': supervisors})
    except Exception as e:
        logger.error(f"Error in get_supervisors: {str(e)}", exc_info=True)
        return JsonResponse({"error": str(e)}, status=500)



# ---------------------------------------------------------------------------
# Daily Entry (Broiler > Transactions)
# ---------------------------------------------------------------------------

def _daily_entry_to_dict(row):
    return {
        "id": row.id, "date": row.date.isoformat(), "entry_no": row.entry_no,
        "branch_name": row.farm.branch.branch_name, "farm": row.farm_id,
        "farm_name": row.farm.farm_name,
        "batch": row.batch_id, "batch_name": row.batch.batch_name if row.batch_id else "",
        "age_days": row.age_days, "mortality": row.mortality, "culls": row.culls,
        "feed_1": row.feed_1_id, "feed_1_name": row.feed_1.item_code if row.feed_1_id else "",
        "feed_1_qty": str(row.feed_1_qty), "feed_1_stock": str(row.feed_1_stock),
        "feed_2": row.feed_2_id, "feed_2_name": row.feed_2.item_code if row.feed_2_id else "",
        "feed_2_qty": str(row.feed_2_qty), "feed_2_stock": str(row.feed_2_stock),
        "avg_weight_gms": str(row.avg_weight_gms), "remarks": row.remarks,
        "is_active": row.is_batch_active,
        "entry_by": row.entry_by.username if row.entry_by_id else "",
        "entry_time": timezone.localtime(row.entry_time).strftime("%Y-%m-%d %H:%M") if row.entry_time else "",
    }


def _active_batch_for_farm(farm_id):
    return (BroilerBatch.objects.filter(broiler_farm_id=farm_id, end_date__isnull=True)
            .order_by('-start_date', '-id').first()
            or BroilerBatch.objects.filter(broiler_farm_id=farm_id).order_by('-start_date', '-id').first())


def _apply_daily_entry_row(instance, row, entry_date, user, default_farm_id=None):
    # Daily Entry sends farm per row; Single Batch Daily Entry fixes one farm
    # for the whole submission and only varies date/mortality/etc per row —
    # default_farm_id backs a row that omits its own "farm".
    farm_id = row.get("farm") or default_farm_id
    if row.get("date"):
        entry_date = timezone.datetime.fromisoformat(row["date"]).date()
    batch = _active_batch_for_farm(farm_id) if farm_id else None
    instance.date = entry_date
    instance.farm_id = farm_id
    instance.batch = batch
    if batch and batch.start_date:
        # Placement day is Age 0; the first entry day (the day after
        # placement) is Age 1.
        instance.age_days = max((entry_date - batch.start_date).days, 0)
    else:
        instance.age_days = 0
    instance.mortality = int(row.get("mortality") or 0)
    instance.culls = int(row.get("culls") or 0)
    instance.feed_1_id = row.get("feed_1") or None
    instance.feed_1_qty = Decimal(str(row.get("feed_1_qty") or 0))
    instance.feed_2_id = row.get("feed_2") or None
    instance.feed_2_qty = Decimal(str(row.get("feed_2_qty") or 0))
    instance.avg_weight_gms = Decimal(str(row.get("avg_weight_gms") or 0))
    instance.remarks = row.get("remarks") or ""
    if not instance.pk:
        instance.entry_by = user
    prev1 = DailyEntry.previous_stock(farm_id, instance.feed_1_id, entry_date, instance.pk)
    instance.feed_1_stock = Decimal(str(prev1)) - instance.feed_1_qty if instance.feed_1_id else 0
    prev2 = DailyEntry.previous_stock(farm_id, instance.feed_2_id, entry_date, instance.pk)
    instance.feed_2_stock = Decimal(str(prev2)) - instance.feed_2_qty if instance.feed_2_id else 0


def _recompute_stock_chain(farm_id, item_id):
    """Recomputes feed_1_stock/feed_2_stock for every entry of this farm
    that touches item_id, walking chronologically from an opening balance of
    0. Needed after an edit changes a row's date, Kgs, or feed item, since
    every later row's opening balance is the previous row's closing balance
    — without this, only the edited row itself would reflect the change and
    every row after it would silently keep its stale, pre-edit stock."""
    if not farm_id or not item_id:
        return
    qs = (DailyEntry.objects.filter(farm_id=farm_id)
          .filter(Q(feed_1_id=item_id) | Q(feed_2_id=item_id))
          .order_by('date', 'id'))
    running = Decimal('0')
    for r in qs:
        changed = False
        if r.feed_1_id == item_id:
            running -= r.feed_1_qty
            if r.feed_1_stock != running:
                r.feed_1_stock = running
                changed = True
        if r.feed_2_id == item_id:
            running -= r.feed_2_qty
            if r.feed_2_stock != running:
                r.feed_2_stock = running
                changed = True
        if changed:
            r.save(update_fields=["feed_1_stock", "feed_2_stock"])


@method_decorator(login_required, name="dispatch")
class DailyEntryListTemplateView(View):
    def get(self, request):
        return render(request, "daily_entry_list.html", {
            "farms": BroilerFarm.objects.order_by("farm_name"),
            "items": Item.objects.order_by("item_code"),
        })


@method_decorator(login_required, name="dispatch")
class SingleBatchDailyEntryListTemplateView(View):
    def get(self, request):
        return render(request, "daily_entry_single_list.html", {
            "items": Item.objects.order_by("item_code"),
        })


@method_decorator(login_required, name="dispatch")
class SingleBatchDailyEntryFormTemplateView(View):
    def get(self, request):
        return render(request, "daily_entry_single_form.html", {
            "supervisors": Supervisor.objects.order_by("name"),
            "farms": BroilerFarm.objects.select_related("branch").order_by("farm_name"),
            "items": Item.objects.order_by("item_code"),
            "today": timezone.localdate().isoformat(),
        })


@method_decorator(login_required, name="dispatch")
class DailyEntryFormTemplateView(View):
    def get(self, request):
        return render(request, "daily_entry_form.html", {
            "supervisors": Supervisor.objects.order_by("name"),
            "farms": BroilerFarm.objects.select_related("branch").order_by("farm_name"),
            "items": Item.objects.order_by("item_code"),
            "today": timezone.localdate().isoformat(),
        })


@method_decorator(login_required, name="dispatch")
class DailyEntryAPI(BaseAPIView):
    def get(self, request, id: Optional[int] = None) -> JsonResponse:
        try:
            if id:
                row = DailyEntry.objects.select_related("farm__branch", "batch", "feed_1", "feed_2").get(id=id)
                return JsonResponse(_daily_entry_to_dict(row))

            qs = DailyEntry.objects.select_related("farm__branch", "batch", "feed_1", "feed_2")
            from_date = (request.GET.get("from_date") or "").strip()
            to_date = (request.GET.get("to_date") or "").strip()
            status = (request.GET.get("status") or "").strip()
            farm_id = (request.GET.get("farm") or "").strip()
            batch_id = (request.GET.get("batch") or "").strip()
            nobatch_farm_id = (request.GET.get("nobatch_farm") or "").strip()
            if from_date:
                qs = qs.filter(date__gte=from_date)
            if to_date:
                qs = qs.filter(date__lte=to_date)
            if farm_id:
                qs = qs.filter(farm_id=farm_id)
            if batch_id:
                qs = qs.filter(batch_id=batch_id)
            if nobatch_farm_id:
                qs = qs.filter(farm_id=nobatch_farm_id, batch__isnull=True)
            if status == "Active":
                qs = qs.filter(batch__end_date__isnull=True)
            elif status == "Inactive":
                qs = qs.filter(batch__end_date__isnull=False)
            return JsonResponse([_daily_entry_to_dict(r) for r in qs.order_by("-date", "-id")], safe=False)
        except Exception as e:
            return self.handle_exception(e)

    @transaction.atomic
    def post(self, request) -> JsonResponse:
        try:
            data = json.loads(request.body)
            supervisor_id = data.get("supervisor")
            default_farm_id = data.get("farm")  # Single Batch Daily Entry: one farm for the whole submission
            rows = data.get("rows") or []
            if not supervisor_id:
                return JsonResponse({"error": "Supervisor is required"}, status=400)
            if not rows:
                return JsonResponse({"error": "Add at least one entry row"}, status=400)
            entry_date = data.get("date") or timezone.localdate().isoformat()
            created = []
            for row in rows:
                if not (row.get("farm") or default_farm_id):
                    continue
                instance = DailyEntry(supervisor_id=supervisor_id)
                _apply_daily_entry_row(instance, row, timezone.datetime.fromisoformat(entry_date).date(),
                                       request.user, default_farm_id=default_farm_id)
                instance.full_clean(exclude=["entry_no", "batch"])
                instance.save()
                created.append(instance.id)
                # A backdated row can land ahead of already-saved later rows
                # in the chain; recompute so every row's stored stock reflects
                # its true chronological position, not just the ones after it
                # at the moment each was individually inserted.
                _recompute_stock_chain(instance.farm_id, instance.feed_1_id)
                _recompute_stock_chain(instance.farm_id, instance.feed_2_id)
            if not created:
                return JsonResponse({"error": "Add at least one entry row with a Farm selected"}, status=400)
            return JsonResponse({"message": "Daily entries created", "ids": created}, status=201)
        except Exception as e:
            return self.handle_exception(e)

    @transaction.atomic
    def put(self, request, id: int) -> JsonResponse:
        try:
            instance = DailyEntry.objects.get(id=id)
            old_feed_ids = {instance.feed_1_id, instance.feed_2_id}
            data = json.loads(request.body)
            if data.get("supervisor"):
                instance.supervisor_id = data["supervisor"]
            entry_date = instance.date
            if data.get("date"):
                entry_date = timezone.datetime.fromisoformat(data["date"]).date()
            # Farm isn't editable from the edit modal (it's the grouping key),
            # so fall back to the row's existing farm rather than letting a
            # payload without "farm" wipe it out.
            _apply_daily_entry_row(instance, data, entry_date, request.user, default_farm_id=instance.farm_id)
            instance.full_clean(exclude=["entry_no", "batch"])
            instance.save()
            # Editing this row's date/Kgs/feed item invalidates the stored
            # closing stock of every later row chained after it — recompute
            # both the old and new feed items' full chains, not just this row.
            for item_id in old_feed_ids | {instance.feed_1_id, instance.feed_2_id}:
                _recompute_stock_chain(instance.farm_id, item_id)
            return JsonResponse({"message": "Daily entry updated"})
        except DailyEntry.DoesNotExist:
            raise Http404("Daily entry not found")
        except Exception as e:
            return self.handle_exception(e)

    def delete(self, request, id: int) -> JsonResponse:
        try:
            instance = DailyEntry.objects.get(id=id)
            # Deleting a middle entry would leave every later row's stored
            # stock chained off a balance that no longer exists — restrict
            # deletion to the most recent entry in the batch (or, for entries
            # with no batch, the most recent for that farm) so entries can
            # only be removed newest-first, back toward older ones.
            group_filter = ({"batch_id": instance.batch_id} if instance.batch_id
                             else {"farm_id": instance.farm_id, "batch_id": None})
            newer_exists = (DailyEntry.objects.filter(**group_filter).exclude(id=instance.id)
                             .filter(Q(date__gt=instance.date) | (Q(date=instance.date) & Q(id__gt=instance.id)))
                             .exists())
            if newer_exists:
                return JsonResponse(
                    {"error": "Only the most recent entry in this batch can be deleted. Delete newer entries first."},
                    status=400)
            instance.delete()
            return JsonResponse({"message": "Daily entry deleted"})
        except DailyEntry.DoesNotExist:
            raise Http404("Daily entry not found")
        except Exception as e:
            return self.handle_exception(e)


@login_required
def daily_entry_farm_lookup(request):
    """Returns the active batch/age for a farm, for the Add form's
    auto-filled Batch/Age fields as soon as a Farm is picked. ``next_date``
    continues the day after this farm's most recently saved entry (so
    backfilling picks up where it left off), falling back to today when
    there's no prior entry."""
    farm_id = request.GET.get("farm")
    batch = _active_batch_for_farm(farm_id) if farm_id else None
    age_days = 0
    if batch and batch.start_date:
        # Placement day is Age 0; the first entry day (the day after
        # placement) is Age 1.
        age_days = max((timezone.localdate() - batch.start_date).days, 0)

    last_entry = (DailyEntry.objects.filter(farm_id=farm_id).order_by('-date', '-id').first()
                 if farm_id else None)
    next_date = (last_entry.date + timedelta(days=1)) if last_entry else timezone.localdate()

    return JsonResponse({
        "batch": batch.id if batch else None,
        "batch_name": batch.batch_name if batch else "",
        "age_days": age_days,
        "start_date": batch.start_date.isoformat() if batch and batch.start_date else None,
        "next_date": next_date.isoformat(),
    })


@login_required
def daily_entry_stock_lookup(request):
    """Opening stock for a farm+feed item as of a given date — i.e. the
    closing balance of the most recent saved entry before that date (0 if
    none). Used to seed the Add form's live running-stock preview; the grid
    itself then subtracts each row's own Kgs client-side as you type."""
    farm_id = request.GET.get("farm")
    item_id = request.GET.get("item")
    entry_date = request.GET.get("date")
    if not farm_id or not item_id or not entry_date:
        return JsonResponse({"stock": "0"})
    d = timezone.datetime.fromisoformat(entry_date).date()
    stock = DailyEntry.previous_stock(farm_id, int(item_id), d, None)
    return JsonResponse({"stock": str(stock)})


# ---------------------------------------------------------------------------
# Medicine Vaccine Consumption (Broiler > Transactions)
# ---------------------------------------------------------------------------

def _medicine_entry_to_dict(row):
    return {
        "id": row.id, "date": row.date.isoformat(), "entry_no": row.entry_no,
        "branch_name": row.farm.branch.branch_name, "farm": row.farm_id,
        "farm_name": row.farm.farm_name,
        "batch": row.batch_id, "batch_name": row.batch.batch_name if row.batch_id else "",
        "age_days": row.age_days,
        "item": row.item_id, "item_name": row.item.item_code if row.item_id else "",
        "unit": _uom_label(row.item.consumption_uom) if row.item_id else "",
        "qty": str(row.qty), "stock": str(row.stock),
        "remarks": row.remarks,
        "is_active": row.is_batch_active,
        "entry_by": row.entry_by.username if row.entry_by_id else "",
        "entry_time": timezone.localtime(row.entry_time).strftime("%Y-%m-%d %H:%M") if row.entry_time else "",
    }


def _apply_medicine_entry_row(instance, row, entry_date, user):
    farm_id = row.get("farm") or instance.farm_id
    if row.get("date"):
        entry_date = timezone.datetime.fromisoformat(row["date"]).date()
    batch = _active_batch_for_farm(farm_id) if farm_id else None
    instance.date = entry_date
    instance.farm_id = farm_id
    instance.batch = batch
    if batch and batch.start_date:
        # Placement day is Age 0; the first entry day (the day after
        # placement) is Age 1.
        instance.age_days = max((entry_date - batch.start_date).days, 0)
    else:
        instance.age_days = 0
    instance.item_id = row.get("item") or None
    instance.qty = Decimal(str(row.get("qty") or 0))
    instance.remarks = row.get("remarks") or ""
    if not instance.pk:
        instance.entry_by = user
    prev = MedicineVaccineEntry.previous_stock(farm_id, instance.item_id, entry_date, instance.pk)
    instance.stock = Decimal(str(prev)) - instance.qty if instance.item_id else 0


def _recompute_medicine_stock_chain(farm_id, item_id):
    """Recomputes stock for every medicine/vaccine entry of this farm that
    touches item_id, walking chronologically from an opening balance of 0.
    See _recompute_stock_chain (Daily Entry) for the full rationale."""
    if not farm_id or not item_id:
        return
    qs = (MedicineVaccineEntry.objects.filter(farm_id=farm_id, item_id=item_id)
          .order_by('date', 'id'))
    running = Decimal('0')
    for r in qs:
        running -= r.qty
        if r.stock != running:
            r.stock = running
            r.save(update_fields=["stock"])


@method_decorator(login_required, name="dispatch")
class MedicineEntryListTemplateView(View):
    def get(self, request):
        return render(request, "medicine_entry_list.html", {
            "farms": BroilerFarm.objects.order_by("farm_name"),
            "items": Item.objects.order_by("item_code"),
        })


@method_decorator(login_required, name="dispatch")
class MedicineEntryFormTemplateView(View):
    def get(self, request):
        return render(request, "medicine_entry_form.html", {
            "supervisors": Supervisor.objects.order_by("name"),
            "farms": BroilerFarm.objects.select_related("branch").order_by("farm_name"),
            "items": Item.objects.order_by("item_code"),
            "today": timezone.localdate().isoformat(),
        })


@method_decorator(login_required, name="dispatch")
class MedicineEntryAPI(BaseAPIView):
    def get(self, request, id: Optional[int] = None) -> JsonResponse:
        try:
            if id:
                row = MedicineVaccineEntry.objects.select_related("farm__branch", "batch", "item").get(id=id)
                return JsonResponse(_medicine_entry_to_dict(row))

            qs = MedicineVaccineEntry.objects.select_related("farm__branch", "batch", "item")
            from_date = (request.GET.get("from_date") or "").strip()
            to_date = (request.GET.get("to_date") or "").strip()
            status = (request.GET.get("status") or "").strip()
            farm_id = (request.GET.get("farm") or "").strip()
            batch_id = (request.GET.get("batch") or "").strip()
            nobatch_farm_id = (request.GET.get("nobatch_farm") or "").strip()
            if from_date:
                qs = qs.filter(date__gte=from_date)
            if to_date:
                qs = qs.filter(date__lte=to_date)
            if farm_id:
                qs = qs.filter(farm_id=farm_id)
            if batch_id:
                qs = qs.filter(batch_id=batch_id)
            if nobatch_farm_id:
                qs = qs.filter(farm_id=nobatch_farm_id, batch__isnull=True)
            if status == "Active":
                qs = qs.filter(batch__end_date__isnull=True)
            elif status == "Inactive":
                qs = qs.filter(batch__end_date__isnull=False)
            return JsonResponse([_medicine_entry_to_dict(r) for r in qs.order_by("-date", "-id")], safe=False)
        except Exception as e:
            return self.handle_exception(e)

    @transaction.atomic
    def post(self, request) -> JsonResponse:
        try:
            data = json.loads(request.body)
            supervisor_id = data.get("supervisor")
            rows = data.get("rows") or []
            if not supervisor_id:
                return JsonResponse({"error": "Supervisor is required"}, status=400)
            if not rows:
                return JsonResponse({"error": "Add at least one entry row"}, status=400)
            entry_date = data.get("date") or timezone.localdate().isoformat()
            created = []
            for row in rows:
                if not row.get("farm"):
                    continue
                instance = MedicineVaccineEntry(supervisor_id=supervisor_id)
                _apply_medicine_entry_row(instance, row, timezone.datetime.fromisoformat(entry_date).date(), request.user)
                instance.full_clean(exclude=["entry_no", "batch"])
                instance.save()
                created.append(instance.id)
                _recompute_medicine_stock_chain(instance.farm_id, instance.item_id)
            if not created:
                return JsonResponse({"error": "Add at least one entry row with a Farm selected"}, status=400)
            return JsonResponse({"message": "Medicine/Vaccine entries created", "ids": created}, status=201)
        except Exception as e:
            return self.handle_exception(e)

    @transaction.atomic
    def put(self, request, id: int) -> JsonResponse:
        try:
            instance = MedicineVaccineEntry.objects.get(id=id)
            old_item_id = instance.item_id
            data = json.loads(request.body)
            if data.get("supervisor"):
                instance.supervisor_id = data["supervisor"]
            entry_date = instance.date
            if data.get("date"):
                entry_date = timezone.datetime.fromisoformat(data["date"]).date()
            _apply_medicine_entry_row(instance, data, entry_date, request.user)
            instance.full_clean(exclude=["entry_no", "batch"])
            instance.save()
            for item_id in {old_item_id, instance.item_id}:
                _recompute_medicine_stock_chain(instance.farm_id, item_id)
            return JsonResponse({"message": "Medicine/Vaccine entry updated"})
        except MedicineVaccineEntry.DoesNotExist:
            raise Http404("Medicine/Vaccine entry not found")
        except Exception as e:
            return self.handle_exception(e)

    def delete(self, request, id: int) -> JsonResponse:
        try:
            instance = MedicineVaccineEntry.objects.get(id=id)
            # Same tail-only rule as Daily Entry: deleting a middle entry
            # would leave every later row's stored stock chained off a
            # balance that no longer exists.
            group_filter = ({"batch_id": instance.batch_id} if instance.batch_id
                             else {"farm_id": instance.farm_id, "batch_id": None})
            newer_exists = (MedicineVaccineEntry.objects.filter(**group_filter).exclude(id=instance.id)
                             .filter(Q(date__gt=instance.date) | (Q(date=instance.date) & Q(id__gt=instance.id)))
                             .exists())
            if newer_exists:
                return JsonResponse(
                    {"error": "Only the most recent entry in this batch can be deleted. Delete newer entries first."},
                    status=400)
            instance.delete()
            return JsonResponse({"message": "Medicine/Vaccine entry deleted"})
        except MedicineVaccineEntry.DoesNotExist:
            raise Http404("Medicine/Vaccine entry not found")
        except Exception as e:
            return self.handle_exception(e)


@login_required
def medicine_entry_farm_lookup(request):
    """Returns the active batch/age for a farm, for the Add form's
    auto-filled Batch/Age fields as soon as a Farm is picked."""
    farm_id = request.GET.get("farm")
    batch = _active_batch_for_farm(farm_id) if farm_id else None
    age_days = 0
    if batch and batch.start_date:
        age_days = max((timezone.localdate() - batch.start_date).days, 0)
    return JsonResponse({
        "batch": batch.id if batch else None,
        "batch_name": batch.batch_name if batch else "",
        "age_days": age_days,
        "start_date": batch.start_date.isoformat() if batch and batch.start_date else None,
    })


@login_required
def medicine_entry_item_lookup(request):
    """Unit (consumption UOM) for a selected Medicine/Vaccine item, for the
    Add form's auto-filled Unit field."""
    item_id = request.GET.get("item")
    item = Item.objects.filter(id=item_id).first() if item_id else None
    return JsonResponse({"unit": _uom_label(item.consumption_uom) if item else ""})


@login_required
def medicine_entry_stock_lookup(request):
    """Opening stock for a farm+item as of a given date — the closing
    balance of the most recent saved entry before that date (0 if none)."""
    farm_id = request.GET.get("farm")
    item_id = request.GET.get("item")
    entry_date = request.GET.get("date")
    if not farm_id or not item_id or not entry_date:
        return JsonResponse({"stock": "0"})
    d = timezone.datetime.fromisoformat(entry_date).date()
    stock = MedicineVaccineEntry.previous_stock(farm_id, int(item_id), d, None)
    return JsonResponse({"stock": str(stock)})


@login_required
def daily_entry_group_delete(request):
    """Bulk-deletes every Daily Entry / Single Batch Daily Entry row for one
    batch (or, for entries with no active batch, one farm) at once — the
    register's group-level Delete action. Safe to do in one shot regardless
    of the tail-only rule on individual deletes, since wiping the whole
    group at once leaves no later row anywhere still chained to it."""
    if request.method != "DELETE":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    batch_id = (request.GET.get("batch") or "").strip()
    farm_id = (request.GET.get("farm") or "").strip()
    if batch_id:
        qs = DailyEntry.objects.filter(batch_id=batch_id)
    elif farm_id:
        qs = DailyEntry.objects.filter(farm_id=farm_id, batch__isnull=True)
    else:
        return JsonResponse({"error": "batch or farm is required"}, status=400)
    count = qs.count()
    if not count:
        return JsonResponse({"error": "No entries found for this batch"}, status=404)
    qs.delete()
    return JsonResponse({"message": f"Deleted {count} entries"})


@login_required
def medicine_entry_group_delete(request):
    """Bulk-deletes every Medicine Vaccine Consumption row for one batch (or,
    for entries with no active batch, one farm) at once. See
    daily_entry_group_delete for the rationale."""
    if request.method != "DELETE":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    batch_id = (request.GET.get("batch") or "").strip()
    farm_id = (request.GET.get("farm") or "").strip()
    if batch_id:
        qs = MedicineVaccineEntry.objects.filter(batch_id=batch_id)
    elif farm_id:
        qs = MedicineVaccineEntry.objects.filter(farm_id=farm_id, batch__isnull=True)
    else:
        return JsonResponse({"error": "batch or farm is required"}, status=400)
    count = qs.count()
    if not count:
        return JsonResponse({"error": "No entries found for this batch"}, status=404)
    qs.delete()
    return JsonResponse({"message": f"Deleted {count} entries"})


# ---------------------------------------------------------------------------
# Bird Sale (Broiler > Transactions)
# ---------------------------------------------------------------------------

def _bird_sale_to_dict(row):
    buyer_name = row.customer.name if row.customer_id else (row.farmer.farmer_name if row.farmer_id else "")
    return {
        "id": row.id, "sale_no": row.sale_no, "date": row.date.isoformat(), "doc_no": row.doc_no,
        "sale_type": row.sale_type,
        "customer": row.customer_id, "customer_name": row.customer.name if row.customer_id else "",
        "farmer": row.farmer_id, "farmer_name": row.farmer.farmer_name if row.farmer_id else "",
        "buyer_name": buyer_name,
        "farm": row.farm_id, "farm_name": row.farm.farm_name,
        "batch": row.batch_id, "batch_name": row.batch.batch_name if row.batch_id else "",
        "birds": row.birds, "net_weight": str(row.net_weight), "avg_weight": str(row.avg_weight),
        "rate": str(row.rate), "round_off": str(row.round_off), "amount": str(row.amount),
        "lifting_supervisor": row.lifting_supervisor_id,
        "lifting_supervisor_name": row.lifting_supervisor.name if row.lifting_supervisor_id else "",
        "vehicle": row.vehicle, "driver": row.driver, "remarks": row.remarks,
    }


def _apply_bird_sale(instance, data):
    if data.get("date"):
        instance.date = timezone.datetime.fromisoformat(data["date"]).date()
    instance.doc_no = data.get("doc_no") or ""
    sale_type = data.get("sale_type") or "customer"
    instance.sale_type = sale_type
    farm_id = data.get("farm") or None
    instance.farm_id = farm_id
    instance.batch = _active_batch_for_farm(farm_id) if farm_id else None
    if sale_type == "customer":
        instance.customer_id = data.get("customer") or None
        instance.farmer_id = None
    else:
        # A Farmer Sale is always the same farmer who grew these birds on
        # this farm (buying their own birds back) — never a free pick from
        # the whole Farmer list, so it's derived from the farm, not the
        # client payload.
        instance.customer_id = None
        farm = BroilerFarm.objects.filter(id=farm_id).first() if farm_id else None
        instance.farmer_id = farm.farmer_id if farm else None
    instance.birds = int(data.get("birds") or 0)
    instance.net_weight = Decimal(str(data.get("net_weight") or 0))
    instance.rate = Decimal(str(data.get("rate") or 0))
    instance.round_off = Decimal(str(data.get("round_off") or 0))
    instance.lifting_supervisor_id = data.get("lifting_supervisor") or None
    instance.vehicle = data.get("vehicle") or ""
    instance.driver = data.get("driver") or ""
    instance.remarks = data.get("remarks") or ""


@method_decorator(login_required, name="dispatch")
class BirdSaleListTemplateView(View):
    def get(self, request):
        return render(request, "bird_sale_list.html")


@method_decorator(login_required, name="dispatch")
class BirdSaleFormTemplateView(View):
    def get(self, request, id=None):
        return render(request, "bird_sale_form.html", {
            "instance": BirdSale.objects.filter(id=id).first() if id else None,
            "farms": BroilerFarm.objects.order_by("farm_name"),
            "customers": Customer.objects.order_by("name"),
            "farmers": Farmer.objects.order_by("farmer_name"),
            "supervisors": Supervisor.objects.order_by("name"),
            "today": timezone.localdate().isoformat(),
        })


@method_decorator(login_required, name="dispatch")
class BirdSaleAPI(BaseAPIView):
    def get(self, request, id: Optional[int] = None) -> JsonResponse:
        try:
            if id:
                row = BirdSale.objects.select_related(
                    "customer", "farmer", "farm", "batch", "lifting_supervisor").get(id=id)
                return JsonResponse(_bird_sale_to_dict(row))

            qs = BirdSale.objects.select_related("customer", "farmer", "farm", "batch", "lifting_supervisor")
            from_date = (request.GET.get("from_date") or "").strip()
            to_date = (request.GET.get("to_date") or "").strip()
            if from_date:
                qs = qs.filter(date__gte=from_date)
            if to_date:
                qs = qs.filter(date__lte=to_date)
            return JsonResponse([_bird_sale_to_dict(r) for r in qs.order_by("-date", "-id")], safe=False)
        except BirdSale.DoesNotExist:
            raise Http404("Bird sale not found")
        except Exception as e:
            return self.handle_exception(e)

    @transaction.atomic
    def post(self, request) -> JsonResponse:
        try:
            data = json.loads(request.body or "{}")
            rows = data.get("rows") or []
            if not rows:
                return JsonResponse({"error": "Add at least one sale row"}, status=400)
            created = []
            for row in rows:
                if not row.get("farm"):
                    continue
                instance = BirdSale(entry_by=request.user)
                _apply_bird_sale(instance, row)
                instance.full_clean(exclude=["sale_no", "batch"])
                instance.save()
                created.append(instance.id)
            if not created:
                return JsonResponse({"error": "Add at least one sale row with a Farm selected"}, status=400)
            return JsonResponse({"message": "Bird sale(s) created", "ids": created}, status=201)
        except Exception as e:
            return self.handle_exception(e)

    @transaction.atomic
    def put(self, request, id: int) -> JsonResponse:
        try:
            instance = BirdSale.objects.get(id=id)
            data = json.loads(request.body or "{}")
            _apply_bird_sale(instance, data)
            instance.full_clean(exclude=["sale_no", "batch"])
            instance.save()
            return JsonResponse({"message": "Bird sale updated"})
        except BirdSale.DoesNotExist:
            raise Http404("Bird sale not found")
        except Exception as e:
            return self.handle_exception(e)

    def delete(self, request, id: int) -> JsonResponse:
        try:
            instance = BirdSale.objects.get(id=id)
            instance.delete()
            return JsonResponse({"message": "Bird sale deleted"})
        except BirdSale.DoesNotExist:
            raise Http404("Bird sale not found")
        except Exception as e:
            return self.handle_exception(e)


@login_required
def bird_sale_farm_lookup(request):
    """Returns the active batch and owning farmer for a farm, for the Add
    form's auto-filled Batch field and Farmer Sale buyer (always the same
    farmer who grew the birds on this farm) as soon as a Farm is picked."""
    farm_id = request.GET.get("farm")
    batch = _active_batch_for_farm(farm_id) if farm_id else None
    farm = BroilerFarm.objects.filter(id=farm_id).select_related("farmer").first() if farm_id else None
    return JsonResponse({
        "batch": batch.id if batch else None,
        "batch_name": batch.batch_name if batch else "",
        "farmer": farm.farmer_id if farm else None,
        "farmer_name": farm.farmer.farmer_name if farm and farm.farmer_id else "",
    })


# ---------------------------------------------------------------------------
# Bird Sale Receipt (Broiler > Transactions)
# ---------------------------------------------------------------------------

def _bird_sale_receipt_to_dict(row):
    buyer_name = row.customer.name if row.customer_id else (row.farmer.farmer_name if row.farmer_id else "")
    return {
        "id": row.id, "receipt_no": row.receipt_no, "date": row.date.isoformat(),
        "location": row.location_id, "location_name": row.location.name,
        "sale_type": row.sale_type,
        "customer": row.customer_id, "customer_name": row.customer.name if row.customer_id else "",
        "farmer": row.farmer_id, "farmer_name": row.farmer.farmer_name if row.farmer_id else "",
        "buyer_name": buyer_name,
        "mode": row.mode,
        "receipt_account": row.receipt_account_id,
        "receipt_account_name": (f"{row.receipt_account.code} - {row.receipt_account.description}"
                                 if row.receipt_account_id else ""),
        "amount": str(row.amount), "reference_no": row.reference_no, "remarks": row.remarks,
    }


def _apply_bird_sale_receipt(instance, data):
    if data.get("date"):
        instance.date = timezone.datetime.fromisoformat(data["date"]).date()
    instance.location_id = data.get("location") or None
    sale_type = data.get("sale_type") or "customer"
    instance.sale_type = sale_type
    if sale_type == "customer":
        instance.customer_id = data.get("customer") or None
        instance.farmer_id = None
    else:
        instance.customer_id = None
        instance.farmer_id = data.get("farmer") or None
    instance.mode = data.get("mode") or "Cash"
    instance.receipt_account_id = data.get("receipt_account") or None
    instance.amount = Decimal(str(data.get("amount") or 0))
    instance.reference_no = data.get("reference_no") or ""
    instance.remarks = data.get("remarks") or ""


@method_decorator(login_required, name="dispatch")
class BirdSaleReceiptListTemplateView(View):
    def get(self, request):
        return render(request, "bird_sale_receipt_list.html")


@method_decorator(login_required, name="dispatch")
class BirdSaleReceiptFormTemplateView(View):
    def get(self, request, id=None):
        return render(request, "bird_sale_receipt_form.html", {
            "instance": BirdSaleReceipt.objects.filter(id=id).first() if id else None,
            "locations": Warehouse.objects.order_by("name"),
            "customers": Customer.objects.order_by("name"),
            "farmers": Farmer.objects.order_by("farmer_name"),
            "accounts": ChartOfAccount.objects.order_by("code"),
            "today": timezone.localdate().isoformat(),
        })


@method_decorator(login_required, name="dispatch")
class BirdSaleReceiptAPI(BaseAPIView):
    def get(self, request, id: Optional[int] = None) -> JsonResponse:
        try:
            if id:
                row = BirdSaleReceipt.objects.select_related(
                    "customer", "farmer", "location", "receipt_account").get(id=id)
                return JsonResponse(_bird_sale_receipt_to_dict(row))

            qs = BirdSaleReceipt.objects.select_related("customer", "farmer", "location", "receipt_account")
            from_date = (request.GET.get("from_date") or "").strip()
            to_date = (request.GET.get("to_date") or "").strip()
            if from_date:
                qs = qs.filter(date__gte=from_date)
            if to_date:
                qs = qs.filter(date__lte=to_date)
            return JsonResponse([_bird_sale_receipt_to_dict(r) for r in qs.order_by("-date", "-id")], safe=False)
        except BirdSaleReceipt.DoesNotExist:
            raise Http404("Receipt not found")
        except Exception as e:
            return self.handle_exception(e)

    @transaction.atomic
    def post(self, request) -> JsonResponse:
        try:
            data = json.loads(request.body or "{}")
            rows = data.get("rows") or []
            if not rows:
                return JsonResponse({"error": "Add at least one receipt row"}, status=400)
            created = []
            for row in rows:
                if not row.get("location"):
                    continue
                instance = BirdSaleReceipt(entry_by=request.user)
                _apply_bird_sale_receipt(instance, row)
                instance.full_clean(exclude=["receipt_no"])
                instance.save()
                created.append(instance.id)
            if not created:
                return JsonResponse({"error": "Add at least one receipt row with a Location selected"}, status=400)
            return JsonResponse({"message": "Receipt(s) created", "ids": created}, status=201)
        except Exception as e:
            return self.handle_exception(e)

    @transaction.atomic
    def put(self, request, id: int) -> JsonResponse:
        try:
            instance = BirdSaleReceipt.objects.get(id=id)
            data = json.loads(request.body or "{}")
            _apply_bird_sale_receipt(instance, data)
            instance.full_clean(exclude=["receipt_no"])
            instance.save()
            return JsonResponse({"message": "Receipt updated"})
        except BirdSaleReceipt.DoesNotExist:
            raise Http404("Receipt not found")
        except Exception as e:
            return self.handle_exception(e)

    def delete(self, request, id: int) -> JsonResponse:
        try:
            instance = BirdSaleReceipt.objects.get(id=id)
            instance.delete()
            return JsonResponse({"message": "Receipt deleted"})
        except BirdSaleReceipt.DoesNotExist:
            raise Http404("Receipt not found")
        except Exception as e:
            return self.handle_exception(e)


@login_required
def bird_sale_receipt_balance_lookup(request):
    """Outstanding balance for a Customer/Farmer at a cost centre (rolled up
    across every Farm sharing that Location's Branch), for the Add form's
    auto-filled Balance field as soon as Location and Customer/Farmer are
    picked."""
    location_id = request.GET.get("location")
    sale_type = request.GET.get("sale_type") or "customer"
    customer_id = request.GET.get("customer")
    farmer_id = request.GET.get("farmer")
    exclude_id = request.GET.get("exclude_id")
    balance = BirdSaleReceipt.balance_due(location_id, sale_type, customer_id, farmer_id, exclude_id=exclude_id)
    return JsonResponse({"balance": str(balance)})


# ---------------------------------------------------------------------------
# Batch History Report (Broiler > Reports)
# ---------------------------------------------------------------------------

def _transfer_location_name(header):
    if header.from_warehouse_id:
        return header.from_warehouse.name
    if header.from_farm_id:
        return header.from_farm.farm_name
    return ""


def _transfer_to_location_name(header):
    if header.to_warehouse_id:
        return header.to_warehouse.name
    if header.to_farm_id:
        return header.to_farm.farm_name
    return ""


def _div(numerator, denominator):
    """Safe division returning Decimal('0') when the denominator is zero/None."""
    n = Decimal(str(numerator or 0))
    d = Decimal(str(denominator or 0))
    return (n / d) if d else Decimal("0")


def _match_growing_charge_scheme(batch, on_date):
    """The GrowingChargeScheme whose master-defined date range covers the
    placement date, for this batch's region — branch-specific preferred over
    an all-branches scheme. Returns None when no scheme covers the date (the
    caller then shows 'No Data' for scheme-driven cost/price figures). Never
    falls back to a scheme outside the date range or another branch."""
    if not on_date:
        return None
    branch = batch.broiler_farm.branch
    qs = GrowingChargeScheme.objects.filter(
        region_id=branch.region_id, is_active=True,
        from_date__lte=on_date, to_date__gte=on_date,
    )
    return (qs.filter(branch=branch).order_by("-from_date").first()
            or qs.filter(branch__isnull=True).order_by("-from_date").first())


def _build_batch_costing(batch, placement_total, cum_mortality, cum_culls, mortality_rows,
                         chick_rows, feed_rows, feed_summary_rows, feed_return_rows,
                         medicine_transfer_rows, medicine_consumption_rows, medicine_return_rows,
                         bird_sale_rows, fetch_type="farmer", scheme_override=None):
    """Batch Costing Information and Summary block of the Growing Charge
    Statement — bird/feed/weight KPIs plus the cost roll-up. Cost drivers
    (Admin Cost, Grade) come from the batch's applicable GrowingChargeScheme
    (or ``scheme_override`` when a Schema is hand-picked in the filter bar).

    ``fetch_type`` chooses the statement perspective: 'farmer' bills only the
    farmer's admin share, 'management' bills the full admin cost."""
    q2, q3 = Decimal("0.01"), Decimal("0.001")

    # --- dates ---
    placement_date = min((r["date"] for r in chick_rows), default=None) or batch.start_date
    sale_start_date = min((r["date"] for r in bird_sale_rows), default=None)

    # --- birds ---
    sold_birds = sum(r["birds"] for r in bird_sale_rows)
    sold_weight = sum((r["net_weight"] or 0) for r in bird_sale_rows)
    sold_amount = sum((r["amount"] or 0) for r in bird_sale_rows)
    shortage_birds = 0  # not tracked in this system
    excess_birds = placement_total - cum_mortality - cum_culls - sold_birds - shortage_birds

    # --- mortality % (denominator = chicks placed) ---
    mort_upto_7 = mort_upto_30 = 0
    for r in mortality_rows:
        if r["age"] <= 7:
            mort_upto_7 = r["cum_mortality"]
        if r["age"] <= 30:
            mort_upto_30 = r["cum_mortality"]
    first_week_mort_pct = _div(mort_upto_7 * 100, placement_total)
    upto_30_mort_pct = _div(mort_upto_30 * 100, placement_total)
    after_30_mort_pct = _div((cum_mortality - mort_upto_30) * 100, placement_total)
    total_mort_pct = _div(cum_mortality * 100, placement_total)

    # --- weights / age ---
    avg_body_weight = _div(sold_weight, sold_birds).quantize(q2)        # kg
    weighted_age = sum(
        ((r["date"] - placement_date).days + 1) * r["birds"]
        for r in bird_sale_rows) if placement_date else 0
    mean_age = _div(weighted_age, sold_birds).quantize(q2)
    day_gain = _div(avg_body_weight * 1000, mean_age)                   # g/day (avg wt in g / mean age)

    # --- feed ---
    feed_in_kg = sum((r["quantity"] or 0) for r in feed_rows)
    feed_in_amount = sum((r["amount"] or 0) for r in feed_rows)
    avg_feed_rate = _div(feed_in_amount, feed_in_kg)
    feed_consumed = sum((r["consumed"] or 0) for r in feed_summary_rows)
    feed_return_kg = sum((r["quantity"] or 0) for r in feed_return_rows)
    feed_cost = feed_consumed * avg_feed_rate

    # --- medicine / vaccine ---
    med_in_qty = sum((r["quantity"] or 0) for r in medicine_transfer_rows)
    med_in_amount = sum((r["amount"] or 0) for r in medicine_transfer_rows)
    med_consumed = sum((r["quantity"] or 0) for r in medicine_consumption_rows)
    med_return_qty = sum((r["quantity"] or 0) for r in medicine_return_rows)
    med_cost = med_consumed * _div(med_in_amount, med_in_qty)

    # --- FCR / CFCR / Livability / EEF (per client KPI definitions) ---
    # Mortality Weight = weight of birds that died, from each day's mortality
    # valued at that day's average body weight (early deaths weigh less).
    mortality_weight = sum(
        (Decimal(str(r["mortality"])) * Decimal(str(r["avg_weight_kg"])) for r in mortality_rows),
        Decimal("0"),
    )
    fcr = _div(feed_consumed, sold_weight)                              # Feed / Live Weight
    cfcr = _div(feed_consumed, sold_weight + mortality_weight)          # Feed / (Live Wt + Mortality Wt)
    livability_pct = _div(sold_birds * 100, placement_total)           # (Birds Sold / Chicks Placed) x 100
    eef = _div(livability_pct * avg_body_weight * 100, mean_age * fcr)  # (Livability x Avg Wt x 100) / (Age x FCR)

    # --- costs from the applicable Growing Charge Scheme ---
    scheme = scheme_override or _match_growing_charge_scheme(batch, placement_date)
    chick_cost = sum((r["amount"] or 0) for r in chick_rows)
    if scheme:
        farmer_rate = scheme.farmer_admin_cost or 0
        mgmt_rate = scheme.management_admin_cost or 0
        # Farmer report bills only the farmer's admin share; Management report
        # bills the full admin cost (farmer + management).
        admin_rate = farmer_rate if fetch_type == "farmer" else (farmer_rate + mgmt_rate)
        admin_cost = admin_rate * placement_total
    else:
        admin_cost = Decimal("0")
    total_production_cost = feed_cost + chick_cost + med_cost + admin_cost
    production_cost_per_kg = _div(total_production_cost, sold_weight)

    # Cost Distribution donut (dashboard widget) — captured as plain floats
    # BEFORE the "no scheme -> No Data" string override below, so the chart
    # always has real numbers (admin_cost is simply 0 without a scheme).
    cost_breakdown = {
        "feed_cost": float(feed_cost.quantize(q2)),
        "chick_cost": float(Decimal(str(chick_cost)).quantize(q2)),
        "med_cost": float(med_cost.quantize(q2)),
        "admin_cost": float(admin_cost.quantize(q2)),
    }
    _cb_total = sum(cost_breakdown.values())
    cost_breakdown["total"] = round(_cb_total, 2)
    for _k in ("feed_cost", "chick_cost", "med_cost", "admin_cost"):
        cost_breakdown[f"{_k}_pct"] = round(cost_breakdown[_k] / _cb_total * 100, 1) if _cb_total else 0

    # Performance Overview (dashboard widget) — actual vs the Growing Charge
    # Master's standard rates, for the 3 metrics the master actually defines
    # a target for (standard_fcr, standard_mortality, std_production_cost).
    # Avg Live Weight / Feed-per-Bird / CFCR have no master-defined target in
    # this system, so they're deliberately left off rather than inventing one.
    def _perf_status(actual, target):
        if not target:
            return "No Target"
        actual, target = Decimal(str(actual)), Decimal(str(target))
        if actual <= target:
            return "Good"
        if actual <= target * Decimal("1.05"):
            return "Medium"
        return "High"

    performance_overview = [
        {"kpi": "Mortality %", "actual": total_mort_pct.quantize(q2),
         "target": scheme.standard_mortality if scheme else None,
         "status": _perf_status(total_mort_pct, scheme.standard_mortality if scheme else None)},
        {"kpi": "FCR", "actual": fcr.quantize(q2),
         "target": scheme.standard_fcr if scheme else None,
         "status": _perf_status(fcr, scheme.standard_fcr if scheme else None)},
        {"kpi": "Production Cost / Kg", "actual": production_cost_per_kg.quantize(q2),
         "target": scheme.std_production_cost if scheme else None,
         "status": _perf_status(production_cost_per_kg, scheme.std_production_cost if scheme else None)},
    ]

    # --- Grade: Farmer-Classification band matched on production cost/kg ---
    grade = ""
    if scheme:
        for fc in scheme.farmer_classifications.all():
            if fc.production_cost_from <= production_cost_per_kg <= fc.production_to:
                grade = fc.grade
                break

    # --- Financials (Management view) ---
    revenue = Decimal(str(sold_amount))
    gross_profit = revenue - total_production_cost
    # No overhead ledger (labour/electricity/fuel/...) exists, so Net == Gross here.
    net_profit = gross_profit
    prod_cost_per_bird = _div(total_production_cost, placement_total)
    margin_per_bird = _div(gross_profit, sold_birds)
    margin_per_kg = _div(gross_profit, sold_weight)
    roi = _div(gross_profit * 100, total_production_cost)

    # --- Standard rates from the Growing Charge Master (settlement basis;
    #     NEVER actual company purchase costs) ---
    _weight = Decimal(str(sold_weight))
    std_chick_rate = Decimal(str(scheme.chick_cost)) if scheme else Decimal("0")
    std_feed_rate = Decimal(str(scheme.feed_cost)) if scheme else Decimal("0")
    std_med_rate = Decimal(str(scheme.medicine_cost)) if scheme else Decimal("0")
    std_prod_per_kg = Decimal(str(scheme.std_production_cost)) if scheme else Decimal("0")
    base_gc_rate = Decimal(str(scheme.standard_gc_cost)) if scheme else Decimal("0")
    base_gc_amount = base_gc_rate * _weight
    std_prod_total = std_prod_per_kg * _weight
    prod_cost_variance_kg = std_prod_per_kg - production_cost_per_kg
    prod_cost_variance_total = std_prod_total - total_production_cost

    data = {
        "revenue": revenue.quantize(q2),
        "gross_profit": gross_profit.quantize(q2),
        "net_profit": net_profit.quantize(q2),
        "prod_cost_per_bird": prod_cost_per_bird.quantize(q2),
        "margin_per_bird": margin_per_bird.quantize(q2),
        "margin_per_kg": margin_per_kg.quantize(q2),
        "roi": roi.quantize(q2),
        "std_chick_rate": std_chick_rate.quantize(q2),
        "std_feed_rate": std_feed_rate.quantize(q2),
        "std_med_rate": std_med_rate.quantize(q2),
        "std_prod_per_kg": std_prod_per_kg.quantize(q2),
        "base_gc_rate": base_gc_rate.quantize(q2),
        "base_gc_amount": base_gc_amount.quantize(q2),
        "std_prod_total": std_prod_total.quantize(q2),
        "prod_cost_variance_kg": prod_cost_variance_kg.quantize(q2),
        "prod_cost_variance_total": prod_cost_variance_total.quantize(q2),
        "has_scheme": bool(scheme),
        "placement_date": placement_date,
        "sale_start_date": sale_start_date,
        "chicks_placed": placement_total,
        "mortality": cum_mortality,
        "culls": cum_culls,
        "excess_birds": excess_birds,
        "shortage_birds": shortage_birds,
        "grade": grade,
        "first_week_mort_pct": first_week_mort_pct.quantize(q2),
        "upto_30_mort_pct": upto_30_mort_pct.quantize(q2),
        "after_30_mort_pct": after_30_mort_pct.quantize(q2),
        "total_mort_pct": total_mort_pct.quantize(q2),
        "avg_body_weight": avg_body_weight.quantize(q2),
        "mean_age": mean_age.quantize(q2),
        "day_gain": day_gain.quantize(q2),
        "fcr": fcr.quantize(q2),
        "cfcr": cfcr.quantize(q2),
        "livability_pct": livability_pct.quantize(q2),
        "mortality_weight": mortality_weight.quantize(q2),
        "eef": eef.quantize(q2),
        "sold_birds": sold_birds,
        "sold_weight": Decimal(str(sold_weight)).quantize(q2),
        "sold_amount": Decimal(str(sold_amount)).quantize(q2),
        "avg_sale_rate": _div(sold_amount, sold_weight).quantize(q2),
        "feed_sent": Decimal(str(feed_in_kg)).quantize(q2),
        "feed_consumed": Decimal(str(feed_consumed)).quantize(q2),
        "feed_return": Decimal(str(feed_return_kg)).quantize(q2),
        "feed_cost": feed_cost.quantize(q2),
        "chick_cost": Decimal(str(chick_cost)).quantize(q2),
        "med_sent": Decimal(str(med_in_qty)).quantize(q2),
        "med_consumed": Decimal(str(med_consumed)).quantize(q2),
        "med_return": Decimal(str(med_return_qty)).quantize(q2),
        "med_cost": med_cost.quantize(q2),
        "admin_cost": admin_cost.quantize(q2),
        "total_production_cost": total_production_cost.quantize(q2),
        "production_cost_per_kg": production_cost_per_kg.quantize(q2),
        "scheme_code": scheme.scheme_code if scheme else "",
        "cost_breakdown": cost_breakdown,
        "performance_overview": performance_overview,
        "mortality_status": performance_overview[0]["status"],
        "fcr_status": performance_overview[1]["status"],
        "cost_status": performance_overview[2]["status"],
    }

    # No Growing Charge Scheme covers the placement date -> the scheme-driven
    # cost/settlement/variance figures are undefined; show "No Data" for them
    # (operational + performance figures still show real values).
    if not scheme:
        for key in ("admin_cost", "grade", "total_production_cost", "production_cost_per_kg",
                    "prod_cost_per_bird", "gross_profit", "net_profit", "margin_per_bird",
                    "margin_per_kg", "roi", "std_chick_rate", "std_feed_rate", "std_med_rate",
                    "std_prod_per_kg", "base_gc_rate", "base_gc_amount", "std_prod_total",
                    "prod_cost_variance_kg", "prod_cost_variance_total"):
            data[key] = "No Data"
    return data


def _build_batch_report(batch, fetch_type="farmer", scheme_override=None):
    from inventory.models import StockTransfer, MedicineTransfer, Mapping
    from purchase.models import GeneralPurchaseItem

    # Feed Purchase: purchases have no batch/farm FK at all, only a
    # Warehouse — sometimes that Warehouse directly *is* the farm's own
    # cost centre (feed bought straight to the farm), sometimes it's a
    # general warehouse the feed reaches the farm from later via a Stock
    # Transfer (already captured as Feed Transfer-In). Either way it's
    # booked to a Warehouse sharing this farm's Branch, so — like Bird Sale
    # Receipt's balance — it's rolled up at the Branch level, bounded to
    # this batch's growing window, rather than claimed to be exact-to-batch.
    # start_date/end_date are both nullable (the Batch form sets neither),
    # so each bound is applied only when it exists — an unbounded batch
    # simply shows every purchase at the branch.
    # A Warehouse (Office) no longer has a direct Branch FK — its Branch is
    # resolved through inventory.Mapping (TYPE_SECTOR_BRANCH: from_id=office,
    # to_id=branch), so we first gather the offices mapped to this branch.
    branch_id = batch.broiler_farm.branch_id
    branch_office_ids = list(
        Mapping.objects.filter(type=Mapping.TYPE_SECTOR_BRANCH, to_id=branch_id)
        .values_list("from_id", flat=True)
    )
    purchase_items = GeneralPurchaseItem.objects.filter(farm_warehouse_id__in=branch_office_ids)
    if batch.start_date:
        purchase_items = purchase_items.filter(purchase__date__gte=batch.start_date)
    if batch.end_date:
        purchase_items = purchase_items.filter(purchase__date__lte=batch.end_date)
    purchase_items = (purchase_items
                      .select_related("purchase", "item__category", "farm_warehouse")
                      .order_by("purchase__date", "id"))
    feed_purchase_rows = []
    for pi in purchase_items:
        category_name = pi.item.category.name if pi.item.category_id else ""
        if "chick" in category_name.lower():
            continue
        feed_purchase_rows.append({
            "date": pi.purchase.date, "trnum": pi.purchase.purchase_no, "dc_no": pi.purchase.dc_no,
            "from_location": pi.farm_warehouse.name, "item": str(pi.item),
            "quantity": pi.rcv_qty, "rate": pi.rate, "amount": pi.amount,
        })

    transfers = (StockTransfer.objects.filter(to_batch=batch)
                 .select_related("item__category", "from_warehouse", "from_farm")
                 .order_by("date", "id"))
    chick_rows, feed_rows = [], []
    feed_cum = Decimal("0")
    for t in transfers:
        row = {
            "date": t.date, "trnum": t.trnum, "dc_no": t.dc_no,
            "from_location": _transfer_location_name(t),
            "item": str(t.item), "quantity": t.quantity, "rate": t.rate,
            "amount": (t.quantity or 0) * (t.rate or 0),
        }
        category_name = t.item.category.name if t.item.category_id else ""
        # Chick-placement transfers are ordinary Stock Transfers of a
        # "chicks" item; everything else transferred to a batch is treated
        # as feed (this model has no dedicated chick-placement transaction).
        if "chick" in category_name.lower():
            chick_rows.append(row)
        else:
            feed_cum += row["quantity"] or 0
            row["cumulative"] = feed_cum
            feed_rows.append(row)

    med_transfers = (MedicineTransfer.objects.filter(to_batch=batch)
                     .prefetch_related("items__item").select_related("from_warehouse", "from_farm")
                     .order_by("date", "id"))
    medicine_transfer_rows = []
    for mt in med_transfers:
        location_name = _transfer_location_name(mt)
        for line in mt.items.all():
            medicine_transfer_rows.append({
                "date": mt.date, "trnum": mt.trnum, "dc_no": mt.dc_no,
                "from_location": location_name, "item": str(line.item),
                "quantity": line.quantity, "rate": line.rate,
                "amount": (line.quantity or 0) * (line.rate or 0),
            })

    # Feed/Medicine Return and Transfer-to-Other-Farm are the same "moved
    # OUT of this batch" leg (from_batch) of the same Stock/Medicine
    # Transfer transactions — split by destination: back to a warehouse
    # (Return) vs on to a different farm/batch (Transfer to Other Farm).
    # Neither is a distinct "return" transaction type in this system.
    outgoing_transfers = (StockTransfer.objects.filter(from_batch=batch)
                          .select_related("item__category", "to_warehouse", "to_farm")
                          .order_by("date", "id"))
    feed_return_rows, feed_transfer_out_rows = [], []
    for t in outgoing_transfers:
        row = {
            "date": t.date, "trnum": t.trnum, "dc_no": t.dc_no,
            "to_location": _transfer_to_location_name(t),
            "item": str(t.item), "quantity": t.quantity, "rate": t.rate,
            "amount": (t.quantity or 0) * (t.rate or 0),
        }
        (feed_return_rows if t.to_warehouse_id else feed_transfer_out_rows).append(row)

    outgoing_med_transfers = (MedicineTransfer.objects.filter(from_batch=batch)
                              .prefetch_related("items__item").select_related("to_warehouse", "to_farm")
                              .order_by("date", "id"))
    medicine_return_rows, medicine_transfer_out_rows = [], []
    for mt in outgoing_med_transfers:
        location_name = _transfer_to_location_name(mt)
        target = medicine_return_rows if mt.to_warehouse_id else medicine_transfer_out_rows
        for line in mt.items.all():
            target.append({
                "date": mt.date, "trnum": mt.trnum, "dc_no": mt.dc_no,
                "to_location": location_name, "item": str(line.item),
                "quantity": line.quantity, "rate": line.rate,
                "amount": (line.quantity or 0) * (line.rate or 0),
            })

    # Placement baseline for Opening Birds / Cum Mort% / Feed-per-bird below
    # is the Chick Placement total itself — BroilerBatch has no count field,
    # but every placement is a real Chick Placement Stock Transfer, so the
    # baseline is just the sum of those quantities, not a new data point.
    placement_total = sum((r["quantity"] or 0) for r in chick_rows)

    def _bags(qty, item):
        return (qty / item.kg_per_bag) if item and item.kg_per_bag else Decimal("0")

    sold_by_date = {}
    for bs in BirdSale.objects.filter(batch=batch).values("date").annotate(total=Sum("birds")):
        sold_by_date[bs["date"]] = bs["total"] or 0

    daily_entries = DailyEntry.objects.filter(batch=batch).select_related("feed_1", "feed_2").order_by("date", "id")
    mortality_rows = []
    cum_mortality = cum_culls = 0
    cum_feed_kg = Decimal("0")
    opening_birds = placement_total
    for de in daily_entries:
        cum_mortality += de.mortality
        cum_culls += de.culls
        sold = sold_by_date.get(de.date, 0)
        closing_birds = opening_birds - de.mortality - de.culls - sold
        feed_1_kg = de.feed_1_qty or Decimal("0")
        feed_2_kg = de.feed_2_qty or Decimal("0")
        cum_feed_kg += feed_1_kg + feed_2_kg
        avg_bw_kg = (de.avg_weight_gms or Decimal("0")) / Decimal("1000")
        mortality_rows.append({
            "date": de.date, "age": de.age_days,
            "opening_birds": opening_birds,
            "mortality": de.mortality,
            "mortality_pct": round(de.mortality / opening_birds * 100, 2) if opening_birds else 0,
            "culls": de.culls, "cum_mortality": cum_mortality,
            "cum_mortality_pct": round(cum_mortality / placement_total * 100, 2) if placement_total else 0,
            "sold_birds": sold, "closing_birds": closing_birds,
            "avg_weight_kg": round(avg_bw_kg, 3),
            "fcr": round(cum_feed_kg / (closing_birds * avg_bw_kg), 2) if closing_birds and avg_bw_kg else 0,
            "feed_1_name": de.feed_1.description if de.feed_1_id else "", "feed_1_kg": feed_1_kg,
            "feed_1_bags": round(_bags(feed_1_kg, de.feed_1), 2),
            "feed_2_name": de.feed_2.description if de.feed_2_id else "", "feed_2_kg": feed_2_kg,
            "feed_2_bags": round(_bags(feed_2_kg, de.feed_2), 2),
            "cum_feed_kg": cum_feed_kg,
            "feed_per_bird_g": round(cum_feed_kg * 1000 / placement_total, 2) if placement_total else 0,
            "balance_feed_kg": (de.feed_1_stock or 0) + (de.feed_2_stock or 0),
            "balance_feed_bags": round(_bags(de.feed_1_stock or Decimal("0"), de.feed_1)
                                       + _bags(de.feed_2_stock or Decimal("0"), de.feed_2), 2),
            "remarks": de.remarks,
        })
        opening_birds = closing_birds

    # Weekly subtotal rows, interleaved after every 7th daily row: state
    # columns (opening/closing/cumulative/balance/%) repeat the week's LAST
    # day; only the flow quantities (mortality, culls, sold, feed consumed)
    # are summed across the week.
    mortality_display = []
    for i in range(0, len(mortality_rows), 7):
        week_rows = mortality_rows[i:i + 7]
        mortality_display.extend({**r, "is_total": False} for r in week_rows)
        last = week_rows[-1]
        mortality_display.append({
            "is_total": True, "label": f"Week {i // 7 + 1} Total",
            "opening_birds": week_rows[0]["opening_birds"],
            "mortality": sum(r["mortality"] for r in week_rows),
            "mortality_pct": last["cum_mortality_pct"],
            "culls": sum(r["culls"] for r in week_rows),
            "cum_mortality": last["cum_mortality"], "cum_mortality_pct": last["cum_mortality_pct"],
            "sold_birds": sum(r["sold_birds"] for r in week_rows), "closing_birds": last["closing_birds"],
            "avg_weight_kg": last["avg_weight_kg"], "fcr": last["fcr"],
            "feed_1_kg": sum(r["feed_1_kg"] for r in week_rows), "feed_1_bags": sum(r["feed_1_bags"] for r in week_rows),
            "feed_2_kg": sum(r["feed_2_kg"] for r in week_rows), "feed_2_bags": sum(r["feed_2_bags"] for r in week_rows),
            "cum_feed_kg": last["cum_feed_kg"], "feed_per_bird_g": last["feed_per_bird_g"],
            "balance_feed_kg": last["balance_feed_kg"], "balance_feed_bags": last["balance_feed_bags"],
        })

    medicine_entries = MedicineVaccineEntry.objects.filter(batch=batch).select_related("item").order_by("date", "id")
    medicine_consumption_rows = [{
        "date": me.date, "age": me.age_days, "item": str(me.item) if me.item_id else "",
        "quantity": me.qty, "stock": me.stock, "remarks": me.remarks,
    } for me in medicine_entries]

    bird_sales = (BirdSale.objects.filter(batch=batch).select_related("customer", "farmer")
                  .order_by("date", "id"))
    bird_sale_rows = [{
        "date": bs.date, "sale_no": bs.sale_no, "doc_no": bs.doc_no,
        "buyer_name": bs.customer.name if bs.customer_id else (bs.farmer.farmer_name if bs.farmer_id else ""),
        "birds": bs.birds, "net_weight": bs.net_weight, "avg_weight": bs.avg_weight,
        "rate": bs.rate, "round_off": bs.round_off, "amount": bs.amount,
        "vehicle": bs.vehicle, "driver": bs.driver, "remarks": bs.remarks,
    } for bs in bird_sales]

    # Feed Summary: per feed item, Purchase + Transfer In - Consumed -
    # Return - Transfer to Other Farms = Balance (Kg). Bucketed by item_code
    # (not the row tables' display string) so purchases, transfers, and
    # DailyEntry consumption of the same item always land in one bucket.
    feed_summary = {}

    def _feed_bucket(item_code):
        return feed_summary.setdefault(item_code, {"purchased": Decimal("0"), "transfer_in": Decimal("0"),
                                                    "consumed": Decimal("0"), "returned": Decimal("0"),
                                                    "transferred_out": Decimal("0")})

    for pi in purchase_items:
        category_name = pi.item.category.name if pi.item.category_id else ""
        if "chick" not in category_name.lower():
            _feed_bucket(pi.item.item_code)["purchased"] += (pi.rcv_qty or 0) + (pi.free_qty or 0)
    for t in transfers:
        if not t.item.category_id or "chick" not in t.item.category.name.lower():
            _feed_bucket(t.item.item_code)["transfer_in"] += t.quantity or 0
    for t in outgoing_transfers:
        if t.to_warehouse_id:
            _feed_bucket(t.item.item_code)["returned"] += t.quantity or 0
        else:
            _feed_bucket(t.item.item_code)["transferred_out"] += t.quantity or 0
    for de in daily_entries:
        if de.feed_1_id:
            _feed_bucket(de.feed_1.item_code)["consumed"] += de.feed_1_qty or 0
        if de.feed_2_id:
            _feed_bucket(de.feed_2.item_code)["consumed"] += de.feed_2_qty or 0
    # Bucketed by item_code (stable key), but display the item name.
    feed_name_by_code = dict(
        Item.objects.filter(item_code__in=feed_summary.keys()).values_list("item_code", "description")
    )
    feed_summary_rows = [{
        "item": feed_name_by_code.get(item_code, item_code), **b,
        "balance": b["purchased"] + b["transfer_in"] - b["consumed"] - b["returned"] - b["transferred_out"],
    } for item_code, b in feed_summary.items()]

    # Bird-sale totals (reused by the Total row and the costing block)
    _bs_birds = sum(r["birds"] for r in bird_sale_rows)
    _bs_weight = sum(r["net_weight"] for r in bird_sale_rows)
    _bs_amount = sum(r["amount"] for r in bird_sale_rows)

    batch_costing = _build_batch_costing(
        batch, placement_total, cum_mortality, cum_culls, mortality_rows,
        chick_rows, feed_rows, feed_summary_rows, feed_return_rows,
        medicine_transfer_rows, medicine_consumption_rows, medicine_return_rows,
        bird_sale_rows, fetch_type=fetch_type, scheme_override=scheme_override,
    )

    # Dashboard KPI tiles + trend charts (Feed Consumption / Mortality) — as
    # of the batch's latest DailyEntry, from the same per-day mortality_rows
    # already computed above (pre weekly-interleave), not a new data source.
    last_entry = mortality_rows[-1] if mortality_rows else None
    dashboard = {
        "current_live_birds": last_entry["closing_birds"] if last_entry else placement_total,
        "avg_live_weight_kg": last_entry["avg_weight_kg"] if last_entry else Decimal("0"),
        "as_of_date": last_entry["date"] if last_entry else None,
        "feed_per_bird_g": last_entry["feed_per_bird_g"] if last_entry else 0,
        "chart": {
            "dates": [r["date"].strftime("%d %b") for r in mortality_rows],
            "daily_feed_kg": [float(r["feed_1_kg"] + r["feed_2_kg"]) for r in mortality_rows],
            "cum_feed_kg": [float(r["cum_feed_kg"]) for r in mortality_rows],
            "daily_mortality_pct": [float(r["mortality_pct"]) for r in mortality_rows],
            "cum_mortality_pct": [float(r["cum_mortality_pct"]) for r in mortality_rows],
            "fcr": [float(r["fcr"]) for r in mortality_rows],
        },
    }

    return {
        "batch_costing": batch_costing,
        "dashboard": dashboard,
        "chick_placement": chick_rows,
        "feed_purchase": feed_purchase_rows,
        "feed_transfer_in": feed_rows,
        "feed_return": feed_return_rows,
        "feed_transfer_out": feed_transfer_out_rows,
        "feed_summary": feed_summary_rows,
        "medicine_transfer_in": medicine_transfer_rows,
        "medicine_return": medicine_return_rows,
        "medicine_transfer_out": medicine_transfer_out_rows,
        "mortality": mortality_display,
        "placement_total": placement_total,
        "medicine_consumption": medicine_consumption_rows,
        "bird_sales": bird_sale_rows,
        "totals": {
            "birds": _bs_birds,
            "net_weight": _bs_weight,
            "amount": _bs_amount,
            # Overall averages for the Total row: Avg Wt = weight/birds, Rate = amount/weight
            "avg_weight": _div(_bs_weight, _bs_birds).quantize(Decimal("0.01")),
            "avg_sale_rate": _div(_bs_amount, _bs_weight).quantize(Decimal("0.01")),
            "mortality": cum_mortality, "culls": cum_culls,
        },
    }


@login_required
def broiler_batch_report(request):
    """One Batch's full growing history — feed purchase, chick placement,
    feed/medicine transfers-in and returns/transfers-out, a feed summary,
    daily mortality & feed consumption, medicine consumption, and bird
    sales (Broiler > Reports > Batch History Report).

    Feed Purchase has no batch/farm FK at all (only a Warehouse), so it's
    rolled up at the Branch level and bounded to the batch's growing
    window rather than claimed to be exact-to-batch. The Batch Costing
    Information and Summary block uses the Chick Placement total as the
    placement baseline and pulls Admin Cost / Grade from the batch's
    applicable GrowingChargeScheme (see _build_batch_costing).
    """
    from account.models import CompanyProfile

    batch_id = (request.GET.get("batch") or "").strip()
    # Filter-bar selections
    fetch_type = (request.GET.get("fetch_type") or "farmer").strip().lower()
    if fetch_type not in ("farmer", "management"):
        fetch_type = "farmer"
    book_no = (request.GET.get("book_no") or "").strip()
    export = (request.GET.get("export") or "display").strip().lower()
    schema_id = (request.GET.get("schema") or "").strip()

    batch = (BroilerBatch.objects
             .select_related("broiler_farm__branch", "broiler_farm__supervisor", "broiler_farm__farmer")
             .filter(id=batch_id).first()) if batch_id else None
    # A hand-picked Schema overrides the auto-matched Growing Charge Scheme.
    scheme_override = (GrowingChargeScheme.objects.filter(id=schema_id).first()
                       if schema_id.isdigit() else None)

    # Schema dropdown: only schemes whose master-defined date range covers the
    # batch's placement date (region-matched); auto-select the applicable one.
    schemes = GrowingChargeScheme.objects.filter(is_active=True)
    selected_schema_id = int(schema_id) if schema_id.isdigit() else None
    if batch:
        placement = batch.start_date
        region_id = batch.broiler_farm.branch.region_id
        if placement:
            schemes = schemes.filter(region_id=region_id,
                                     from_date__lte=placement, to_date__gte=placement)
        else:
            schemes = schemes.filter(region_id=region_id)
        if selected_schema_id is None:
            matched = _match_growing_charge_scheme(batch, placement)
            selected_schema_id = matched.id if matched else None
    schemes = schemes.order_by("schema_name")

    return render(request, "broiler_batch_report.html", {
        "farms": BroilerFarm.objects.order_by("farm_name"),
        "batches": BroilerBatch.objects.select_related("broiler_farm").order_by("-start_date", "-id"),
        "schemes": schemes,
        "batch": batch,
        "batch_requested": bool(batch_id),
        "report": _build_batch_report(batch, fetch_type=fetch_type,
                                      scheme_override=scheme_override) if batch else None,
        "company": CompanyProfile.get_solo(),
        "fetch_type": fetch_type,
        "fetch_type_label": "Management" if fetch_type == "management" else "Farmer",
        "book_no": book_no,
        "export": export,
        "selected_schema_id": selected_schema_id,
    })


# ---------------------------------------------------------------------------
# Live Flock Summary Report (Broiler > Reports)
# ---------------------------------------------------------------------------

def _breed_standard_at(breed_id, age):
    """The breed's standard row at `age` — exact, else the nearest row at/below
    that age (curve carried forward). If the breed's curve doesn't reach that
    low, fall back to its earliest defined row so the Std columns still show a
    value rather than blank. None only when the breed has no standard rows."""
    if not breed_id or age is None:
        return None
    std = (BreedStandard.objects.filter(breed_id=breed_id, age__lte=age)
           .order_by("-age").first())
    if std:
        return std
    return (BreedStandard.objects.filter(breed_id=breed_id, age__gt=age)
            .order_by("age").first())


def _interp_standard(breed_id, key_field, target, out_field):
    """Read the breed's standard curve at a *value* of `key_field` instead of at
    an age — e.g. "what's the standard cum_feed when body_weight = X", or the
    reverse. Walks the curve ordered by age (both body_weight and cum_feed rise
    with age) and linearly interpolates `out_field` where `key_field` crosses
    `target`; clamps to the end rows outside the curve. Returns a Decimal, or
    None when the breed has no usable rows."""
    if not breed_id or target is None:
        return None
    rows = [(Decimal(str(k)), Decimal(str(v)))
            for k, v in BreedStandard.objects.filter(breed_id=breed_id)
            .order_by("age").values_list(key_field, out_field)
            if k is not None and v is not None]
    if not rows:
        return None
    target = Decimal(str(target))
    if target <= rows[0][0]:
        return rows[0][1]
    if target >= rows[-1][0]:
        return rows[-1][1]
    for (k0, v0), (k1, v1) in zip(rows, rows[1:]):
        if k0 <= target <= k1:
            if k1 == k0:
                return v0
            return v0 + (v1 - v0) * (target - k0) / (k1 - k0)
    return rows[-1][1]


def _flock_valuation_remark(*, not_started, avg_bwt, std_bwt, fcr, std_fcr,
                            feed_con, std_feed_at_bwt, mort_pct, gap_days):
    """Auto-compose a one-line valuation of a live flock from its own numbers:
    an overall verdict (On Track / Watch / Behind / Critical) plus the drivers
    (weight vs std, feed vs the standard-for-that-weight, FCR vs std, mortality,
    data freshness). Purely derived — no stored field."""
    if not_started:
        return "Not Started — chicks placed, no daily entry yet"

    f = lambda x: float(x) if x is not None else None
    avg_bwt, std_bwt, fcr, std_fcr = f(avg_bwt), f(std_bwt), f(fcr), f(std_fcr)
    feed_con, std_feed_at_bwt, mort_pct = f(feed_con), f(std_feed_at_bwt), f(mort_pct)

    parts, penalty = [], 0
    # Body weight vs the age-standard
    if std_bwt and avg_bwt:
        dev = (avg_bwt - std_bwt) / std_bwt * 100
        if dev <= -20:
            parts.append(f"B.Wt {abs(dev):.0f}% below std"); penalty += 3
        elif dev <= -10:
            parts.append(f"B.Wt {abs(dev):.0f}% below std"); penalty += 2
        elif dev >= 10:
            parts.append(f"B.Wt {dev:.0f}% above std")
        else:
            parts.append("B.Wt on target")
    # Feed used vs what the standard bird eats to reach the SAME weight
    if std_feed_at_bwt and feed_con:
        fe = (feed_con - std_feed_at_bwt) / std_feed_at_bwt * 100
        if fe >= 15:
            parts.append(f"over-fed {fe:.0f}% for weight"); penalty += 2
        elif fe >= 8:
            parts.append(f"over-fed {fe:.0f}% for weight"); penalty += 1
        elif fe <= -10:
            parts.append(f"under-fed {abs(fe):.0f}% for weight")
    # FCR vs std
    if std_fcr and fcr:
        if fcr > std_fcr * 1.10:
            parts.append("FCR well above std"); penalty += 2
        elif fcr > std_fcr * 1.03:
            parts.append("FCR above std"); penalty += 1
        elif fcr < std_fcr * 0.97:
            parts.append("FCR better than std")
    # Mortality
    if mort_pct is not None:
        if mort_pct >= 8:
            parts.append(f"high mortality {mort_pct:.1f}%"); penalty += 3
        elif mort_pct >= 5:
            parts.append(f"mortality {mort_pct:.1f}%"); penalty += 1
    # Data freshness
    if gap_days and gap_days >= 2:
        parts.append(f"entries {gap_days}d stale"); penalty += 1

    verdict = ("Critical" if penalty >= 5 else "Behind" if penalty >= 3
               else "Watch" if penalty >= 1 else "On Track")
    return f"{verdict} — " + ("; ".join(parts) if parts else "all metrics near standard")


def _live_flock_row(batch, today):
    """One report row for a live flock, reusing the batch report engine plus
    the age/feed-outlook columns the fleet view needs."""
    from inventory.models import StockTransfer

    report = _build_batch_report(batch, fetch_type="management")
    bc = report["batch_costing"]
    farm = batch.broiler_farm

    placed = _num(bc.get("chicks_placed"))
    mort = _num(bc.get("mortality"))
    culls = _num(bc.get("culls"))
    sold = _num(bc.get("sold_birds"))
    placement_date = bc.get("placement_date") or batch.start_date
    actual_age = (today - placement_date).days if placement_date else 0

    # latest daily entry + gap
    entries = list(DailyEntry.objects.filter(batch=batch).order_by("-date")[:3])
    latest = entries[0].date if entries else None
    gap_days = (today - latest).days if latest else None

    # last *body-weight* reading (skip days with no weight taken) + its gap
    last_wt = (DailyEntry.objects.filter(batch=batch, avg_weight_gms__gt=0)
               .order_by("-date").first())
    avg_bwt = last_wt.avg_weight_gms if last_wt else Decimal("0")
    last_bwt_date = last_wt.date if last_wt else None
    last_bwt_gap = (today - last_bwt_date).days if last_bwt_date else None

    # recent daily feed rate (last <=3 entries), fallback to overall
    feed_consumed = _num(bc.get("feed_consumed"))
    recent = sum((_num(e.feed_1_qty) + _num(e.feed_2_qty)) for e in entries)
    daily_rate = (recent / len(entries)) if entries else (
        feed_consumed / actual_age if actual_age else Decimal("0"))

    # farm<->farm feed movements (subset of the engine's in/out)
    feed_item_ids = list(Item.objects.filter(category__name__icontains="feed").values_list("id", flat=True))
    transfer_in_farms = StockTransfer.objects.filter(
        to_batch=batch, from_location_type="farm", item_id__in=feed_item_ids
    ).aggregate(t=Sum("quantity"))["t"] or Decimal("0")
    transfer_out_farms = sum((_num(r["quantity"]) for r in report.get("feed_transfer_out", [])), Decimal("0"))

    feed_sent = _num(bc.get("feed_sent"))
    feed_return = _num(bc.get("feed_return"))
    feed_balance = feed_sent - feed_consumed - feed_return - transfer_out_farms

    std = _breed_standard_at(batch.breed_id, actual_age)
    std_bwt = std.body_weight if std else None   # grams (matches Avg B.Wt in grams)
    std_fcr = std.fcr if std else None
    # cum_feed is per-bird grams -> total kg = cum_feed(g) x birds / 1000 (matches Feed Con in kg)
    std_feed_con = (std.cum_feed * placed / Decimal("1000")) if std else None

    # Weight-adjusted (age-independent) standards: read the curve at the flock's
    # ACTUAL weight/feed rather than its age. "Std Feed @ B.Wt" = the cum_feed a
    # standard bird eats to reach the birds' current body weight; "Std B.Wt @
    # Feed" = the body weight a standard bird has after eating the feed actually
    # consumed per bird. Lets you judge feed efficiency independent of how far
    # the flock is ahead/behind on age.
    actual_feed_per_bird = (feed_consumed * Decimal("1000") / placed) if placed else None  # g/bird
    std_feed_at_bwt_g = _interp_standard(batch.breed_id, "body_weight", avg_bwt, "cum_feed")   # g/bird
    std_feed_at_bwt = (std_feed_at_bwt_g * placed / Decimal("1000")) if std_feed_at_bwt_g is not None else None  # total kg
    std_bwt_at_feed = _interp_standard(batch.breed_id, "cum_feed", actual_feed_per_bird, "body_weight")  # g/bird

    # Live-flock metrics on the CURRENT weight on hand (sold weight + current
    # live weight = available birds x last body weight), not the sale-only
    # weight — so a still-growing flock shows real FCR/CFCR/PC/Kg instead of 0
    # (no sales) or a blown-up CFCR (feed / tiny mortality weight). For a sold-
    # out flock live_weight is 0, so this reduces to the sale-based figures.
    available = placed - mort - culls - sold
    live_weight_kg = available * (avg_bwt / Decimal("1000"))
    sold_weight = _num(bc.get("sold_weight"))
    mortality_weight = _num(bc.get("mortality_weight"))
    total_weight_now = sold_weight + live_weight_kg
    total_prod_cost = _num(bc.get("total_production_cost"))

    m_pc_kg = (_div(total_prod_cost, total_weight_now) if total_weight_now > 0
               else _num(bc.get("production_cost_per_kg"))).quantize(Decimal("0.01"))
    fcr_val = _div(feed_consumed, total_weight_now).quantize(Decimal("0.001")) if total_weight_now > 0 else Decimal("0")
    cfcr_val = (_div(feed_consumed, total_weight_now + mortality_weight).quantize(Decimal("0.01"))
                if (total_weight_now + mortality_weight) > 0 else Decimal("0"))

    # EEF: keep the engine's sale-based value once the flock has sales (uses
    # mean lifting age); for a still-growing flock compute it on current values.
    if sold_weight > 0:
        eef_val = _num(bc.get("eef"))
    elif actual_age and fcr_val:
        surviving = sold + available
        livability = _div(surviving * 100, placed)
        avg_wt_kg = _div(total_weight_now, surviving)
        eef_val = _div(livability * avg_wt_kg * 100, Decimal(str(actual_age)) * fcr_val).quantize(Decimal("0.01"))
    else:
        eef_val = Decimal("0")

    q2 = Decimal("0.01")
    remark = _flock_valuation_remark(
        not_started=bool(placed > 0 and latest is None),
        avg_bwt=avg_bwt, std_bwt=std_bwt, fcr=fcr_val, std_fcr=std_fcr,
        feed_con=feed_consumed, std_feed_at_bwt=std_feed_at_bwt,
        mort_pct=_num(bc.get("total_mort_pct")), gap_days=gap_days)
    return {
        "branch": farm.branch.branch_name if farm.branch_id else "",
        "line": farm.line or "",
        "supervisor": str(farm.supervisor) if farm.supervisor_id else "",
        "farmer": farm.farmer.farmer_name if farm.farmer_id else "",
        "batch": batch.batch_name,
        "book_no": batch.book_number or "",
        "actual_age": actual_age,
        "placement_date": placement_date,
        "lifting_start": bc.get("sale_start_date"),
        "mean_age": bc.get("mean_age"),
        "latest_entry": latest, "gap_days": gap_days,
        "not_started": bool(placed > 0 and latest is None),
        "housed": placed, "mort": mort,
        "mort_pct": _num(bc.get("total_mort_pct")),
        "cull": culls, "cull_pct": _div(culls * 100, placed).quantize(q2),
        "sold_birds": sold, "sold_weight": _num(bc.get("sold_weight")),
        "available": available, "available_weight": live_weight_kg.quantize(q2),
        "std_bwt": std_bwt, "avg_bwt": avg_bwt,
        "std_bwt_at_feed": std_bwt_at_feed.quantize(q2) if std_bwt_at_feed is not None else None,
        "last_bwt_date": last_bwt_date, "last_bwt_gap": last_bwt_gap,
        "std_fcr": std_fcr, "fcr": fcr_val, "cfcr": cfcr_val, "eef": eef_val,
        "m_pc_kg": m_pc_kg,
        "m_pc_bird": bc.get("prod_cost_per_bird"),
        "feed_transferred": feed_sent, "transfer_in_farms": transfer_in_farms,
        "std_feed_con": std_feed_con, "std_feed_con_bird": std.cum_feed if std else None,
        "feed_con": feed_consumed,
        "feed_con_bird": actual_feed_per_bird.quantize(q2) if actual_feed_per_bird is not None else None,
        "std_feed_at_bwt": std_feed_at_bwt.quantize(q2) if std_feed_at_bwt is not None else None,
        "std_feed_at_bwt_bird": std_feed_at_bwt_g.quantize(q2) if std_feed_at_bwt_g is not None else None,
        "transfer_out_farms": transfer_out_farms, "feed_balance": feed_balance,
        "feed_balance_days": _div(feed_balance, daily_rate).quantize(q2) if daily_rate else Decimal("0"),
        "next_3_days_feed": (daily_rate * 3).quantize(q2),
        "remark": remark, "remark_verdict": remark.split(" — ")[0],
    }


@login_required
def live_flock_summary_report(request):
    """Broiler > Reports > Live Flock Summary — one row per live/ongoing flock."""
    from account.models import CompanyProfile

    region_id = (request.GET.get("region") or "").strip()
    branch_id = (request.GET.get("branch") or "").strip()
    supervisor_id = (request.GET.get("supervisor") or "").strip()
    breed_id = (request.GET.get("breed") or "").strip()

    batches = (BroilerBatch.objects.filter(end_date__isnull=True, is_closed=False)
               .select_related("broiler_farm__branch", "broiler_farm__supervisor",
                               "broiler_farm__farmer", "breed")
               .order_by("broiler_farm__branch__branch_name", "batch_name"))
    if branch_id.isdigit():
        batches = batches.filter(broiler_farm__branch_id=branch_id)
    elif region_id.isdigit():
        batches = batches.filter(broiler_farm__branch__region_id=region_id)
    if supervisor_id.isdigit():
        batches = batches.filter(broiler_farm__supervisor_id=supervisor_id)
    if breed_id.isdigit():
        batches = batches.filter(breed_id=breed_id)

    today = timezone.localdate()
    rows = [_live_flock_row(b, today) for b in batches]

    return render(request, "live_flock_summary_report.html", {
        "rows": rows,
        "regions": Region.objects.order_by("description"),
        "branches": Branch.objects.order_by("branch_name"),
        "supervisors": Supervisor.objects.order_by("name"),
        "breeds": Breed.objects.filter(is_active=True).order_by("description"),
        "region_id": region_id, "branch_id": branch_id,
        "supervisor_id": supervisor_id, "breed_id": breed_id,
        "company": CompanyProfile.get_solo(),
    })


def _haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km between two lat/long points; None if any
    coordinate is missing."""
    if None in (lat1, lon1, lat2, lon2):
        return None
    import math
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return r * 2 * math.asin(math.sqrt(a))


def _day_record_row(e, sel_date, feed_ids, chick_ids, placed_cache, StockTransfer, BirdSale):
    """One Day Record row for a single DailyEntry `e` recorded on `sel_date`.
    Everything on the day (mort/cull/sold/feed) plus the cumulative figures to
    that date and the breed-standard comparison. Image/disease/entry-geo columns
    are returned blank — not yet captured on the daily entry."""
    from django.db.models import Sum as _Sum
    batch, farm = e.batch, e.farm
    q2 = Decimal("0.01")

    # chicks placed for this batch (chick-category stock transfers into it)
    if batch and batch.id not in placed_cache:
        placed_cache[batch.id] = _num(StockTransfer.objects.filter(
            to_batch_id=batch.id, item_id__in=chick_ids).aggregate(t=_Sum("quantity"))["t"])
    placed = placed_cache.get(batch.id, Decimal("0")) if batch else Decimal("0")

    def _de_agg(flt):
        r = DailyEntry.objects.filter(**flt).aggregate(
            m=_Sum("mortality"), c=_Sum("culls"),
            f1=_Sum("feed_1_qty"), f2=_Sum("feed_2_qty"))
        return _num(r["m"]), _num(r["c"]), _num(r["f1"]) + _num(r["f2"])

    def _sale_agg(flt):
        r = BirdSale.objects.filter(**flt).aggregate(b=_Sum("birds"), w=_Sum("net_weight"))
        return _num(r["b"]), _num(r["w"])

    mort_before, cull_before, _feed_before = _de_agg({"batch": batch, "date__lt": sel_date})
    _mort_upto, _cull_upto, feed_upto = _de_agg({"batch": batch, "date__lte": sel_date})
    sold_before, _soldw_before = _sale_agg({"batch": batch, "date__lt": sel_date})
    sold_today, soldw_today = _sale_agg({"batch": batch, "date": sel_date})
    sold_upto, soldw_upto = _sale_agg({"batch": batch, "date__lte": sel_date})

    mort_today = _num(e.mortality)
    cull_today = _num(e.culls)
    cum_mort = mort_before + mort_today          # cumulative mortality to date
    cum_cull = cull_before + cull_today

    opening = placed - mort_before - cull_before - sold_before   # birds alive at day start
    balance = opening - mort_today - cull_today - sold_today      # closing birds for the day

    avg_bwt = _num(e.avg_weight_gms)
    age = e.age_days
    std = _breed_standard_at(batch.breed_id if batch else None, age)
    std_bwt = std.body_weight if std else None
    std_fcr = std.fcr if std else None

    # feed movement on the day
    feed_con = _num(e.feed_1_qty) + _num(e.feed_2_qty)
    feed_stock = _num(e.feed_1_stock) + _num(e.feed_2_stock)     # closing stock
    prev = (DailyEntry.objects.filter(batch=batch, date__lt=sel_date)
            .order_by("-date", "-id").first())
    feed_ob = (_num(prev.feed_1_stock) + _num(prev.feed_2_stock)) if prev else Decimal("0")
    feed_in = _num(StockTransfer.objects.filter(
        to_batch=batch, item_id__in=feed_ids, date=sel_date).aggregate(t=_Sum("quantity"))["t"])
    feed_out = _num(StockTransfer.objects.filter(
        from_batch=batch, item_id__in=feed_ids, date=sel_date).aggregate(t=_Sum("quantity"))["t"])

    # FCR / CFCR on weight produced to date (live + sold), like the live report
    live_weight = balance * avg_bwt / Decimal("1000")
    total_weight = live_weight + soldw_upto
    mort_weight = cum_mort * avg_bwt / Decimal("1000")          # approx (birds ~current wt)
    fcr = _div(feed_upto, total_weight).quantize(Decimal("0.001")) if total_weight > 0 else Decimal("0")
    cfcr = (_div(feed_upto, total_weight + mort_weight).quantize(q2)
            if (total_weight + mort_weight) > 0 else Decimal("0"))

    farmer = farm.farmer if farm and farm.farmer_id else None
    batch_no = ""
    if batch and batch.batch_name and "-" in batch.batch_name:
        tail = batch.batch_name.rsplit("-", 1)[-1]
        batch_no = tail if tail.isdigit() else ""

    # field-captured attachments / geo (mobile app populates; may be blank)
    from broiler.models import BroilerDisease
    diseases = list(BroilerDisease.objects.filter(batch=batch, diagnosed_date=sel_date)
                    .exclude(disease_name="").values_list("disease_name", flat=True)) if batch else []
    farm_lat = farm.farm_latitude if farm else None
    farm_lon = farm.farm_longitude if farm else None
    diff_km = _haversine_km(farm_lat, farm_lon, e.entry_latitude, e.entry_longitude)

    return {
        "farm_code": farm.farm_code if farm else "",
        "farmer": farmer.farmer_name if farmer else "",
        "batch": batch.batch_name if batch else "",
        "batch_no": batch_no,
        "supervisor": (str(e.supervisor) if e.supervisor_id
                       else str(farm.supervisor) if farm and farm.supervisor_id else ""),
        "age": age,
        "placed": placed, "opening": opening,
        "mort": mort_today,
        "mort_pct": _div(mort_today * 100, opening).quantize(q2),
        "mort_image": e.mort_image.url if e.mort_image else "",
        "cum_mort": cum_mort,
        "cum_mort_pct": _div(cum_mort * 100, placed).quantize(q2),
        "culls": cull_today, "cull_image": e.cull_image.url if e.cull_image else "",
        "sold": sold_today, "sold_wt": soldw_today.quantize(q2),
        "balance": balance,
        "std_bwt": std_bwt, "avg_bwt": avg_bwt,
        "std_fcr": std_fcr, "fcr": fcr, "cfcr": cfcr,
        "feed_ob": feed_ob.quantize(q2), "feed_in": feed_in.quantize(q2),
        "feed_out": feed_out.quantize(q2), "feed_con": feed_con.quantize(q2),
        "feed_stock": feed_stock.quantize(q2),
        "cum_feed": feed_upto.quantize(q2),
        "feed_images": e.feed_image.url if e.feed_image else "",
        "line": farm.line if farm else "",
        "branch": farm.branch.branch_name if farm and farm.branch_id else "",
        "farmer_contact": (farmer.mobile_no or farmer.phone_no or "") if farmer else "",
        "entry_time": e.entry_time,
        "entry_by": str(e.entry_by) if e.entry_by_id else "",
        "remarks": e.remarks or "",
        "diseases_name": ", ".join(diseases),
        "farm_location": (f"{farm_lat}, {farm_lon}"
                          if farm_lat is not None and farm_lon is not None else ""),
        "entry_location": (f"{e.entry_latitude}, {e.entry_longitude}"
                           if e.entry_latitude is not None and e.entry_longitude is not None else ""),
        "diff_km": round(diff_km, 3) if diff_km is not None else "",
    }


@login_required
def day_record_report(request):
    """Broiler > Reports > Day Record Report — one row per daily entry recorded
    on the selected date across all farms: that day's mortality/culls/sales,
    body weight vs breed standard, and feed movement (opening/in/out/consumed/
    stock/cumulative), with a Total footer. Image, disease and entry-location
    columns are shown but not yet captured on the daily entry (blank for now)."""
    from account.models import CompanyProfile
    from django.utils.dateparse import parse_date
    from inventory.models import StockTransfer, Item
    from broiler.models import BirdSale

    region_id = (request.GET.get("region") or "").strip()
    branch_id = (request.GET.get("branch") or "").strip()
    line = (request.GET.get("line") or "").strip()
    supervisor_id = (request.GET.get("supervisor") or "").strip()
    farm_id = (request.GET.get("farm") or "").strip()
    date_str = (request.GET.get("date") or "").strip()

    if date_str:
        sel_date = parse_date(date_str) or timezone.localdate()
    else:  # default to the most recent day that actually has entries
        sel_date = (DailyEntry.objects.order_by("-date")
                    .values_list("date", flat=True).first()) or timezone.localdate()

    entries = (DailyEntry.objects.filter(date=sel_date)
               .select_related("farm__branch", "farm__supervisor", "farm__farmer",
                               "batch__breed", "supervisor", "entry_by")
               .order_by("farm__farm_code", "batch__batch_name", "id"))
    if region_id:
        entries = entries.filter(farm__branch__region_id=region_id)
    if branch_id:
        entries = entries.filter(farm__branch_id=branch_id)
    if line:
        entries = entries.filter(farm__line=line)
    if supervisor_id:
        entries = entries.filter(Q(supervisor_id=supervisor_id) | Q(farm__supervisor_id=supervisor_id))
    if farm_id:
        entries = entries.filter(farm_id=farm_id)

    feed_ids = list(Item.objects.filter(category__name__icontains="feed").values_list("id", flat=True))
    chick_ids = list(Item.objects.filter(category__name__icontains="chick").values_list("id", flat=True))
    placed_cache = {}

    rows = [_day_record_row(e, sel_date, feed_ids, chick_ids, placed_cache, StockTransfer, BirdSale)
            for e in entries]

    # Total footer over the summable columns
    tkeys = ["placed", "opening", "mort", "cum_mort", "culls", "sold", "sold_wt",
             "balance", "feed_ob", "feed_in", "feed_out", "feed_con", "feed_stock", "cum_feed"]
    totals = {k: sum((_num(r[k]) for r in rows), Decimal("0")) for k in tkeys}
    totals["mort_pct"] = _div(totals["mort"] * 100, totals["opening"]).quantize(Decimal("0.01"))
    totals["cum_mort_pct"] = _div(totals["cum_mort"] * 100, totals["placed"]).quantize(Decimal("0.01"))

    lines = (BroilerFarm.objects.exclude(line="").order_by("line")
             .values_list("line", flat=True).distinct())

    return render(request, "day_record_report.html", {
        "rows": rows, "totals": totals, "sel_date": sel_date,
        "regions": Region.objects.order_by("description"),
        "branches": Branch.objects.order_by("branch_name"),
        "lines": lines,
        "supervisors": Supervisor.objects.order_by("name"),
        "farms": BroilerFarm.objects.select_related("branch").order_by("farm_name"),
        "region_id": region_id, "branch_id": branch_id, "line": line,
        "supervisor_id": supervisor_id, "farm_id": farm_id,
        "company": CompanyProfile.get_solo(),
    })


@login_required
def chicks_placement_report(request):
    """Register of every Chicks Placement transaction (Warehouse -> Farm/Batch
    Stock Transfer of a chicks-category item) within a Branch/Farm/date window
    (Broiler > Reports > Chicks Placement Report). Chicks Ordered/Transit
    Mortality/Shortage/Culls are the same reference-only fields as the Chicks
    Placement transaction itself — only Placement Qty ever reaches inventory.
    """
    from account.models import CompanyProfile
    from inventory.models import StockTransfer
    from hatchery_master.models import Hatchery

    region_id = (request.GET.get("region") or "").strip()
    branch_id = (request.GET.get("branch") or "").strip()
    line = (request.GET.get("line") or "").strip()
    supervisor_id = (request.GET.get("supervisor") or "").strip()
    farm_id = (request.GET.get("farm") or "").strip()
    hatchery_id = (request.GET.get("hatchery") or "").strip()
    from_date = (request.GET.get("from_date") or "").strip()
    to_date = (request.GET.get("to_date") or "").strip()
    status = (request.GET.get("status") or "").strip().lower()
    export = (request.GET.get("export") or "display").strip().lower()
    submitted = bool(region_id or branch_id or line or supervisor_id or farm_id or hatchery_id
                     or from_date or to_date or status or request.GET.get("submit"))

    rows, totals = [], None
    if submitted:
        qs = (StockTransfer.objects
              .filter(to_location_type="farm", item__category__name__icontains="chick")
              .select_related("to_farm__branch", "to_farm__supervisor", "to_batch",
                              "from_warehouse", "source_hatchery", "item")
              .order_by("date", "id"))
        if region_id:
            qs = qs.filter(to_farm__branch__region_id=region_id)
        if branch_id:
            qs = qs.filter(to_farm__branch_id=branch_id)
        if line:
            qs = qs.filter(to_farm__line=line)
        if supervisor_id:
            qs = qs.filter(to_farm__supervisor_id=supervisor_id)
        if farm_id:
            qs = qs.filter(to_farm_id=farm_id)
        if hatchery_id:
            qs = qs.filter(source_hatchery_id=hatchery_id)
        if from_date:
            qs = qs.filter(date__gte=from_date)
        if to_date:
            qs = qs.filter(date__lte=to_date)
        # Status reflects the linked Batch's own state (see batch_status below).
        if status == "active":
            qs = qs.filter(to_batch__isnull=False, to_batch__end_date__isnull=True)
        elif status == "completed":
            qs = qs.filter(to_batch__isnull=False, to_batch__end_date__isnull=False)

        # Free Quantity has no backing field on StockTransfer yet, so it's always
        # 0 (shown, not hidden, so the column stays honest about what isn't
        # tracked) and Total Chicks Placed = Quantity Received + Free Quantity.
        free_quantity = Decimal("0")
        t_ordered = t_mortality = t_shortage = t_culls = t_excess = Decimal("0")
        t_received = t_free = t_placed = t_amount = Decimal("0")
        mort_pct_sum = Decimal("0")
        farm_ids, branch_ids, warehouse_ids = set(), set(), set()
        for t in qs:
            ordered = t.chicks_ordered or Decimal("0")
            mortality = t.transit_mortality or Decimal("0")
            shortage = t.shortage or Decimal("0")
            culls = t.culls or Decimal("0")
            received = t.quantity or Decimal("0")
            placed = received + free_quantity
            amount = (received * (t.rate or Decimal("0"))).quantize(Decimal("0.01"))
            # Excess = birds received beyond what the ordered/loss breakdown expected
            # (only meaningful when Chicks Ordered was actually recorded).
            excess = Decimal("0")
            if ordered > 0:
                expected = max(ordered - mortality - shortage - culls, Decimal("0"))
                excess = max(received - expected, Decimal("0"))
            row_mort_pct = (mortality / ordered * 100).quantize(Decimal("0.01")) if ordered else Decimal("0")
            # Status reflects the linked Batch's own state — a Batch with no
            # end_date is still running (Active); once end_date is set it's
            # Closed. No batch linked means there's nothing to report on.
            if not t.to_batch_id:
                batch_status = ""
            elif t.to_batch.end_date is None:
                batch_status = "Active"
            else:
                batch_status = "Completed"
            rows.append({
                "batch_status": batch_status,
                "date": t.date, "trnum": t.trnum, "dc_no": t.dc_no,
                "branch_name": t.to_farm.branch.branch_name if t.to_farm_id else "",
                "line": t.to_farm.line if t.to_farm_id else "",
                "supervisor_name": t.to_farm.supervisor.name if t.to_farm_id and t.to_farm.supervisor_id else "",
                "farm_code": t.to_farm.farm_code if t.to_farm_id else "",
                "farm_name": t.to_farm.farm_name if t.to_farm_id else "",
                "batch_name": t.to_batch.batch_name if t.to_batch_id else "",
                "source_hatchery_name": t.source_hatchery.hatchery_name if t.source_hatchery_id else "",
                "warehouse_name": t.from_warehouse.name if t.from_warehouse_id else "",
                "chicks_ordered": ordered, "transit_mortality": mortality,
                "mort_pct": row_mort_pct,
                "shortage": shortage, "culls": culls,
                "culls_pct": (culls / ordered * 100).quantize(Decimal("0.01")) if ordered else Decimal("0"),
                "excess": excess,
                "quantity_received": received, "free_quantity": free_quantity, "total_placed": placed,
                "rate": t.rate or Decimal("0"), "amount": amount,
                "farm_capacity": t.to_farm.farm_capacity if t.to_farm_id else "",
            })
            t_ordered += ordered; t_mortality += mortality; t_shortage += shortage
            t_culls += culls; t_excess += excess
            t_received += received; t_free += free_quantity; t_placed += placed; t_amount += amount
            mort_pct_sum += row_mort_pct
            if t.to_farm_id:
                farm_ids.add(t.to_farm_id)
                branch_ids.add(t.to_farm.branch_id)
            if t.from_warehouse_id:
                warehouse_ids.add(t.from_warehouse_id)

        shortage_pct = (t_shortage / t_ordered * 100).quantize(Decimal("0.01")) if t_ordered else Decimal("0")
        culls_pct = (t_culls / t_ordered * 100).quantize(Decimal("0.01")) if t_ordered else Decimal("0")
        totals = {
            "chicks_ordered": t_ordered, "transit_mortality": t_mortality,
            "mort_pct": (t_mortality / t_ordered * 100).quantize(Decimal("0.01")) if t_ordered else Decimal("0"),
            "shortage": t_shortage, "culls": t_culls, "culls_pct": culls_pct,
            "excess": t_excess,
            "quantity_received": t_received, "free_quantity": t_free, "total_placed": t_placed,
            "amount": t_amount,
        }
        # KPI cards: real, derived-only figures — no fabricated "status" metric,
        # since neither StockTransfer nor BroilerBatch tracks any such state.
        kpi = {
            "total_placed": t_placed,
            "total_ordered": t_ordered,
            "placed_pct": (t_placed / t_ordered * 100).quantize(Decimal("0.1")) if t_ordered else Decimal("100.0"),
            "total_mortality": t_mortality,
            "overall_mort_pct": totals["mort_pct"],
            "total_shortage": t_shortage,
            "shortage_pct": shortage_pct,
            "total_culls": t_culls,
            "culls_pct": culls_pct,
            "average_mort_pct": (mort_pct_sum / len(rows)).quantize(Decimal("0.01")) if rows else Decimal("0"),
            "farms_count": len(farm_ids),
            "branches_count": len(branch_ids),
            "warehouses_count": len(warehouse_ids),
        }

    if not submitted:
        kpi = {"total_placed": 0, "total_ordered": 0, "placed_pct": Decimal("0"),
               "total_mortality": 0, "overall_mort_pct": Decimal("0"), "average_mort_pct": Decimal("0"),
               "total_shortage": 0, "shortage_pct": Decimal("0"),
               "total_culls": 0, "culls_pct": Decimal("0"),
               "farms_count": 0, "branches_count": 0, "warehouses_count": 0}

    lines = (BroilerFarm.objects.exclude(line="").order_by("line")
             .values_list("line", flat=True).distinct())

    return render(request, "chicks_placement_report.html", {
        "regions": Region.objects.order_by("description"),
        "branches": Branch.objects.order_by("branch_name"),
        "lines": lines,
        "supervisors": Supervisor.objects.order_by("name"),
        "farms": BroilerFarm.objects.select_related("branch").order_by("farm_name"),
        "hatcheries": Hatchery.objects.order_by("hatchery_name"),
        "region_id": region_id, "branch_id": branch_id, "line": line,
        "supervisor_id": supervisor_id, "farm_id": farm_id, "hatchery_id": hatchery_id,
        "from_date": from_date, "to_date": to_date, "status": status,
        "submitted": submitted, "rows": rows, "totals": totals, "kpi": kpi,
        "export": export,
        "company": CompanyProfile.get_solo(),
    })


@login_required
def feed_dispatch_stock_report(request):
    """Feed Dispatch & Stock ledger for a single Warehouse (Broiler > Reports
    > Feed Dispatch & Stock Report) — one row per dispatch (Warehouse ->
    Farm), return (Farm -> Warehouse) or purchase receipt (Supplier ->
    Warehouse) of a tracked feed item, in chronological order, carrying a
    running per-feed-type stock balance (in bags) forward after every row —
    matching a feed store's own paper stock register.

    Stock is computed independently, event by event, from the very first
    historical transaction for this warehouse: no single transaction type's
    own running-stock field reflects the *combined* physical balance (see
    StockTransfer.stock / InventoryAdjustmentItem.stock — each only chains
    through its own transaction type), and Purchases don't touch any
    running-stock field at all.

    Freight is only ever real on purchase-receipt rows (GeneralPurchase.
    freight_amount) — Stock Transfer has no freight field, so dispatch/return
    rows show it blank rather than a fabricated 0.
    """
    from account.models import CompanyProfile
    from django.utils.dateparse import parse_date
    from inventory.models import StockTransfer, Mapping
    from purchase.models import GeneralPurchaseItem

    region_id = (request.GET.get("region") or "").strip()
    branch_id = (request.GET.get("branch") or "").strip()
    warehouse_id = (request.GET.get("warehouse") or "").strip()
    from_date = (request.GET.get("from_date") or "").strip()
    to_date = (request.GET.get("to_date") or "").strip()
    export = (request.GET.get("export") or "display").strip().lower()
    submitted = bool(from_date or to_date or request.GET.get("submit"))

    # Feed columns are fully dynamic — every Item under a "Feed" category is
    # its own ledger column, keyed by item id and ordered by item_code. Add a
    # new feed Item and it shows up here automatically, no code change needed.
    feed_items_all = list(Item.objects.filter(category__name__icontains="feed").order_by("item_code"))
    label_ids = [it.id for it in feed_items_all]
    label_item = {it.id: it for it in feed_items_all}
    label_name = {it.id: it.description for it in feed_items_all}
    # Fixed (non-feed) columns: Date, Txn No.(ERP), Challan No., Branch,
    # Warehouse, Supplier/Farm Name, Farm Batch No. (7) + Total Bags/Total Kg
    # (2) + Net Total Bag Stock (1) + Vehicle No./Freight Paid/Remarks (3) = 13.
    opening_label_colspan = 7  # Date..Farm Batch No.
    total_columns = 13 + 3 * len(label_ids)

    ledger_rows, opening, ledger_totals, trend = [], None, None, None
    kpi = {"total_dispatched_bags": Decimal("0"), "total_received_bags": Decimal("0"),
           "net_total_bag_stock": Decimal("0"), "total_freight": Decimal("0")}
    top_feed = [{"label": label_name[l], "value": Decimal("0")} for l in label_ids]
    recent_activity = {"dispatched": Decimal("0"), "received": Decimal("0"),
                       "adjustment": Decimal("0"), "returned": Decimal("0")}
    warehouse_snapshot = []

    # A Warehouse (Office) has no direct Branch FK — resolved via inventory.
    # Mapping (TYPE_SECTOR_BRANCH: from_id=warehouse, to_id=branch). Region
    # narrows to every Branch in it, Branch narrows to its mapped Warehouse(s).
    branch_obj = Branch.objects.filter(id=branch_id).first() if branch_id else None
    region_obj = Region.objects.filter(id=region_id).first() if region_id else None

    warehouse_obj = Warehouse.objects.filter(id=warehouse_id).first() if warehouse_id else None
    # "All Warehouses" combines every location's stock into one running total
    # (a company-wide feed pipeline view) — the Warehouse column is only
    # shown in that mode so each row's origin/destination stays traceable;
    # with one Warehouse picked, the ledger matches the paper register 1:1.
    all_warehouses = submitted and not warehouse_obj

    if submitted:
        tracked_item_ids = label_ids
        item_label = {iid: iid for iid in label_ids}  # event item_id -> column key (identity: 1 item = 1 column)

        from_date_obj = parse_date(from_date) if from_date else None
        to_date_obj = parse_date(to_date) if to_date else None

        # Scope every event query to the narrowest filter given: a specific
        # Warehouse wins outright; otherwise Branch (via Mapping) or Region
        # (via every Branch in it) narrows to that set of Warehouses; with
        # none of the three, every Warehouse is in scope (None = no filter).
        if warehouse_obj:
            scoped_warehouse_ids = {warehouse_obj.id}
        elif branch_obj:
            scoped_warehouse_ids = set(Mapping.objects.filter(
                type=Mapping.TYPE_SECTOR_BRANCH, to_id=branch_obj.id).values_list("from_id", flat=True))
        elif region_obj:
            branch_ids_in_region = Branch.objects.filter(region_id=region_obj.id).values_list("id", flat=True)
            scoped_warehouse_ids = set(Mapping.objects.filter(
                type=Mapping.TYPE_SECTOR_BRANCH, to_id__in=branch_ids_in_region).values_list("from_id", flat=True))
        else:
            scoped_warehouse_ids = None

        # Warehouse -> Branch, resolved once per warehouse and cached (a
        # Warehouse/Office has no direct Branch FK — only via inventory.
        # Mapping) so "All Warehouses" mode doesn't re-query per row.
        _branch_cache = {}

        def _branch_for_warehouse(wh):
            if not wh:
                return ""
            if wh.id not in _branch_cache:
                branch_id = (Mapping.objects.filter(type=Mapping.TYPE_SECTOR_BRANCH, from_id=wh.id)
                             .values_list("to_id", flat=True).first())
                branch = Branch.objects.filter(id=branch_id).first() if branch_id else None
                _branch_cache[wh.id] = branch.branch_name if branch else ""
            return _branch_cache[wh.id]

        # ---- gather every event ever recorded for the tracked feed items,
        # scoped to one Warehouse, or every Warehouse when none is chosen ----
        events = []
        transfer_qs = StockTransfer.objects.filter(item_id__in=tracked_item_ids)
        transfer_qs = (transfer_qs.filter(Q(from_warehouse_id__in=scoped_warehouse_ids) | Q(to_warehouse_id__in=scoped_warehouse_ids))
                      if scoped_warehouse_ids is not None
                      else transfer_qs.filter(Q(from_warehouse__isnull=False) | Q(to_warehouse__isnull=False)))
        transfer_qs = transfer_qs.select_related("to_farm__farmer", "from_farm__farmer",
                                                  "from_warehouse", "to_warehouse", "to_batch", "from_batch")
        for t in transfer_qs:
            if t.from_warehouse_id and (scoped_warehouse_ids is None or t.from_warehouse_id in scoped_warehouse_ids):
                events.append({
                    "date": t.date, "sort_key": (t.date, 0, t.id), "kind": "dispatch", "source": "dispatch",
                    "item_id": t.item_id,
                    "qty_kg": t.quantity or Decimal("0"), "challan_no": t.dc_no, "txn_no": t.trnum,
                    "warehouse_id": t.from_warehouse_id,
                    "warehouse_name": t.from_warehouse.name, "branch_name": _branch_for_warehouse(t.from_warehouse),
                    "batch_no": t.to_batch.batch_name if t.to_batch_id else "",
                    "farm_code": t.to_farm.farm_code if t.to_farm_id else "",
                    "name": (t.to_farm.farmer.farmer_name if t.to_farm_id and t.to_farm.farmer_id
                             else (t.to_farm.farm_name if t.to_farm_id else "")),
                    "vehicle_no": t.vehicle_no, "freight": None, "remarks": t.remarks,
                })
            if t.to_warehouse_id and (scoped_warehouse_ids is None or t.to_warehouse_id in scoped_warehouse_ids):
                events.append({
                    "date": t.date, "sort_key": (t.date, 1, t.id), "kind": "receipt", "source": "return",
                    "item_id": t.item_id,
                    "qty_kg": t.quantity or Decimal("0"), "challan_no": t.dc_no, "txn_no": t.trnum,
                    "warehouse_id": t.to_warehouse_id,
                    "warehouse_name": t.to_warehouse.name, "branch_name": _branch_for_warehouse(t.to_warehouse),
                    "batch_no": t.from_batch.batch_name if t.from_batch_id else "",
                    "farm_code": t.from_farm.farm_code if t.from_farm_id else "",
                    "name": (t.from_farm.farmer.farmer_name if t.from_farm_id and t.from_farm.farmer_id
                             else (t.from_farm.farm_name if t.from_farm_id else "")),
                    "vehicle_no": t.vehicle_no, "freight": None, "remarks": t.remarks,
                })

        purchase_qs = GeneralPurchaseItem.objects.filter(item_id__in=tracked_item_ids)
        purchase_qs = (purchase_qs.filter(farm_warehouse_id__in=scoped_warehouse_ids) if scoped_warehouse_ids is not None
                      else purchase_qs.filter(farm_warehouse__isnull=False))
        purchase_qs = purchase_qs.select_related("purchase__supplier", "farm_warehouse")
        for p in purchase_qs:
            events.append({
                "date": p.purchase.date, "sort_key": (p.purchase.date, 1, -p.id), "kind": "receipt",
                "source": "purchase", "item_id": p.item_id,
                "qty_kg": (p.rcv_qty or Decimal("0")) + (p.free_qty or Decimal("0")),
                "challan_no": p.purchase.dc_no, "txn_no": p.purchase.purchase_no,
                "warehouse_id": p.farm_warehouse_id,
                "warehouse_name": p.farm_warehouse.name, "branch_name": _branch_for_warehouse(p.farm_warehouse),
                "batch_no": "", "farm_code": "",
                "name": p.purchase.supplier.name if p.purchase.supplier_id else "",
                "vehicle_no": p.purchase.vehicle_no, "freight": p.purchase.freight_amount or Decimal("0"),
                "remarks": p.purchase.remarks,
            })

        # ---- Inventory > Transactions: Stock Received / Stock Issued /
        # Inventory Adjustment — all warehouse-scoped (location_type='warehouse'),
        # none of these carry their own running-stock balance either, so
        # they fold into the same from-scratch reconciliation as everything
        # else here. None of these three have a real Challan/DC field (only
        # an auto ERP trnum), so Challan No. is blank and trnum is shown
        # under Transaction No.(ERP) instead.
        from inventory.models import StockReceiveItem, StockIssueItem, InventoryAdjustmentItem

        receive_qs = StockReceiveItem.objects.filter(item_id__in=tracked_item_ids, location_type="warehouse")
        receive_qs = (receive_qs.filter(warehouse_id__in=scoped_warehouse_ids) if scoped_warehouse_ids is not None
                     else receive_qs.filter(warehouse__isnull=False))
        receive_qs = receive_qs.select_related("receive", "warehouse")
        for r in receive_qs:
            events.append({
                "date": r.receive.date, "sort_key": (r.receive.date, 1, -r.id), "kind": "receipt",
                "source": "stock_receive", "item_id": r.item_id, "qty_kg": r.quantity or Decimal("0"),
                "challan_no": "", "txn_no": r.receive.trnum,
                "warehouse_id": r.warehouse_id,
                "warehouse_name": r.warehouse.name, "branch_name": _branch_for_warehouse(r.warehouse),
                "batch_no": "", "farm_code": "",
                "name": "Stock Received" + (f" — {r.remarks}" if r.remarks else ""),
                "vehicle_no": "", "freight": None, "remarks": r.remarks,
            })

        issue_qs = StockIssueItem.objects.filter(item_id__in=tracked_item_ids, location_type="warehouse")
        issue_qs = (issue_qs.filter(warehouse_id__in=scoped_warehouse_ids) if scoped_warehouse_ids is not None
                   else issue_qs.filter(warehouse__isnull=False))
        issue_qs = issue_qs.select_related("issue", "warehouse")
        for s in issue_qs:
            events.append({
                "date": s.issue.date, "sort_key": (s.issue.date, 0, s.id), "kind": "dispatch",
                "source": "stock_issue", "item_id": s.item_id, "qty_kg": s.quantity or Decimal("0"),
                "challan_no": "", "txn_no": s.issue.trnum,
                "warehouse_id": s.warehouse_id,
                "warehouse_name": s.warehouse.name, "branch_name": _branch_for_warehouse(s.warehouse),
                "batch_no": "", "farm_code": "",
                "name": "Stock Issued",
                "vehicle_no": "", "freight": None, "remarks": "",
            })

        adj_qs = InventoryAdjustmentItem.objects.filter(item_id__in=tracked_item_ids,
                                                         adjustment__location_type="warehouse")
        adj_qs = (adj_qs.filter(adjustment__warehouse_id__in=scoped_warehouse_ids) if scoped_warehouse_ids is not None
                 else adj_qs.filter(adjustment__warehouse__isnull=False))
        adj_qs = adj_qs.select_related("adjustment", "adjustment__warehouse")
        for a in adj_qs:
            is_add = a.adjustment_type == "Add"
            events.append({
                "date": a.adjustment.date, "sort_key": (a.adjustment.date, 1 if is_add else 0, a.id),
                "kind": "receipt" if is_add else "dispatch", "source": "adjustment",
                "item_id": a.item_id, "qty_kg": a.quantity or Decimal("0"),
                "challan_no": "", "txn_no": a.adjustment.trnum,
                "warehouse_id": a.adjustment.warehouse_id,
                "warehouse_name": a.adjustment.warehouse.name, "branch_name": _branch_for_warehouse(a.adjustment.warehouse),
                "batch_no": "", "farm_code": "",
                "name": f"Stock Adjustment ({a.adjustment_type})" + (f" — {a.remarks}" if a.remarks else ""),
                "vehicle_no": "", "freight": None, "remarks": a.remarks,
            })
        events.sort(key=lambda e: e["sort_key"])

        def _bags(qty_kg, item):
            return (qty_kg / item.kg_per_bag).quantize(Decimal("0.01")) if item and item.kg_per_bag else Decimal("0")

        # Opening: replay every event strictly before From Date, from the very
        # start of history. With no From Date given there is no opening period
        # at all — opening stays zero and every event falls in the display
        # window below (guard is essential: without it the loop never breaks
        # and replays all events here, then the display loop replays them
        # again, doubling the running balance).
        running_kg = {label: Decimal("0") for label in label_ids}
        if from_date_obj:
            for e in events:
                if e["date"] >= from_date_obj:
                    break
                label = item_label.get(e["item_id"])
                if not label:
                    continue
                running_kg[label] += e["qty_kg"] if e["kind"] == "receipt" else -e["qty_kg"]

        opening_values = [_bags(running_kg[label], label_item.get(label)) for label in label_ids]
        opening = {"values": opening_values, "net": sum(opening_values)}

        # ---- emit rows within the display window, carrying the running balance ----
        # Events sharing the same Date + Challan No. + Warehouse + direction
        # (dispatch/receipt) are one real document covering several feed
        # types (e.g. one delivery challan with Pre-Starter + Starter both
        # on it) and are merged into a single row — each feed type still
        # gets its own column, but the farm/date/challan aren't repeated.
        # Events with a *different* Challan No. stay on their own row even
        # if same-day/same-farm, since they're genuinely separate documents.
        t_dispatched_bags = t_received_bags = t_freight = Decimal("0")
        dispatch_label_totals = [Decimal("0") for _ in label_ids]
        received_label_totals = [Decimal("0") for _ in label_ids]
        total_bag_sum = total_kg_sum = Decimal("0")
        grouped_rows, group_order = {}, []
        for e in events:
            if from_date_obj and e["date"] < from_date_obj:
                continue
            if to_date_obj and e["date"] > to_date_obj:
                continue
            label = item_label.get(e["item_id"])
            if not label:
                continue
            item = label_item.get(label)
            bags = _bags(e["qty_kg"], item)
            is_receipt = e["kind"] == "receipt"
            running_kg[label] += e["qty_kg"] if is_receipt else -e["qty_kg"]
            bag_weight = item.kg_per_bag if item and item.kg_per_bag else Decimal("0")

            if is_receipt:
                t_received_bags += bags
            else:
                t_dispatched_bags += bags
                total_bag_sum += bags
                total_kg_sum += (bags * bag_weight).quantize(Decimal("0.01"))
            if e["freight"]:
                t_freight += e["freight"]
            label_idx = label_ids.index(label)
            if is_receipt:
                received_label_totals[label_idx] += bags
            else:
                dispatch_label_totals[label_idx] += bags

            # Stock Received/Issued/Adjustment have no real Challan No. (blank
            # for all their lines), so grouping on it directly would merge
            # unrelated same-day documents at the same warehouse together.
            # Fall back to the event's own ERP txn_no (unique per document)
            # as the grouping key whenever there's no real challan.
            doc_key = e["challan_no"] or e["txn_no"]
            group_key = (e["date"], doc_key, e["warehouse_name"], is_receipt)
            row = grouped_rows.get(group_key)
            if row is None:
                row = {
                    "date": e["date"], "challan_no": e["challan_no"], "txn_no": e["txn_no"],
                    "warehouse_name": e["warehouse_name"], "branch_name": e["branch_name"], "batch_no": e["batch_no"],
                    "farm_code": e["farm_code"], "name": e["name"],
                    "dispatch_bags": [Decimal("0")] * len(label_ids),
                    "received_bags": [Decimal("0")] * len(label_ids),
                    "total_bag": Decimal("0"), "total_kg": Decimal("0"),
                    "vehicle_no": e["vehicle_no"], "freight": e["freight"], "remarks": e["remarks"],
                    "is_receipt": is_receipt,
                }
                grouped_rows[group_key] = row
                group_order.append(group_key)
            if is_receipt:
                row["received_bags"][label_idx] += bags
            else:
                row["dispatch_bags"][label_idx] += bags
                row["total_bag"] += bags
                row["total_kg"] += (bags * bag_weight).quantize(Decimal("0.01"))
            if e["freight"]:
                row["freight"] = (row["freight"] or Decimal("0")) + e["freight"]
            # Snapshot the running balance as of the latest event folded into
            # this row, so a merged row shows the state after the whole document.
            row["stock_bags"] = [_bags(running_kg[l], label_item.get(l)) for l in label_ids]
            row["net_stock"] = sum(row["stock_bags"])

        ledger_rows = [grouped_rows[k] for k in group_order]

        current_stock_values = [_bags(running_kg[l], label_item.get(l)) for l in label_ids]
        current_net_stock = sum(current_stock_values)
        kpi = {
            "total_dispatched_bags": t_dispatched_bags, "total_received_bags": t_received_bags,
            "net_total_bag_stock": current_net_stock,
            "total_freight": t_freight,
        }
        ledger_totals = {
            "dispatch_bags": dispatch_label_totals, "received_bags": received_label_totals,
            "total_bag": total_bag_sum, "total_kg": total_kg_sum,
            "stock_bags": current_stock_values, "net_stock": current_net_stock,
        }

        # Top feed by |net stock| — all tracked feed columns, ranked by
        # magnitude (a large negative balance is just as noteworthy as a
        # large positive one).
        top_feed = sorted(
            ({"label": label_name[l], "value": v} for l, v in zip(label_ids, current_stock_values)),
            key=lambda x: abs(x["value"]), reverse=True,
        )

        # Warehouse Snapshot: the same combined balance, split back out per
        # Warehouse — only meaningful in All-Warehouses mode (a single
        # Warehouse view already shows its own net stock in the KPI card).
        # Replays every event up to To Date (same cutoff as the ledger's own
        # current balance), keyed by warehouse this time instead of feed type.
        warehouse_snapshot = []
        if all_warehouses:
            wh_running_kg, wh_names, wh_branches = {}, {}, {}
            for e in events:
                if to_date_obj and e["date"] > to_date_obj:
                    continue
                label = item_label.get(e["item_id"])
                if not label:
                    continue
                wh_id = e["warehouse_id"]
                if wh_id not in wh_running_kg:
                    wh_running_kg[wh_id] = {l: Decimal("0") for l in label_ids}
                    wh_names[wh_id] = e["warehouse_name"]
                    wh_branches[wh_id] = e["branch_name"]
                wh_running_kg[wh_id][label] += e["qty_kg"] if e["kind"] == "receipt" else -e["qty_kg"]
            warehouse_snapshot = sorted(
                ({"name": wh_names[wh_id], "branch_name": wh_branches[wh_id],
                  "net_stock": sum(_bags(kg_map[l], label_item.get(l)) for l in label_ids)}
                 for wh_id, kg_map in wh_running_kg.items()),
                key=lambda x: x["name"],
            )

        # Recent Activity: last 7 days from *today*, independent of the report's
        # own date filter. Classified by each event's explicit `source` tag
        # (not kind/freight heuristics) so Stock Received/Issued/Adjustment
        # from Inventory > Transactions land in the right bucket:
        #   dispatched = Stock Transfer dispatch + Stock Issued
        #   received   = Purchase receipt + Stock Received
        #   returned   = Stock Transfer farm return
        #   adjustment = Inventory Adjustment (Add or Deduct)
        today = timezone.localdate()
        week_ago = today - timedelta(days=6)
        recent_dispatched = recent_received = recent_returned = recent_adjustment = Decimal("0")
        for e in events:
            if not (week_ago <= e["date"] <= today):
                continue
            label = item_label.get(e["item_id"])
            if not label:
                continue
            bags = _bags(e["qty_kg"], label_item.get(label))
            if e["source"] in ("dispatch", "stock_issue"):
                recent_dispatched += bags
            elif e["source"] in ("purchase", "stock_receive"):
                recent_received += bags
            elif e["source"] == "return":
                recent_returned += bags
            elif e["source"] == "adjustment":
                recent_adjustment += bags
        recent_activity = {
            "dispatched": recent_dispatched, "received": recent_received,
            "adjustment": recent_adjustment, "returned": recent_returned,
        }

        # Previous-period trend on the 4 headline KPIs — only computable when
        # both dates are given, since "previous period" needs a defined length.
        trend = None
        if from_date_obj and to_date_obj:
            period_days = (to_date_obj - from_date_obj).days + 1
            prev_to = from_date_obj - timedelta(days=1)
            prev_from = prev_to - timedelta(days=period_days - 1)

            prev_dispatched = prev_received = prev_freight = Decimal("0")
            for e in events:
                if not (prev_from <= e["date"] <= prev_to):
                    continue
                label = item_label.get(e["item_id"])
                if not label:
                    continue
                bags = _bags(e["qty_kg"], label_item.get(label))
                if e["kind"] == "dispatch":
                    prev_dispatched += bags
                else:
                    prev_received += bags
                    if e["freight"]:
                        prev_freight += e["freight"]

            prev_running = {label: Decimal("0") for label in label_ids}
            for e in events:
                if e["date"] > prev_to:
                    break
                label = item_label.get(e["item_id"])
                if not label:
                    continue
                prev_running[label] += e["qty_kg"] if e["kind"] == "receipt" else -e["qty_kg"]
            prev_net_stock = sum(_bags(prev_running[l], label_item.get(l)) for l in label_ids)

            def _pct_change(curr, prev):
                if prev:
                    return ((curr - prev) / abs(prev) * 100).quantize(Decimal("0.01"))
                return Decimal("0") if curr == 0 else Decimal("100.00")

            trend = {
                "dispatched": _pct_change(t_dispatched_bags, prev_dispatched),
                "received": _pct_change(t_received_bags, prev_received),
                "net_stock": _pct_change(current_net_stock, prev_net_stock),
                "freight": _pct_change(t_freight, prev_freight),
            }

    return render(request, "feed_dispatch_stock_report.html", {
        "regions": Region.objects.order_by("description"),
        "branches": Branch.objects.order_by("branch_name"),
        "warehouses": Warehouse.objects.order_by("name"),
        "feed_labels": [label_name[l] for l in label_ids],
        "total_columns": total_columns, "opening_label_colspan": opening_label_colspan,
        "region_id": region_id, "branch_id": branch_id, "warehouse_id": warehouse_id,
        "warehouse_obj": warehouse_obj, "all_warehouses": all_warehouses,
        "from_date": from_date, "to_date": to_date,
        "submitted": submitted, "ledger_rows": ledger_rows, "opening": opening, "kpi": kpi,
        "ledger_totals": ledger_totals, "top_feed": top_feed,
        "recent_activity": recent_activity, "trend": trend, "warehouse_snapshot": warehouse_snapshot,
        "export": export,
        "company": CompanyProfile.get_solo(),
    })


# ---------------------------------------------------------------------------
# Chicks Placement (Broiler > Transactions)
# ---------------------------------------------------------------------------
# Not a separate model — chick placement is an ordinary inventory Stock
# Transfer (Warehouse -> Farm/Batch) of a "chicks" category item, per the
# same convention the Batch History Report already relies on. This is a
# purpose-built, simplified front end over that same StockTransfer data
# (Warehouse supplier -> Farm, auto-derived active Batch, item restricted to
# the chicks category) so Broiler users don't have to use the generic
# Inventory > Stock Transfer form's full location-type/item-picker.

def _hatcheries_with_warehouse():
    """Hatchery queryset annotated with `warehouse_id` — its mapped Office,
    looked up from inventory.Mapping (Inventory > Office Mapping) rather
    than a direct FK, so templates can keep reading `h.warehouse_id` as
    before."""
    from django.db.models import OuterRef, Subquery
    from inventory.models import Mapping

    mapped_warehouse = Mapping.objects.filter(
        type=Mapping.TYPE_HATCHERY_OFFICE, from_id=OuterRef("pk")
    ).values("to_id")[:1]
    return Hatchery.objects.order_by("hatchery_name").annotate(
        warehouse_id=Subquery(mapped_warehouse)
    )


@method_decorator(login_required, name="dispatch")
class ChicksPlacementListTemplateView(View):
    def get(self, request):
        return render(request, "chicks_placement_list.html", {
            "warehouses": Warehouse.objects.order_by("name"),
            "farms": BroilerFarm.objects.order_by("farm_name"),
            "chick_items": Item.objects.filter(category__name__icontains="chick").order_by("item_code"),
            "hatcheries": _hatcheries_with_warehouse(),
        })


@method_decorator(login_required, name="dispatch")
class ChicksPlacementFormTemplateView(View):
    def get(self, request):
        return render(request, "chicks_placement_form.html", {
            "warehouses": Warehouse.objects.order_by("name"),
            "farms": BroilerFarm.objects.order_by("farm_name"),
            "chick_items": Item.objects.filter(category__name__icontains="chick").order_by("item_code"),
            "hatcheries": _hatcheries_with_warehouse(),
            "today": timezone.localdate().isoformat(),
        })


# ---------------------------------------------------------------------------
# Growing Charges Master (Rearing Charge)
# ---------------------------------------------------------------------------

GROWING_CHARGE_LIST_CACHE_KEY = "growing_charge_scheme_list"

# related_name -> (child model, ordered field list). Rows round-trip as JSON
# arrays; string fields (incentive_on / grade) stay as text, the rest default 0.
GC_CHILD_SPECS = [
    ("production_cost_incentives", GCProductionCostIncentive, ["from_production_cost", "to_production_cost", "rate_pct"]),
    ("sales_incentives", GCSalesIncentive, ["sale_rate_from", "sale_rate_to", "sales_incentive"]),
    ("mortality_incentives", GCMortalityIncentive, ["from_mortality_pct", "to_mortality_pct", "incentive_value"]),
    ("fcr_incentives", GCFCRIncentive, ["cfcr_limit", "body_weight", "incentive_value"]),
    ("summer_incentives", GCSummerIncentive, ["min_production_cost", "max_production_cost", "incentive_on", "from_production_cost", "to_production_cost", "incentive_rate"]),
    ("production_cost_decentives", GCProductionCostDecentive, ["from_production_cost", "to_production_cost", "rate_pct"]),
    ("mortality_decentives", GCMortalityDecentive, ["from_mortality_pct", "to_mortality_pct", "decentive_value"]),
    ("fcr_recoveries", GCFCRRecovery, ["cfcr_limit", "production_limit", "recovery_rate"]),
    ("farmer_classifications", GCFarmerClassification, ["production_cost_from", "production_to", "grade"]),
]
GC_STRING_ROW_FIELDS = {"incentive_on", "grade"}


@method_decorator(login_required, name="dispatch")
class GrowingChargeSchemeTemplateView(View):
    """Renders the Rearing / Growing Charge master page."""

    def get(self, request):
        context = {
            "regions": Region.objects.order_by("description"),
            "branches": Branch.objects.select_related("region").order_by("branch_name"),
            "medicine_basis_choices": GrowingChargeScheme.MedicineCostBasis.choices,
            "shortage_basis_choices": GrowingChargeScheme.ShortageBasis.choices,
            "summer_incentive_on_choices": GCSummerIncentive.IncentiveOn.choices,
        }
        return render(request, "growing_charge.html", context)


@method_decorator(login_required, name="dispatch")
class GrowingChargeSchemeAPI(BaseAPIView):
    """CRUD API for the Rearing / Growing Charge master with its nested rows."""

    SCALAR_FIELDS = [
        "schema_name", "from_date", "to_date",
        "chick_cost", "feed_cost", "medicine_cost_basis", "medicine_cost",
        "farmer_admin_cost", "management_admin_cost", "std_production_cost",
        "standard_gc_cost", "minimum_gc_cost", "standard_fcr", "standard_mortality",
        "unloading_charges", "maximum_prod_cost", "maximum_rate_incentive",
        "mort_dec_first_week_exceeds", "mort_dec_overall_above", "mort_dec_first_week_value",
        "shortage_basis",
    ]
    CHOICE_FIELDS = {"medicine_cost_basis", "shortage_basis"}
    DECIMAL_FIELDS = {
        "chick_cost", "feed_cost", "medicine_cost", "farmer_admin_cost",
        "management_admin_cost", "std_production_cost", "standard_gc_cost",
        "minimum_gc_cost", "standard_fcr", "standard_mortality", "unloading_charges",
        "maximum_prod_cost", "maximum_rate_incentive", "mort_dec_first_week_exceeds",
        "mort_dec_overall_above", "mort_dec_first_week_value",
    }

    def get(self, request, id: Optional[int] = None) -> JsonResponse:
        try:
            if id:
                scheme = GrowingChargeScheme.objects.select_related("region", "branch").get(id=id)
                data = {f: getattr(scheme, f) for f in self.SCALAR_FIELDS}
                for f in self.DECIMAL_FIELDS:
                    data[f] = str(data[f])
                data["from_date"] = scheme.from_date.isoformat() if scheme.from_date else None
                data["to_date"] = scheme.to_date.isoformat() if scheme.to_date else None
                data.update({
                    "id": scheme.id,
                    "scheme_code": scheme.scheme_code,
                    "region_id": scheme.region_id,
                    "branch_id": scheme.branch_id,
                    "is_active": scheme.is_active,
                    "is_locked": scheme.is_locked,
                })
                for related_name, _model, fields in GC_CHILD_SPECS:
                    rows = list(getattr(scheme, related_name).values(*fields))
                    for row in rows:
                        for k in fields:
                            if k not in GC_STRING_ROW_FIELDS:
                                row[k] = str(row[k])
                    data[related_name] = rows
                return JsonResponse(data)

            cached = self.get_cached_data(GROWING_CHARGE_LIST_CACHE_KEY)
            if cached:
                return JsonResponse(cached, safe=False)

            schemes = []
            for s in GrowingChargeScheme.objects.select_related("branch"):
                schemes.append({
                    "id": s.id,
                    "scheme_code": s.scheme_code,
                    "from_date": s.from_date.strftime("%d.%m.%Y") if s.from_date else "",
                    "to_date": s.to_date.strftime("%d.%m.%Y") if s.to_date else "",
                    "branch_name": s.branch.branch_name if s.branch else "-All-",
                    "schema_name": s.schema_name,
                    "chick_cost": str(s.chick_cost),
                    "feed_cost": str(s.feed_cost),
                    "medicine_cost": str(s.medicine_cost),
                    "farmer_admin_cost": str(s.farmer_admin_cost),
                    "std_production_cost": str(s.std_production_cost),
                    "minimum_gc_cost": str(s.minimum_gc_cost),
                    "standard_fcr": str(s.standard_fcr),
                    "standard_mortality": str(s.standard_mortality),
                    "is_active": s.is_active,
                    "is_locked": s.is_locked,
                })
            self.set_cached_data(GROWING_CHARGE_LIST_CACHE_KEY, schemes)
            return JsonResponse(schemes, safe=False)
        except Exception as e:
            return self.handle_exception(e)

    def _save_children(self, scheme, data):
        """Replace every nested-row set from the posted JSON arrays."""
        for related_name, model, fields in GC_CHILD_SPECS:
            rows = json.loads(data.get(related_name, "[]") or "[]")
            model.objects.filter(scheme=scheme).delete()
            for row in rows:
                kwargs = {}
                blank = True
                for f in fields:
                    val = row.get(f, "")
                    if f in GC_STRING_ROW_FIELDS:
                        kwargs[f] = val or ""
                        if val:
                            blank = False
                    else:
                        kwargs[f] = val if val not in ("", None) else 0
                        if val not in ("", None, "0", "0.00", 0):
                            blank = False
                if blank:
                    continue
                model.objects.create(scheme=scheme, **kwargs)

    def post(self, request, id: Optional[int] = None) -> JsonResponse:
        try:
            data = request.POST
            with transaction.atomic():
                scheme = GrowingChargeScheme.objects.get(id=id) if id else GrowingChargeScheme()
                if id and scheme.is_locked:
                    return JsonResponse({"error": "This scheme is locked."}, status=400)

                scheme.region = Region.objects.get(id=data["region_id"])
                branch_id = data.get("branch_id")
                scheme.branch = Branch.objects.get(id=branch_id) if branch_id else None

                for field in self.SCALAR_FIELDS:
                    if field in data:
                        value = data[field]
                        if value == "" and field in self.DECIMAL_FIELDS:
                            value = 0
                        setattr(scheme, field, value)

                scheme.full_clean(exclude=["scheme_code"])
                scheme.save()

                self._save_children(scheme, data)
                cache.delete(GROWING_CHARGE_LIST_CACHE_KEY)
            return JsonResponse(
                {"message": "Scheme updated" if id else "Scheme created", "id": scheme.id},
                status=200 if id else 201,
            )
        except Exception as e:
            return self.handle_exception(e)

    def delete(self, request, id: int) -> JsonResponse:
        try:
            scheme = GrowingChargeScheme.objects.get(id=id)
            if scheme.is_locked:
                return JsonResponse({"error": "This scheme is locked."}, status=400)
            with transaction.atomic():
                scheme.delete()
                cache.delete(GROWING_CHARGE_LIST_CACHE_KEY)
            return JsonResponse({"message": "Scheme deleted"})
        except Exception as e:
            return self.handle_exception(e)


@login_required
def growing_charge_duplicate(request, id):
    """Clone a scheme (header + all nested rows) into a new draft record."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=400)
    try:
        src = GrowingChargeScheme.objects.get(id=id)
    except GrowingChargeScheme.DoesNotExist:
        return JsonResponse({"error": "Scheme not found."}, status=404)
    with transaction.atomic():
        children = [(rn, m, list(getattr(src, rn).all())) for rn, m, _f in GC_CHILD_SPECS]
        clone = src
        clone.pk = None
        clone.scheme_code = ""
        clone.schema_name = f"{src.schema_name} (Copy)"
        clone.is_locked = False
        clone._state.adding = True
        clone.save()
        for related_name, model, rows in children:
            for row in rows:
                row.pk = None
                row.scheme = clone
                row._state.adding = True
                row.save()
        cache.delete(GROWING_CHARGE_LIST_CACHE_KEY)
    return JsonResponse({"message": "Scheme duplicated", "id": clone.id}, status=201)


@login_required
def toggle_growing_charge_active(request, id):
    """Toggle a scheme's active/inactive status."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=400)
    try:
        scheme = GrowingChargeScheme.objects.get(id=id)
        if scheme.is_locked:
            return JsonResponse({"error": "This scheme is locked."}, status=400)
        scheme.is_active = not scheme.is_active
        scheme.save(update_fields=["is_active"])
        cache.delete(GROWING_CHARGE_LIST_CACHE_KEY)
        return JsonResponse({"message": "Scheme updated", "is_active": scheme.is_active})
    except GrowingChargeScheme.DoesNotExist:
        return JsonResponse({"error": "Scheme not found."}, status=404)


@login_required
def toggle_growing_charge_lock(request, id):
    """Toggle a scheme's locked status."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=400)
    try:
        scheme = GrowingChargeScheme.objects.get(id=id)
        scheme.is_locked = not scheme.is_locked
        scheme.save(update_fields=["is_locked"])
        cache.delete(GROWING_CHARGE_LIST_CACHE_KEY)
        return JsonResponse({"message": "Scheme updated", "is_locked": scheme.is_locked})
    except GrowingChargeScheme.DoesNotExist:
        return JsonResponse({"error": "Scheme not found."}, status=404)


# ---------------------------------------------------------------------------
# Farmer Growing Charge Settlement / Batch Closing (Broiler > Growing Charges)
# ---------------------------------------------------------------------------
# The "Add Rearing Charges" transaction. Auto-loads a batch's computed figures
# from the same engine the Growing Charge Statement report uses
# (_build_batch_report), applies the scheme's incentive/deduction slabs to
# arrive at a Farmer Payable, and — on save — closes the batch. Every field is
# override-able, so the slab units/chain below are sensible defaults, not a
# hard contract (see the plan's Notes/risks).

FEED_KG_PER_BAG = Decimal("50")  # feed items are 50kg/bag across this system

# Manual-entry fields (not slab-derived): default 0 on autofill, user fills.
GC_SETTLEMENT_MANUAL_FIELDS = [
    "other_incentives", "ifft_charges", "farmer_sales_deduction", "feed_transfer_charges",
    "vaccinator_charges", "transportation_charges", "other_deductions", "equipment_charges",
    "advance_deductions",
]
# Every persisted numeric field the POST accepts (the client sends final values;
# the server recomputes the authoritative running totals from them on save).
GC_SETTLEMENT_INPUT_FIELDS = GC_SETTLEMENT_MANUAL_FIELDS + [
    "standard_growing_charges", "actual_growing_charges", "sales_incentives",
    "mortality_incentives", "fcr_incentives", "summer_incentives",
    "birds_shortage_rate", "birds_shortage_amount", "fcr_deduction", "mortality_deduction",
]


def _num(x):
    """Coerce a batch_costing value (Decimal, int, or the 'No Data' string used
    when no scheme matches) to a Decimal — 'No Data'/blank become 0."""
    if x is None or x == "No Data" or x == "":
        return Decimal("0")
    return x if isinstance(x, Decimal) else Decimal(str(x))


def _slab_match(rows, value, lo_attr, hi_attr, val_attr):
    """First row whose [lo, hi] band contains ``value`` → its ``val_attr`` (0 if none)."""
    v = _num(value)
    for r in rows:
        if _num(getattr(r, lo_attr)) <= v <= _num(getattr(r, hi_attr)):
            return _num(getattr(r, val_attr))
    return Decimal("0")


def _actual_gc_rate(scheme, std_cost, actual_cost, base_rate):
    """Actual Growing Charge rate (Rs./kg): the standard GC rate adjusted by the
    gap between the batch's actual production cost/kg and the scheme's standard
    production cost, spread PROGRESSIVELY across the per-rupee Production-Cost
    slab bands (tax-bracket style).

    actual > std -> decentive bands (ascending, keyed on to_production_cost):
        each ₹ segment of the excess above std, up to that band's ceiling, is
        multiplied by band.rate_pct/100 and SUBTRACTED.
    actual < std -> incentive bands (descending, keyed on from_production_cost):
        each ₹ segment of the shortfall below std is multiplied by rate_pct/100
        and ADDED.

    e.g. std=90, actual=91.89, both bands 50%: (1.00 + 0.89) tiered ->
        1.00*0.5 + 0.89*0.5 = 0.945 subtracted, so 7.50 -> 6.555.
    """
    if not scheme or std_cost <= 0:
        return base_rate
    adj = Decimal("0")
    if actual_cost > std_cost:
        decentives = sorted(scheme.production_cost_decentives.all(),
                            key=lambda r: _num(r.to_production_cost))
        # Beyond the highest defined decentive slab, the growing charge is
        # wiped entirely (production cost too high -> no GC).
        if decentives and actual_cost > _num(decentives[-1].to_production_cost):
            return Decimal("0")
        prev = std_cost
        for band in decentives:
            top = _num(band.to_production_cost)
            if top <= std_cost:
                continue
            seg = min(actual_cost, top) - prev
            if seg <= 0:
                break
            adj -= seg * _num(band.rate_pct) / Decimal("100")
            prev = top
            if prev >= actual_cost:
                break
    elif actual_cost < std_cost:
        # Incentive accrues only through the defined slabs; below the lowest
        # one the bonus is capped at the first slab (no further increase).
        prev = std_cost
        for band in sorted(scheme.production_cost_incentives.all(),
                           key=lambda r: _num(r.from_production_cost), reverse=True):
            bottom = _num(band.from_production_cost)
            if bottom >= std_cost:
                continue
            seg = prev - max(actual_cost, bottom)
            if seg <= 0:
                break
            adj += seg * _num(band.rate_pct) / Decimal("100")
            prev = bottom
            if prev <= actual_cost:
                break
    # GC rate never goes negative.
    return max(Decimal("0"), base_rate + adj)


def _sales_incentive_per_kg(scheme, avg_sale_rate):
    """Sales incentive per kg of sold weight. The slab's ``sales_incentive`` is
    a rate PER RUPEE of sale rate above the band floor, accrued progressively
    across bands (like the growing-charge tiers): e.g. band 105-140 @ 0.10 and
    a ₹115 sale rate -> (115-105) x 0.10 = ₹1.00/kg. Below the lowest band's
    floor there is no incentive; above the highest band's ceiling it caps."""
    if not scheme:
        return Decimal("0")
    v = _num(avg_sale_rate)
    per_kg = Decimal("0")
    for band in sorted(scheme.sales_incentives.all(), key=lambda r: _num(r.sale_rate_from)):
        lo, hi, rate = _num(band.sale_rate_from), _num(band.sale_rate_to), _num(band.sales_incentive)
        if v <= lo:
            break
        per_kg += (min(v, hi) - lo) * rate
        if v <= hi:
            break
    return per_kg


def _shortage_rate(scheme, bc):
    """Per-bird shortage recovery rate per the scheme's shortage_basis."""
    if not scheme:
        return Decimal("0")
    basis = scheme.shortage_basis
    prod = _num(bc.get("production_cost_per_kg"))
    std_prod = _num(bc.get("std_prod_per_kg"))
    avg_rate = _num(bc.get("avg_sale_rate"))
    B = GrowingChargeScheme.ShortageBasis
    if basis == B.STD_PRODUCTION_COST:
        return std_prod
    if basis == B.PRODUCTION_COST:
        return prod
    if basis == B.AVG_SALE_RATE:
        return avg_rate
    if basis == B.MAX_SALE_RATE:
        return avg_rate  # no per-sale max tracked; avg is the best available proxy
    return max(std_prod, prod, avg_rate)  # WHICH_IS_HIGHER


def _gc_settlement_autofill(batch, scheme):
    """All settlement field defaults for a batch, keyed by the model's field
    names. Read-only figures come from _build_batch_report; incentive/deduction
    defaults from the scheme's slab tables. Returns Decimals."""
    report = _build_batch_report(batch, fetch_type="farmer", scheme_override=scheme)
    bc = report["batch_costing"]
    q2 = Decimal("0.01")

    # Final liquidation = the LAST bird-sale date; GC closing defaults to the
    # day after it (editable in the form).
    sale_dates = [r["date"] for r in report.get("bird_sales", []) if r.get("date")]
    last_sale_date = max(sale_dates) if sale_dates else bc.get("sale_start_date")
    gc_date_default = (last_sale_date + timedelta(days=1)) if last_sale_date else None

    sold_weight = _num(bc.get("sold_weight"))
    sold_birds = _num(bc.get("sold_birds"))
    placed = _num(bc.get("chicks_placed"))
    live_birds = placed - _num(bc.get("mortality")) - _num(bc.get("culls"))

    # ---- slab-derived incentives (treated as per-kg of sold live weight,
    #      except summer which is per-bird on its `incentive_on` basis) ----
    if scheme:
        sales_rate = _sales_incentive_per_kg(scheme, bc.get("avg_sale_rate"))
        mort_rate = _slab_match(scheme.mortality_incentives.all(), bc.get("total_mort_pct"),
                                "from_mortality_pct", "to_mortality_pct", "incentive_value")
        fcr_rate = _slab_match(scheme.fcr_incentives.all(), bc.get("cfcr"),
                               "cfcr_limit", "cfcr_limit", "incentive_value") \
            if scheme.fcr_incentives.exists() else Decimal("0")
        # FCR incentive slab is a limit, not a band: reward when CFCR <= limit.
        fcr_rate = Decimal("0")
        for r in scheme.fcr_incentives.all().order_by("cfcr_limit"):
            if _num(bc.get("cfcr")) <= _num(r.cfcr_limit):
                fcr_rate = _num(r.incentive_value)
                break

        summer_amount = Decimal("0")
        for r in scheme.summer_incentives.all():
            if _num(r.from_production_cost) <= _num(bc.get("production_cost_per_kg")) <= _num(r.to_production_cost):
                basis_birds = {"sold_birds": sold_birds, "placed_birds": placed,
                               "live_birds": live_birds}.get(r.incentive_on, sold_birds)
                summer_amount = _num(r.incentive_rate) * basis_birds
                break

        sales_incentives = (sales_rate * sold_weight)
        mortality_incentives = (mort_rate * sold_weight)
        fcr_incentives = (fcr_rate * sold_weight)
        summer_incentives = summer_amount

        # ---- slab-derived deductions ----
        fcr_recovery_rate = Decimal("0")
        for r in scheme.fcr_recoveries.all().order_by("cfcr_limit"):
            if _num(bc.get("cfcr")) >= _num(r.cfcr_limit):
                fcr_recovery_rate = _num(r.recovery_rate)
        fcr_deduction = fcr_recovery_rate * sold_weight
        mort_dec_rate = _slab_match(scheme.mortality_decentives.all(), bc.get("total_mort_pct"),
                                    "from_mortality_pct", "to_mortality_pct", "decentive_value")
        mortality_deduction = mort_dec_rate * sold_weight

        # ---- Standard vs Actual GC ----
        # Standard GC rate (Rs./kg) comes from the master; the Actual GC rate
        # adjusts it by how far the batch's actual production cost/kg is from the
        # scheme's standard production cost, distributed PROGRESSIVELY across the
        # per-rupee Production-Cost slab bands (like tax brackets):
        #   actual > std  -> walk the decentive bands upward, subtract each
        #                    segment x (band rate/100) from the GC rate
        #   actual < std  -> walk the incentive bands downward, add each segment
        # Amounts are rate x sold weight.
        std_gc_rate = _num(bc.get("base_gc_rate"))               # scheme.standard_gc_cost
        std_cost = _num(bc.get("std_prod_per_kg"))               # scheme.std_production_cost
        actual_cost = _num(bc.get("production_cost_per_kg"))
        actual_gc_rate = _actual_gc_rate(scheme, std_cost, actual_cost, std_gc_rate)
        # Standard + Incentive/Decentive = Actual (the net the farmer is paid).
        incdec_rate = actual_gc_rate - std_gc_rate               # +ve incentive, -ve decentive
        standard_gc = std_gc_rate * sold_weight
        gc_incdec = incdec_rate * sold_weight
        actual_gc = actual_gc_rate * sold_weight
    else:
        sales_incentives = mortality_incentives = fcr_incentives = summer_incentives = Decimal("0")
        fcr_deduction = mortality_deduction = standard_gc = actual_gc = Decimal("0")
        std_gc_rate = incdec_rate = actual_gc_rate = gc_incdec = Decimal("0")

    shortage_birds = _num(bc.get("shortage_birds"))
    shortage_rate = _shortage_rate(scheme, bc)
    shortage_amount = shortage_rate * shortage_birds

    data = {
        "placement_date": bc.get("placement_date"),
        "liquidation_date": last_sale_date,
        "gc_date_default": gc_date_default,
        # Bird details
        "placed_birds": placed, "mortality": _num(bc.get("mortality")),
        "sold_birds": sold_birds, "sold_weight": sold_weight,
        "excess": _num(bc.get("excess_birds")), "shortage": shortage_birds,
        "sale_amount": _num(bc.get("sold_amount")), "sale_rate": _num(bc.get("avg_sale_rate")),
        "age": _num(bc.get("mean_age")),
        # Performance
        "first_week_mortality_pct": _num(bc.get("first_week_mort_pct")),
        "days30_mortality_pct": _num(bc.get("upto_30_mort_pct")),
        "after30_mortality_pct": _num(bc.get("after_30_mort_pct")),
        "total_mortality_pct": _num(bc.get("total_mort_pct")),
        "fcr": _num(bc.get("fcr")), "cfcr": _num(bc.get("cfcr")),
        "avg_weight": _num(bc.get("avg_body_weight")), "mean_age": _num(bc.get("mean_age")),
        "day_gain": _num(bc.get("day_gain")), "eef": _num(bc.get("eef")),
        "grade": bc.get("grade") if bc.get("grade") not in (None, "No Data") else "",
        # Feed / medicine
        "feed_in": _num(bc.get("feed_sent")), "feed_consumption": _num(bc.get("feed_consumed")),
        "feed_out": _num(bc.get("feed_return")),
        "feed_balance": _num(bc.get("feed_sent")) - _num(bc.get("feed_consumed")) - _num(bc.get("feed_return")),
        "med_transfer_in": _num(bc.get("med_sent")), "med_consumption": _num(bc.get("med_consumed")),
        "med_transfer_out": _num(bc.get("med_return")),
        "med_closing": _num(bc.get("med_sent")) - _num(bc.get("med_consumed")) - _num(bc.get("med_return")),
        # Costing (per-unit = per kg of sold live weight)
        "chick_cost": _num(bc.get("chick_cost")), "chick_cost_per_unit": _div(_num(bc.get("chick_cost")), sold_weight),
        "feed_cost": _num(bc.get("feed_cost")), "feed_cost_per_unit": _div(_num(bc.get("feed_cost")), sold_weight),
        "admin_cost": _num(bc.get("admin_cost")), "admin_cost_per_unit": _div(_num(bc.get("admin_cost")), sold_weight),
        "medicine_cost": _num(bc.get("med_cost")), "medicine_cost_per_unit": _div(_num(bc.get("med_cost")), sold_weight),
        "total_cost": _num(bc.get("total_production_cost")),
        "total_cost_per_unit": _num(bc.get("production_cost_per_kg")),
        # Production Cost is quoted per kg of live weight (Rs./kg) — standard
        # comes from the scheme's per-kg rate, actual is this batch's own
        # per-kg cost (== Total Cost's per-unit).
        "standard_production_cost": _num(bc.get("std_prod_per_kg")),
        "actual_production_cost": _num(bc.get("production_cost_per_kg")),
        # Rearing charges (incentives) — Standard + Incentive/Decentive = Actual
        "standard_growing_charges": standard_gc, "gc_incentive_decentive": gc_incdec,
        "actual_growing_charges": actual_gc,
        # per-kg rates for the "Rs." column of the three GC rows
        "std_gc_rate": std_gc_rate, "gc_incdec_rate": incdec_rate, "actual_gc_rate": actual_gc_rate,
        "sales_incentives": sales_incentives, "mortality_incentives": mortality_incentives,
        "fcr_incentives": fcr_incentives, "summer_incentives": summer_incentives,
        # Deductions (slab-derived)
        "birds_shortage_rate": shortage_rate, "birds_shortage_amount": shortage_amount,
        "fcr_deduction": fcr_deduction, "mortality_deduction": mortality_deduction,
    }
    for f in GC_SETTLEMENT_MANUAL_FIELDS:
        data[f] = Decimal("0")

    # Farmer sales deduction: birds this farmer bought from the batch
    # (sale_type='farmer') that are still UNPAID — i.e. the batch's farmer
    # bird-sale amount capped by the farmer's overall unpaid balance
    # (total farmer sales minus receipts; receipts aren't batch-scoped).
    # Auto-picked here; still editable on the form.
    from django.db.models import Sum
    farmer = batch.broiler_farm.farmer
    Z = Decimal("0")

    def _sum(qs):
        return qs.aggregate(t=Sum("amount"))["t"] or Z

    batch_farmer_sales = _sum(BirdSale.objects.filter(batch=batch, sale_type="farmer", farmer=farmer))
    total_farmer_sales = _sum(BirdSale.objects.filter(sale_type="farmer", farmer=farmer))
    total_farmer_receipts = _sum(BirdSaleReceipt.objects.filter(sale_type="farmer", farmer=farmer))
    unpaid = total_farmer_sales - total_farmer_receipts
    data["farmer_sales_deduction"] = max(Z, min(batch_farmer_sales, unpaid))

    # Running totals (recomputed identically on save from whatever values stand).
    data.update(_gc_settlement_totals(data, sold_birds, sold_weight))
    return {k: (v.quantize(q2) if isinstance(v, Decimal) else v) for k, v in data.items()}


def _gc_settlement_totals(d, sold_birds, sold_weight):
    """The dependent running totals of the settlement, from the current field
    values — the single source of truth used by both autofill and save."""
    g = lambda k: _num(d.get(k))
    total_incentives = (g("sales_incentives") + g("mortality_incentives") + g("fcr_incentives")
                        + g("summer_incentives") + g("other_incentives") + g("ifft_charges"))
    total_deduction = g("birds_shortage_amount") + g("fcr_deduction") + g("mortality_deduction")
    amount_payable = g("actual_growing_charges") + total_incentives - total_deduction
    total_amount_payable = (amount_payable - g("farmer_sales_deduction") - g("feed_transfer_charges")
                            - g("vaccinator_charges") - g("other_deductions") + g("transportation_charges"))
    tds = (total_amount_payable * Decimal("0.01"))
    farmer_payable = total_amount_payable - tds - g("equipment_charges") - g("advance_deductions")
    return {
        "total_incentives": total_incentives,
        "gc_paid_per_kg": _div(g("actual_growing_charges"), _num(sold_weight)),
        "total_deduction": total_deduction,
        "amount_payable": amount_payable,
        "total_amount_payable": total_amount_payable,
        "tds": tds,
        "farmer_payable": farmer_payable,
        "per_bird_cost": _div(farmer_payable, _num(sold_birds)),
    }


@method_decorator(login_required, name="dispatch")
class GCSettlementTemplateView(View):
    """Renders the Farmer GC Settlement / batch-closing form page."""

    def get(self, request):
        return render(request, "gc_settlement_form.html", {
            "farms": BroilerFarm.objects.select_related("branch", "supervisor").order_by("farm_name"),
            "today": timezone.localdate().isoformat(),
        })


@login_required
def gc_settlement_batches(request):
    """Open (not-yet-closed) batches for a farm, for the Batch dropdown."""
    farm_id = (request.GET.get("farm") or "").strip()
    if not farm_id:
        return JsonResponse([], safe=False)
    batches = (BroilerBatch.objects.filter(broiler_farm_id=farm_id, is_closed=False)
               .order_by("-start_date", "-id"))
    return JsonResponse([{"id": b.id, "batch_name": b.batch_name} for b in batches], safe=False)


@login_required
def gc_settlement_schemes(request):
    """Schemes whose date range covers the batch's placement date (region
    matched), plus the auto-matched one — for the Scheme Name dropdown."""
    batch_id = (request.GET.get("batch") or "").strip()
    batch = BroilerBatch.objects.select_related("broiler_farm__branch").filter(id=batch_id).first()
    if not batch:
        return JsonResponse({"schemes": [], "selected": None}, safe=False)
    placement = batch.start_date
    region_id = batch.broiler_farm.branch.region_id
    qs = GrowingChargeScheme.objects.filter(region_id=region_id, is_active=True)
    if placement:
        qs = qs.filter(from_date__lte=placement, to_date__gte=placement)
    matched = _match_growing_charge_scheme(batch, placement)
    return JsonResponse({
        "schemes": [{"id": s.id, "name": f"{s.scheme_code} - {s.schema_name}"}
                    for s in qs.order_by("schema_name")],
        "selected": matched.id if matched else None,
    })


@login_required
def gc_settlement_autofill_api(request):
    """All auto-computed settlement figures for a batch + scheme, as JSON."""
    batch_id = (request.GET.get("batch") or "").strip()
    scheme_id = (request.GET.get("scheme") or "").strip()
    batch = (BroilerBatch.objects
             .select_related("broiler_farm__branch", "broiler_farm__supervisor")
             .filter(id=batch_id).first())
    if not batch:
        return JsonResponse({"error": "Batch not found"}, status=404)
    if batch.is_closed:
        return JsonResponse({"error": "This batch is already closed/settled."}, status=400)
    scheme = GrowingChargeScheme.objects.filter(id=scheme_id).first() if scheme_id.isdigit() else \
        _match_growing_charge_scheme(batch, batch.start_date)

    farm = batch.broiler_farm
    data = _gc_settlement_autofill(batch, scheme)
    out = {}
    for k, v in data.items():
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        elif isinstance(v, Decimal):
            out[k] = str(v)
        else:
            out[k] = v
    out.update({
        "branch": farm.branch.branch_name if farm.branch_id else "",
        "line": farm.line or "",
        "supervisor": str(farm.supervisor) if farm.supervisor_id else "",
        "batch_name": batch.batch_name,
        "scheme_id": scheme.id if scheme else None,
        "scheme_name": (f"{scheme.scheme_code} - {scheme.schema_name}") if scheme else "",
        "kg_per_bag": str(FEED_KG_PER_BAG),
    })
    return JsonResponse(out)


@method_decorator(login_required, name="dispatch")
class GCSettlementAPI(View):
    """List / retrieve / create / delete Farmer GC settlements."""

    def get(self, request, id=None):
        if id:
            s = get_object_or_404(GrowingChargeSettlement.objects.select_related(
                "batch__broiler_farm", "farm", "scheme"), id=id)
            return JsonResponse(_gc_settlement_detail(s))
        rows = (GrowingChargeSettlement.objects
                .select_related("batch__broiler_farm", "farm", "scheme").order_by("-gc_date", "-id"))
        from_date = (request.GET.get("from_date") or "").strip()
        to_date = (request.GET.get("to_date") or "").strip()
        if from_date:
            rows = rows.filter(gc_date__gte=from_date)
        if to_date:
            rows = rows.filter(gc_date__lte=to_date)
        def fmt(d):
            return d.strftime("%d.%m.%Y") if d else ""
        return JsonResponse([{
            "id": s.id,
            "closed_date": fmt(timezone.localtime(s.created_at).date() if s.created_at else None),
            "settlement_code": s.settlement_code,
            "gc_date": fmt(s.gc_date),
            "farm_name": s.farm.farm_name, "batch_name": s.batch.batch_name,
            "start_date": fmt(s.placement_date or s.batch.start_date),
            "liquidation_date": fmt(s.liquidation_date),
            "gc_amount": str(s.farmer_payable),
            "grade": s.grade or "-",
        } for s in rows], safe=False)

    @transaction.atomic
    def post(self, request):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        batch = (BroilerBatch.objects.select_related("broiler_farm")
                 .filter(id=data.get("batch")).first())
        if not batch:
            return JsonResponse({"error": "Select a Batch."}, status=400)
        if batch.is_closed or GrowingChargeSettlement.objects.filter(batch=batch).exists():
            return JsonResponse({"error": "This batch is already settled/closed."}, status=400)

        scheme = GrowingChargeScheme.objects.filter(id=data.get("scheme")).first()
        gc_date = timezone.datetime.fromisoformat(data["gc_date"]).date() if data.get("gc_date") \
            else timezone.localdate()

        # Start from a fresh autofill (authoritative read-only figures), then
        # overlay the user's editable inputs, then recompute the running totals.
        fields = _gc_settlement_autofill(batch, scheme)
        for f in GC_SETTLEMENT_INPUT_FIELDS:
            if f in data and data[f] not in (None, ""):
                fields[f] = Decimal(str(data[f]))
        sold_birds = fields.get("sold_birds") or Decimal("0")
        sold_weight = fields.get("sold_weight") or Decimal("0")
        fields.update(_gc_settlement_totals(fields, sold_birds, sold_weight))

        settlement = GrowingChargeSettlement(
            batch=batch, farm=batch.broiler_farm, scheme=scheme,
            gc_date=gc_date, remarks=data.get("remarks") or "", created_by=request.user,
        )
        model_field_names = {f.name for f in GrowingChargeSettlement._meta.get_fields()}
        for k, v in fields.items():
            if k in model_field_names:
                setattr(settlement, k, v)
        settlement.save()

        # Close the batch.
        batch.is_closed = True
        batch.closed_on = gc_date
        if not batch.end_date:
            batch.end_date = gc_date
        batch.save(update_fields=["is_closed", "closed_on", "end_date"])

        return JsonResponse({"message": "Settlement saved and batch closed",
                             "id": settlement.id, "code": settlement.settlement_code}, status=201)

    @transaction.atomic
    def put(self, request, id):
        s = get_object_or_404(GrowingChargeSettlement, id=id)
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)
        # Editing only touches the manual/override inputs + gc_date/remarks; the
        # auto-computed read-only figures stay as stored. Totals recompute from
        # the current stored values overlaid with the edited inputs.
        fields = {f.name: getattr(s, f.name) for f in GrowingChargeSettlement._meta.fields}
        for f in GC_SETTLEMENT_INPUT_FIELDS:
            if f in data and data[f] not in (None, ""):
                fields[f] = Decimal(str(data[f]))
        totals = _gc_settlement_totals(fields, s.sold_birds, s.sold_weight)
        for k, v in {**{f: fields[f] for f in GC_SETTLEMENT_INPUT_FIELDS}, **totals}.items():
            setattr(s, k, v)
        if data.get("gc_date"):
            s.gc_date = timezone.datetime.fromisoformat(data["gc_date"]).date()
        s.remarks = data.get("remarks", s.remarks) or ""
        s.save()
        return JsonResponse({"message": "Settlement updated", "id": s.id, "code": s.settlement_code})

    @transaction.atomic
    def delete(self, request, id):
        s = get_object_or_404(GrowingChargeSettlement.objects.select_related("batch"), id=id)
        batch = s.batch
        # Reopen the batch — clear the end/closed marks the settlement set so
        # the flock counts as live again.
        s.delete()
        batch.is_closed = False
        batch.closed_on = None
        batch.end_date = None
        batch.save(update_fields=["is_closed", "closed_on", "end_date"])
        return JsonResponse({"message": "Settlement deleted and batch reopened"})


def _gc_settlement_detail(s):
    """Full field dict of a saved settlement (all numeric fields as strings)."""
    farm = s.farm
    out = {"id": s.id, "settlement_code": s.settlement_code,
           "farm_id": s.farm_id, "batch_id": s.batch_id, "scheme_id": s.scheme_id,
           "farm_name": farm.farm_name, "batch_name": s.batch.batch_name,
           "scheme_name": (f"{s.scheme.scheme_code} - {s.scheme.schema_name}") if s.scheme_id else "",
           "branch": farm.branch.branch_name if farm.branch_id else "",
           "line": farm.line or "", "supervisor": str(farm.supervisor) if farm.supervisor_id else "",
           "gc_date": s.gc_date.isoformat() if s.gc_date else "",
           "placement_date": s.placement_date.isoformat() if s.placement_date else "",
           "liquidation_date": s.liquidation_date.isoformat() if s.liquidation_date else "",
           "grade": s.grade, "remarks": s.remarks}
    for f in GrowingChargeSettlement._meta.get_fields():
        val = getattr(s, f.name, None)
        if isinstance(val, Decimal):
            out[f.name] = str(val)
        elif isinstance(val, int) and not isinstance(val, bool):
            out[f.name] = val
    return out


@login_required
def gc_settlement_print(request, id):
    """Farmer-facing printable Growing Charges / Batch Closing report for a
    saved settlement (the "Shalimar" field set). Shows performance + the
    farmer's growing-charge payment breakdown ONLY — no company revenue,
    profitability or margin (in contract growing the company owns/sells the
    birds; the farmer is paid growing charges)."""
    from account.models import CompanyProfile
    s = get_object_or_404(GrowingChargeSettlement.objects.select_related(
        "batch__broiler_farm__branch", "batch__broiler_farm__supervisor",
        "batch__broiler_farm__farmer", "scheme"), id=id)
    batch = s.batch
    farm = batch.broiler_farm

    sw = s.sold_weight or Decimal("0")
    sb = Decimal(str(s.sold_birds or 0))
    q3 = Decimal("0.001")

    def rate(amount, by):
        return (Decimal(str(amount)) / by).quantize(q3) if by else Decimal("0")

    # Derived per-kg / per-bird rearing-charge rates (not stored on the model).
    d = {
        "rc_per_kg": rate(s.actual_growing_charges, sw),           # Rearing Charges/Kg
        "std_rc_per_kg": rate(s.standard_growing_charges, sw),     # Std Rearing Charges/Kg
        "prod_cost_incentive_rate": rate(s.gc_incentive_decentive, sw),  # Prod Cost Incentives
        "rc_per_bird": rate(s.actual_growing_charges, sb),         # Rearing Charges/Bird
        "std_fcr": s.scheme.standard_fcr if s.scheme_id else None,
        # net earning (+) / deduction (-) for the FCR & mortality lines
        "fcr_net": s.fcr_incentives - s.fcr_deduction,
        "mortality_net": s.mortality_incentives - s.mortality_deduction,
    }
    return render(request, "gc_settlement_print.html", {
        "s": s, "batch": batch, "farm": farm, "farmer": farm.farmer,
        "supervisor": farm.supervisor, "branch": farm.branch, "scheme": s.scheme,
        "company": CompanyProfile.get_solo(), "d": d,
    })
