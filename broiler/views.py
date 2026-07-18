#pylint: disable=no-member

from typing import Dict, List, Optional, Union
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views import View
from django.http import Http404, JsonResponse
from django.db.models import F, Prefetch, Q
from django.core.files.storage import default_storage
from django.core.exceptions import ValidationError
from django.db import transaction
from django.core.cache import cache
from django.conf import settings
from .models import (
    Branch, BroilerBatch, BroilerDisease, BroilerFarm, BroilerFarmImage,
    BroilerFarmShed, BroilerLine, DailyEntry, Farmer, FarmerGroup, MedicineVaccineEntry,
    Region, Supervisor,
)
from account.models import ChartOfAccount
from inventory.models import Item
from decimal import Decimal
from datetime import timedelta
from django.utils import timezone
import json
import logging

logger = logging.getLogger(__name__)

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
            return JsonResponse({"error": str(e)}, status=400)
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
class BranchTemplateView(View):
    """View for rendering the branch template."""

    def get(self, request):
        context = {"regions": Region.objects.filter(is_active=True)}
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

            created = 0
            with transaction.atomic():
                for branch_name, prefix in zip(branch_names, prefixes):
                    branch_name = branch_name.strip()
                    prefix = prefix.strip()
                    if not branch_name or not prefix:
                        continue
                    Branch.objects.create(region=region, branch_name=branch_name, prefix=prefix)
                    created += 1
                cache.delete("branch_list")

            if not created:
                return JsonResponse({"error": "Enter at least one branch name and prefix."}, status=400)
            return JsonResponse({"message": f"{created} branch(es) created"}, status=201)
        except Exception as e:
            return self.handle_exception(e)

    def put(self, request, id: int) -> JsonResponse:
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
        cache_key = "branch_list"
        branches = cache.get(cache_key)
        if not branches:
            branches = list(Branch.objects.values())
            cache.set(cache_key, branches)
        context = {"branches": branches}
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
                supervisor = Supervisor.objects.select_related("branch").get(id=id)
                return JsonResponse({
                    "id": supervisor.id.id,
                    "supervisor": supervisor.name,
                    "branch_name": supervisor.branch.branch_name,
                })
            
            cache_key = "supervisor_list"
            cached_data = self.get_cached_data(cache_key)
            if cached_data:
                return JsonResponse(cached_data, safe=False)
            
            supervisors = list(
                Supervisor.objects.select_related("branch")
                .annotate(branch_name=F("branch__branch_name"))
                .values("id", "name", "branch_name")
            )
            self.set_cached_data(cache_key, supervisors)
            return JsonResponse(supervisors, safe=False)
        except Exception as e:
            return self.handle_exception(e)

    def post(self, request) -> JsonResponse:
        try:
            data = request.POST
            branch = Branch.objects.get(branch_name=data["branch"])
            with transaction.atomic():
                Supervisor.objects.create(
                    name=data["supervisor_name"],
                    branch=branch
                )
                cache.delete("supervisor_list")
            return JsonResponse({"message": "Supervisor created"}, status=201)
        except Exception as e:
            return self.handle_exception(e)

    def put(self, request, id: int) -> JsonResponse:
        try:
            supervisor = Supervisor.objects.get(id=id)
            data = json.loads(request.body)
            with transaction.atomic():
                supervisor.name = data["supervisor_name"]
                supervisor.branch.branch_name = data["branch"]
                supervisor.save()
                cache.delete("supervisor_list")
            return JsonResponse({"message": "Supervisor updated"})
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
                    "broiler_farm_name": broiler_batch.broiler_farm.farm_name,
                })
            
            cache_key = "broiler_batch_list"
            cached_data = self.get_cached_data(cache_key)
            if cached_data:
                return JsonResponse(cached_data, safe=False)
            
            broiler_batches = list(
                BroilerBatch.objects.select_related("broiler_farm")
                .annotate(broiler_farm_name=F("broiler_farm__farm_name"))
                .values("id", "batch_name", "broiler_farm_name")
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
                BroilerBatch.objects.create(
                    batch_name=data["batch_name"],
                    broiler_farm=farm_obj
                )
                cache.delete("broiler_batch_list")
            return JsonResponse({"message": "BroilerBatch created"}, status=201)
        except Exception as e:
            return self.handle_exception(e)

    def put(self, request, id: int) -> JsonResponse:
        try:
            broiler_batch = BroilerBatch.objects.get(id=id)
            data = json.loads(request.body)
            with transaction.atomic():
                broiler_batch.batch_name = data["batch_name"]
                broiler_batch.save()
                cache.delete("broiler_batch_list")
            return JsonResponse({"message": "BroilerBatch updated"})
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
    FORM_FIELDS = [
        "farm_code", "farm_name", "region", "line", "farm_pincode", "farm_capacity",
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
                        setattr(broiler_farm, field, data[field] or None)

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
        "unit": row.item.consumption_uom if row.item_id else "",
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
    return JsonResponse({"unit": item.consumption_uom if item else ""})


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
