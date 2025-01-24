from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, Http404
from django.views import View
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import login_required
import json

from account.models import FinancialYear

# Create your views here.





@login_required
def account(request):
    return render(request, "account.html")

@login_required
def coa(request):
    return render(request, "coa.html")

@login_required
def fin_year(request):
    return render(request, "fin_year.html")

@login_required
def bank_cash(request):
    return render(request, "bank_cash.html")

@login_required
def schedule(request):
    return render(request, "schedule.html")


@method_decorator(login_required, name="dispatch")
class FinancialYearAPI(View):
    def get(self, request, id=None):
        """
        Get details of a single financial year by ID or list all financial years.
        """
        if id:
            try:
                fin_year = FinancialYear.objects.get(id=id)
                return JsonResponse(
                    {
                        "id": fin_year.id,
                        "start_date": fin_year.start_date,
                        "end_date": fin_year.end_date,
                        "is_active": fin_year.is_active,
                    }
                )
            except FinancialYear.DoesNotExist:
                raise Http404("Financial Year not found")
        else:
            fin_years = list(
                FinancialYear.objects.values(
                    "id", "start_date", "end_date", "is_active"
                )
            )
            return JsonResponse(fin_years, safe=False)

    def post(self, request):
        """
        Create a new financial year.
        """
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        try:
            fin_year = FinancialYear.objects.create(
                start_date=data["start_date"],
                end_date=data["end_date"],
                is_active=data.get("is_active", False),
            )
            return JsonResponse(
                {
                    "message": "Financial year created",
                    "id": fin_year.id,
                    "start_date": fin_year.start_date,
                    "end_date": fin_year.end_date,
                    "is_active": fin_year.is_active,
                },
                status=201,
            )
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)

    def put(self, request, id):
        """
        Update an existing financial year.
        """
        try:
            fin_year = FinancialYear.objects.get(id=id)
        except FinancialYear.DoesNotExist:
            raise Http404("Financial Year not found")

        try:
            data = json.loads(request.body)
            fin_year.start_date = data["start_date"]
            fin_year.end_date = data["end_date"]
            fin_year.is_active = data["is_active"]
            fin_year.save()
            return JsonResponse(
                {
                    "message": "Financial year updated",
                    "id": fin_year.id,
                    "start_date": fin_year.start_date,
                    "end_date": fin_year.end_date,
                    "is_active": fin_year.is_active,
                }
            )
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)

    def delete(self, request, id):
        """
        Delete a financial year by ID.
        """
        try:
            fin_year = FinancialYear.objects.get(id=id)
        except FinancialYear.DoesNotExist:
            raise Http404("Financial Year not found")

        fin_year.delete()
        return JsonResponse({"message": "Financial year deleted"})
