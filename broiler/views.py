#pylint: disable=no-member

from typing import Dict, List, Optional, Union
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views import View
from django.http import Http404, JsonResponse
from django.db.models import F, Prefetch
from django.core.files.storage import default_storage
from django.core.exceptions import ValidationError
from django.db import transaction
from django.core.cache import cache
from django.conf import settings
from .models import Branch, BroilerBatch, BroilerDisease, BroilerFarm, BroilerPlace, Supervisor
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

@login_required()
def broiler(request):
    """Render the broiler template."""
    return render(request, "broiler.html")

@method_decorator(login_required, name="dispatch")
class BranchTemplateView(View):
    """View for rendering the branch template."""
    
    def get(self, request):
        context = {"states_and_union_territories": STATES_AND_TERRITORIES}
        return render(request, "branch.html", context)

@method_decorator(login_required, name="dispatch")
class BranchAPI(BaseAPIView):
    """API endpoints for Branch operations."""
    
    def get(self, request, id: Optional[int] = None) -> JsonResponse:
        try:
            if id:
                branch = Branch.objects.get(id=id)
                return JsonResponse({
                    "id": branch.id,
                    "state": branch.state,
                    "branch_name": branch.branch_name,
                })
            
            # Try to get from cache first
            cache_key = "branch_list"
            cached_data = self.get_cached_data(cache_key)
            if cached_data:
                return JsonResponse(cached_data, safe=False)
            
            # If not in cache, get from database
            branches = list(Branch.objects.all().values())
            print(branches, "branches")
            self.set_cached_data(cache_key, branches)
            return JsonResponse(branches, safe=False)
        except Exception as e:
            return self.handle_exception(e)

    def post(self, request) -> JsonResponse:
        try:
            data = request.POST
            with transaction.atomic():
                branch = Branch.objects.create(
                    state=data["state"],
                    branch_name=data["branch_name"]
                )
                # Invalidate cache
                cache.delete("branch_list")
            return JsonResponse({"message": "Branch created"}, status=201)
        except Exception as e:
            return self.handle_exception(e)

    def put(self, request, id: int) -> JsonResponse:
        try:
            branch = Branch.objects.get(id=id)
            data = json.loads(request.body)
            with transaction.atomic():
                branch.state = data["state"]
                branch.branch_name = data["branch_name"]
                branch.save()
                # Invalidate cache
                cache.delete("branch_list")
            return JsonResponse({"message": "Branch updated"})
        except Exception as e:
            return self.handle_exception(e)

    def delete(self, request, id: int) -> JsonResponse:
        try:
            branch = Branch.objects.get(id=id)
            with transaction.atomic():
                branch.delete()
                # Invalidate cache
                cache.delete("branch_list")
            return JsonResponse({"message": "Branch deleted"})
        except Exception as e:
            return self.handle_exception(e)

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
class BroilerPlaceTemplateView(View):
    """View for rendering the broiler place template."""
    
    def get(self, request):
        cache_key = "supervisor_list"
        supervisors = cache.get(cache_key)
        if not supervisors:
            supervisors = list(Supervisor.objects.values())
            cache.set(cache_key, supervisors)
        context = {"supervisors": supervisors}
        return render(request, "broiler_place.html", context)

@method_decorator(login_required, name="dispatch")
class BroilerFarmTemplateView(View):
    """View for rendering the broiler farm template."""
    
    def get(self, request):
        cache_key = "branch_list"
        branches = cache.get(cache_key)
        if not branches:
            branches = list(Branch.objects.values())
            cache.set(cache_key, branches)
        context = {"branches": branches}
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

@method_decorator(login_required, name="dispatch")
class BroilerPlaceAPI(BaseAPIView):
    """API endpoints for BroilerPlace operations."""
    
    def get(self, request, id: Optional[int] = None) -> JsonResponse:
        try:
            if id:
                broiler_place = BroilerPlace.objects.select_related("supervisor").get(id=id)
                return JsonResponse({
                    "id": broiler_place.id,
                    "name": broiler_place.place_name,
                    "supervisor_name": broiler_place.supervisor.name,
                })
            
            cache_key = "broiler_place_list"
            cached_data = self.get_cached_data(cache_key)
            if cached_data:
                return JsonResponse(cached_data, safe=False)
            
            broiler_places = list(
                BroilerPlace.objects.select_related("supervisor")
                .annotate(supervisor_name=F("supervisor__name"))
                .values("id", "place_name", "supervisor_name")
            )
            self.set_cached_data(cache_key, broiler_places)
            print(broiler_places, "broiler_places")
            return JsonResponse(broiler_places, safe=False)
        except Exception as e:
            return self.handle_exception(e)

    def post(self, request) -> JsonResponse:
        try:
            data = request.POST
            super_obj = Supervisor.objects.get(id=data["supervisor_id"])
            with transaction.atomic():
                BroilerPlace.objects.create(
                    place_name=data["place_name"],
                    supervisor=super_obj
                )
                cache.delete("broiler_place_list")
            return JsonResponse({"message": "BroilerPlace created"}, status=201)
        except Exception as e:
            return self.handle_exception(e)

    def put(self, request, id: int) -> JsonResponse:
        try:
            broiler_place = BroilerPlace.objects.get(id=id)
            data = json.loads(request.body)
            with transaction.atomic():
                broiler_place.place_name = data["place_name"]
                broiler_place.save()
                cache.delete("broiler_place_list")
            return JsonResponse({"message": "BroilerPlace updated"})
        except Exception as e:
            return self.handle_exception(e)

    def delete(self, request, id: int) -> JsonResponse:
        try:
            broiler_place = BroilerPlace.objects.get(id=id)
            with transaction.atomic():
                broiler_place.delete()
                cache.delete("broiler_place_list")
            return JsonResponse({"message": "BroilerPlace deleted"})
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
    
    def get(self, request, id: Optional[int] = None) -> JsonResponse:
        try:
            if id:
                broiler_farm = BroilerFarm.objects.select_related(
                    "branch", "supervisor", "broiler_place"
                ).get(id=id)
                return JsonResponse({
                    "id": broiler_farm.id,
                    "farm_code": broiler_farm.farm_code,
                    "farm_name": broiler_farm.farm_name,
                    "branch_name": broiler_farm.branch.branch_name if broiler_farm.branch else None,
                    "supervisor_name": broiler_farm.supervisor.name if broiler_farm.supervisor else None,
                    "broiler_place_name": broiler_farm.broiler_place.name if broiler_farm.broiler_place else None,
                    "mobile_no": broiler_farm.mobile_no,
                    "block_name": broiler_farm.block_name,
                    "address": broiler_farm.address,
                    "farm_latitude": broiler_farm.farm_latitude,
                    "farm_longitude": broiler_farm.farm_longitude,
                    "farm_type": broiler_farm.farm_type,
                })
            
            cache_key = "broiler_farm_list"
            cached_data = self.get_cached_data(cache_key)
            if cached_data:
                return JsonResponse(cached_data, safe=False)
            
            broiler_farms = list(
                BroilerFarm.objects.select_related("branch", "supervisor", "broiler_place")
                .values(
                    "id", "farm_code", "farm_name", "mobile_no", "block_name",
                    "address", "farm_latitude", "farm_longitude", "farm_type",
                    branch_name=F("branch__branch_name"),
                    supervisor_name=F("supervisor__name"),
                    broiler_place_name=F("broiler_place__place_name"),
                )
            )
            self.set_cached_data(cache_key, broiler_farms)
            return JsonResponse(broiler_farms, safe=False)
        except Exception as e:
            return self.handle_exception(e)

    def post(self, request) -> JsonResponse:
        try:
            data = request.POST
            with transaction.atomic():
                branch = Branch.objects.get(id=data["branch_id"])
                supervisor = Supervisor.objects.get(id=data["supervisor_id"])
                broiler_place = BroilerPlace.objects.get(id=data["broiler_place_id"])
                
                BroilerFarm.objects.create(
                    farm_code=data["farm_code"],
                    farm_name=data["farm_name"],
                    branch=branch,
                    supervisor=supervisor,
                    broiler_place=broiler_place,
                    mobile_no=data["mobile_no"],
                    block_name=data["block_name"],
                    address=data["address"],
                    farm_latitude=data["farm_latitude"],
                    farm_longitude=data["farm_longitude"],
                    farm_type=data["farm_type"],
                )
                cache.delete("broiler_farm_list")
            return JsonResponse({"message": "BroilerFarm created"}, status=201)
        except Exception as e:
            return self.handle_exception(e)

    def put(self, request, id: int) -> JsonResponse:
        try:
            broiler_farm = BroilerFarm.objects.get(id=id)
            data = json.loads(request.body.decode("utf-8"))
            with transaction.atomic():
                broiler_farm.farm_code = data.get("farm_code", broiler_farm.farm_code)
                broiler_farm.farm_name = data.get("farm_name", broiler_farm.farm_name)
                broiler_farm.mobile_no = data.get("mobile_no", broiler_farm.mobile_no)
                broiler_farm.block_name = data.get("block_name", broiler_farm.block_name)
                broiler_farm.address = data.get("address", broiler_farm.address)
                broiler_farm.farm_latitude = data.get("farm_latitude", broiler_farm.farm_latitude)
                broiler_farm.farm_longitude = data.get("farm_longitude", broiler_farm.farm_longitude)
                broiler_farm.farm_type = data.get("farm_type", broiler_farm.farm_type)

                if "branch_id" in data:
                    broiler_farm.branch = Branch.objects.get(id=data["branch_id"])
                if "supervisor_id" in data:
                    broiler_farm.supervisor = Supervisor.objects.get(id=data["supervisor_id"])
                if "broiler_place_id" in data:
                    broiler_farm.broiler_place = BroilerPlace.objects.get(id=data["broiler_place_id"])

                broiler_farm.save()
                cache.delete("broiler_farm_list")
            return JsonResponse({"message": "BroilerFarm updated"})
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

@login_required()
def get_broiler_places(request) -> JsonResponse:
    """Get broiler places for a specific supervisor."""
    try:
        supervisor_id = request.GET.get('supervisor_id')
        cache_key = f"broiler_places_supervisor_{supervisor_id}"
        
        cached_data = cache.get(cache_key)
        if cached_data:
            return JsonResponse({'broiler_places': cached_data})
        
        broiler_places = list(BroilerPlace.objects.filter(supervisor_id=supervisor_id).values('id', 'place_name'))
        cache.set(cache_key, broiler_places, 300)  # Cache for 5 minutes
        return JsonResponse({'broiler_places': broiler_places})
    except Exception as e:
        logger.error(f"Error in get_broiler_places: {str(e)}", exc_info=True)
        return JsonResponse({"error": str(e)}, status=500)