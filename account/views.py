from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, Http404
from django.views import View
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import login_required
import json

from account.models import ChartOfAccount, FinancialYear, Schedule

# Create your views here.
@login_required
def account(request):
    return render(request, "account.html")


@login_required
def coa(request):
    context = {
        'account_types': ChartOfAccount.TYPE_CHOICES,
        'schedules': Schedule.objects.all()
    }

    return render(request, "coa.html", context)


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


@method_decorator(login_required, name="dispatch")
class ScheduleAPI(View):
    def get(self, request, id=None):
        """
        Get details of a single schedule by ID or list all schedules.
        """
        if id:
            try:
                schedule = Schedule.objects.get(id=id)
                return JsonResponse({
                    "id": schedule.id,
                    "code": schedule.code,
                    "name": schedule.name,
                    "created_at": schedule.created_at.strftime("%d-%b-%Y %H:%M"),  # Format the datetime
                })
            except Schedule.DoesNotExist:
                raise Http404("Schedule not found")
        else:
            schedules = Schedule.objects.values("id", "code", "name", "created_at")
            formatted_schedules = [
                {
                    **schedule,
                    "created_at": schedule["created_at"].strftime("%d-%b-%Y %H:%M"),  # Format the datetime
                }
                for schedule in schedules
            ]
            return JsonResponse(formatted_schedules, safe=False)

    def post(self, request):
        """
        Create a new schedule.
        """
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        try:
            schedule = Schedule.objects.create(
                code=data["code"], name=data["name"], description=data.get("description")
            )
            return JsonResponse(
                {
                    "message": "Schedule created",
                    "id": schedule.id,
                    "code": schedule.code,
                    "name": schedule.name,
                },
                status=201,
            )
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)

    def put(self, request, id):
        """
        Update an existing schedule.
        """
        try:
            schedule = Schedule.objects.get(id=id)
        except Schedule.DoesNotExist:
            raise Http404("Schedule not found")

        try:
            data = json.loads(request.body)
            schedule.code = data["code"]
            schedule.name = data["name"]
            schedule.description = data["description"]
            schedule.save()
            return JsonResponse(
                {
                    "message": "Schedule updated",
                    "id": schedule.id,
                    "code": schedule.code,
                    "name": schedule.name,
                }
            )
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)

    def delete(self, request, id):
        """
        Delete a schedule by ID.
        """
        try:
            schedule = Schedule.objects.get(id=id)
        except Schedule.DoesNotExist:
            raise Http404("Schedule not found")

        schedule.delete()
        return JsonResponse({"message": "Schedule deleted"})
    

@method_decorator(login_required, name="dispatch")
class ChartOfAccountsAPI(View):
    def get(self, request, id=None):
        """
        Get details of a single chart of account by ID or list all chart of accounts.
        """
        if id:
            try:
                coa = ChartOfAccount.objects.get(id=id)
                return JsonResponse(
                    {
                        "id": coa.id,
                        "code": coa.code,
                        "description": coa.description,
                        "type": coa.type,
                        "control_type": coa.control_type,
                        "status": coa.status,
                        "schedule": coa.schedule_id,
                        "schedule__name": coa.schedule.name,
                        "created_at": coa.created_at.strftime("%d-%b-%Y %H:%M"),  # Format the datetime
                    }
                )
            except ChartOfAccount.DoesNotExist:
                raise Http404("Chart of Account not found")
        else:
            coas = ChartOfAccount.objects.values(
                "id", "code", "description", "type","control_type", "status", "schedule_id", "schedule__name","created_at"
            )
            formatted_coas = [
                {
                    **coa,
                    "created_at": coa["created_at"].strftime("%d-%b-%Y %H:%M"),  # Format the datetime
                }
                for coa in coas
            ]
            return JsonResponse(formatted_coas, safe=False)

    def post(self, request):
        """
        Create a new chart of account.
        """
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        try:
            print(data, "data")
            coa = ChartOfAccount.objects.create(
                code=data["code"],
                description=data["description"],
                type=data["type"],
                control_type=data["control_type"],
                status=data["status"],
                schedule_id=data["schedule"],
            )
            return JsonResponse(
                {
                    "message": "Chart of Account created",
                    "id": coa.id,
                    "code": coa.code,
                    "description": coa.description,
                    "type": coa.type,
                    "control_type": coa.control_type,
                    "status": coa.status,
                    "schedule": coa.schedule_id,
                },
                status=201,
            )
        except Exception as e:
            print(e, "error")
            return JsonResponse({"error": str(e)}, status=400)

    def put(self, request, id):
        """
        Update an existing chart of account.
        """
        try:
            coa = ChartOfAccount.objects.get(id=id)
        except ChartOfAccount.DoesNotExist:
            raise Http404("Chart of Account not found")
        
        try:
            data = json.loads(request.body)
            coa.code = data["code"]
            coa.description = data["description"]
            coa.type = data["type"]
            coa.status = data["status"]
            coa.schedule_id = data["schedule"]
            coa.save()
            return JsonResponse(
                {
                    "message": "Chart of Account updated",
                    "id": coa.id,
                    "code": coa.code,
                    "description": coa.description,
                    "type": coa.type,
                    "status": coa.status,
                    "schedule": coa.schedule_id,
                }
            )
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)
        
    def delete(self, request, id):

        try:
            coa = ChartOfAccount.objects.get(id=id)
        except ChartOfAccount.DoesNotExist:
            raise Http404("Chart of Account not found")
        
        coa.delete()
        return JsonResponse({"message": "Chart of Account deleted"})
    
