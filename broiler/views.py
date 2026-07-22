#pylint: disable=no-member

from typing import Dict, List, Optional, Union
from django.shortcuts import render
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
    GCFCRRecovery, GCFarmerClassification, MedicineVaccineEntry,
    Region, Supervisor,
)
from account.models import ChartOfAccount
from inventory.models import Item, Warehouse
from sales.models import Customer
from hatchery_master.models import Hatchery
from decimal import Decimal, ROUND_HALF_UP
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

                BreedStandard.objects.create(
                    breed=breed,
                    age=age,
                    body_weight=body_weight,
                    feed_intake=feed_intake,
                    avg_daily_gain=_to_decimal(row.get("avg_daily_gain")),
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
        context = {"broiler_farms": broiler_farms}
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
                    "broiler_farm_name": broiler_batch.broiler_farm.farm_name,
                })

            cache_key = "broiler_batch_list"
            cached_data = self.get_cached_data(cache_key)
            if cached_data:
                return JsonResponse(cached_data, safe=False)

            broiler_batches = list(
                BroilerBatch.objects.select_related("broiler_farm")
                .annotate(broiler_farm_name=F("broiler_farm__farm_name"))
                .values("id", "batch_name", "book_number", "lot_no", "broiler_farm_name")
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
                    "sheds": list(broiler_farm.sheds.values("id", "shed_no", "dimensions", "sq_feet")),
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
        """Replace this farm's sheds with the rows submitted from the form."""
        sheds = json.loads(sheds_json) if sheds_json else []
        broiler_farm.sheds.all().delete()
        for shed in sheds:
            if not shed.get("shed_no"):
                continue
            BroilerFarmShed.objects.create(
                farm=broiler_farm,
                shed_no=shed.get("shed_no", ""),
                dimensions=shed.get("dimensions", ""),
                sq_feet=shed.get("sq_feet", ""),
            )

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

    return {
        "batch_costing": batch_costing,
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
