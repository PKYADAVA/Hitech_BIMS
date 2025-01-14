from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views import View
from django.http import Http404, JsonResponse
from django.views import View
from .models import Branch, BroilerBatch, BroilerFarm, BroilerPlace, Supervisor
import json


from broiler.models import Branch
from django.db.models import F


@login_required()
def broiler(request):
    return render(request, "broiler.html")


@method_decorator(login_required, name="dispatch")
class BranchTemplateView(View):
    def get(self, request):
        # List of Indian states and union territories
        states_and_union_territories = [
            "Andhra Pradesh",
            "Arunachal Pradesh",
            "Assam",
            "Bihar",
            "Chhattisgarh",
            "Goa",
            "Gujarat",
            "Haryana",
            "Himachal Pradesh",
            "Jharkhand",
            "Karnataka",
            "Kerala",
            "Madhya Pradesh",
            "Maharashtra",
            "Manipur",
            "Meghalaya",
            "Mizoram",
            "Nagaland",
            "Odisha",
            "Punjab",
            "Rajasthan",
            "Sikkim",
            "Tamil Nadu",
            "Telangana",
            "Tripura",
            "Uttar Pradesh",
            "Uttarakhand",
            "West Bengal",
            "Andaman and Nicobar Islands",
            "Chandigarh",
            "Dadra and Nagar Haveli and Daman and Diu",
            "Delhi",
            "Jammu and Kashmir",
            "Ladakh",
            "Lakshadweep",
            "Puducherry",
        ]

        # Pass the data as context
        context = {"states_and_union_territories": states_and_union_territories}
        # Render the branch_template.html file
        return render(request, "branch.html", context)


@method_decorator(login_required, name="dispatch")
class BranchAPI(View):
    def get(self, request, id=None):
        if id:
            try:
                branch = Branch.objects.get(id=id)
                return JsonResponse(
                    {
                        "id": branch.id,
                        "state": branch.state,
                        "branch_name": branch.branch_name,
                    }
                )
            except Branch.DoesNotExist:
                raise Http404("Branch not found")
        else:
            branches = list(Branch.objects.values())
            print("Branches: ", branches)
            return JsonResponse(branches, safe=False)

    def post(self, request):

        try:
            data = request.POST
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        Branch.objects.create(state=data["state"], branch_name=data["branch_name"])
        return JsonResponse({"message": "Branch created"}, status=201)

    def put(self, request, id):
        try:
            branch = Branch.objects.get(id=id)
        except Branch.DoesNotExist:
            raise Http404("Branch not found")

        data = json.loads(request.body)
        branch.state = data["state"]
        branch.branch_name = data["branch_name"]
        branch.save()
        return JsonResponse({"message": "Branch updated"})

    def delete(self, request, id):
        try:
            branch = Branch.objects.get(id=id)
        except Branch.DoesNotExist:
            raise Http404("Branch not found")

        branch.delete()
        return JsonResponse({"message": "Branch deleted"})


@method_decorator(login_required, name="dispatch")
class SupervisorTemplateView(View):
    def get(self, request):
        context = {"branches": list(Branch.objects.values())}
        return render(request, "supervisor.html", context)


@method_decorator(login_required, name="dispatch")
class BroilerPlaceTemplateView(View):
    def get(self, request):
        # List of Indian states and union territories

        # Pass the data as context
        context = {"supervisors": list(Supervisor.objects.values())}
        # Render the branch_template.html file
        return render(request, "broiler_place.html", context)


@method_decorator(login_required, name="dispatch")
class BroilerFarmTemplateView(View):
    def get(self, request):
        # List of Indian states and union territories

        # Pass the data as context
        context = {"branches": list(Branch.objects.values())}
        # Render the branch_template.html file
        return render(request, "broiler_farm.html", context)


class BroilerBatchTemplateView(View):
    def get(self, request):
        # List of Indian states and union territories

        # Pass the data as context
        context = {"branches": list(Branch.objects.values())}
        # Render the branch_template.html file
        return render(request, "broiler_batch.html", context)


@method_decorator(login_required, name="dispatch")
class BroilerDiseaseTemplateView(View):
    def get(self, request):
        # List of Indian states and union territories

        # Pass the data as context
        context = {"branches": list(Branch.objects.values())}
        # Render the branch_template.html file
        return render(request, "broiler_disease.html", context)


@method_decorator(login_required, name="dispatch")
class SupervisorAPI(View):

    def get(self, request, id=None):
        if id:
            try:
                supervisor = Supervisor.objects.get(id=id)
                return JsonResponse(
                    {
                        "id": supervisor.id.id,
                        "supervisor": supervisor.name,
                        "branch_name": supervisor.branch.branch_name,
                    }
                )
            except Supervisor.DoesNotExist:
                raise Http404("Supervisor not found")
        else:
            supervisors = list(
                Supervisor.objects.select_related("branch")  # Load related branch data
                .annotate(
                    branch_name=F("branch__branch_name")
                )  # Create an alias for branch_name
                .values(
                    "id", "name", "branch_name"
                )  # Use the alias for the JSON response
            )
            return JsonResponse(supervisors, safe=False)

    def post(self, request):

        try:
            data = request.POST
            print(data, "data")
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        branch = Branch.objects.get(branch_name=data["branch"])

        Supervisor.objects.create(name=data["supervisor_name"], branch=branch)
        return JsonResponse({"message": "Supervisor created"}, status=201)

    def put(self, request, id):
        try:
            supervisor = Supervisor.objects.get(id=id)
        except Supervisor.DoesNotExist:
            raise Http404("Supervisor not found")

        data = json.loads(request.body)
        supervisor.name = data["name"]
        supervisor.branch.branch_name = data["branch_name"]
        supervisor.save()
        return JsonResponse({"message": "Supervisor updated"})

    def delete(self, request, id):
        try:
            supervisor = Supervisor.objects.get(id=id)
        except Supervisor.DoesNotExist:
            raise Http404("Supervisor not found")

        supervisor.delete()
        return JsonResponse({"message": "Supervisor deleted"})


@method_decorator(login_required, name="dispatch")
class BroilerPlaceAPI(View):

    def get(self, request, id=None):
        if id:
            try:
                broiler_place = BroilerPlace.objects.get(id=id)
                return JsonResponse(
                    {
                        "id": broiler_place.id,
                        "name": broiler_place.place_name,
                        "supervisor_name": broiler_place.supervisor.name,
                    }
                )
            except BroilerPlace.DoesNotExist:
                raise Http404("Supervisor not found")
        else:
            broiler_places = list(
                BroilerPlace.objects.select_related(
                    "supervisor"
                )  # Load related branch data
                .annotate(
                    supervisor_name=F("supervisor__name")
                )  # Create an alias for branch_name
                .values(
                    "id", "place_name", "supervisor_name"
                )  # Use the alias for the JSON response
            )
            return JsonResponse(broiler_places, safe=False)

    def post(self, request):

        try:
            data = request.POST
            print(data, "data")
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        super_obj = Supervisor.objects.get(id=data["supervisor_id"])

        BroilerPlace.objects.create(place_name=data["place_name"], supervisor=super_obj)
        return JsonResponse({"message": "BroilerPlace created"}, status=201)

    def put(self, request, id):
        try:
            broiler_place = BroilerPlace.objects.get(id=id)
        except Supervisor.DoesNotExist:
            raise Http404("Supervisor not found")

        data = json.loads(request.body)
        broiler_place.place_name = data["place_name"]
        broiler_place.save()
        return JsonResponse({"message": "BroilerPlace updated"})

    def delete(self, request, id):
        try:
            broiler_place = BroilerPlace.objects.get(id=id)
        except BroilerPlace.DoesNotExist:
            raise Http404("Supervisor not found")

        broiler_place.delete()
        return JsonResponse({"message": "BroilerPlace deleted"})


@method_decorator(login_required, name="dispatch")
class BroilerBatchAPI(View):

    def get(self, request, id=None):
        if id:
            try:
                broiler_batch = BroilerBatch.objects.get(id=id)
                return JsonResponse(
                    {
                        "id": broiler_batch.id,
                        "name": broiler_batch.batch_name,
                        "broiler_farm_name": broiler_batch.broiler_farm.farm_name,
                    }
                )
            except BroilerPlace.DoesNotExist:
                raise Http404("BroilerBatch not found")
        else:
            broiler_batches = list(
                BroilerBatch.objects.select_related(
                    "broiler_farm"
                )  # Load related branch data
                .annotate(
                    broiler_farm_name=F("broiler_farm__farm_name")
                )  # Create an alias for branch_name
                .values(
                    "id", "batch_name", "broiler_farm_name"
                )  # Use the alias for the JSON response
            )
            return JsonResponse(broiler_batches, safe=False)

    def post(self, request):

        try:
            data = request.POST
            print(data, "data")
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        farm_obj = BroilerFarm.objects.get(id=data["broiler_farm_id"])

        BroilerBatch.objects.create(
            place_name=data["batch_name"], broiler_farm=farm_obj
        )
        return JsonResponse({"message": "BroilerBatch created"}, status=201)

    def put(self, request, id):
        try:
            broiler_batch = BroilerBatch.objects.get(id=id)
        except BroilerBatch.DoesNotExist:
            raise Http404("Supervisor not found")

        data = json.loads(request.body)
        broiler_batch.batch_name = data["batch_name"]
        broiler_batch.save()
        return JsonResponse({"message": "BroilerBatch updated"})

    def delete(self, request, id):
        try:
            broiler_batch = BroilerBatch.objects.get(id=id)
        except BroilerBatch.DoesNotExist:
            raise Http404("Supervisor not found")

        broiler_batch.delete()
        return JsonResponse({"message": "BroilerBatch deleted"})
