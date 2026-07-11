import csv
import io

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, Http404
from django.views import View
from django.utils.decorators import method_decorator
from django.db import transaction
import json
import openpyxl

from account.models import ChartOfAccount, CoACategory, FinancialYear, Schedule

# Create your views here.
@login_required
def coa(request):
    context = {
        'account_types': ChartOfAccount.TYPE_CHOICES,
        'schedules': Schedule.objects.all()
    }

    return render(request, "coa.html", context)


@login_required
def coa_category(request):
    context = {'category_types': CoACategory.TYPE_CHOICES}
    return render(request, "coa_category.html", context)


@method_decorator(login_required, name="dispatch")
class CoACategoryAPI(View):
    """API endpoints for CoACategory operations."""

    def get(self, request, id=None):
        if id:
            try:
                cat = CoACategory.objects.get(id=id)
            except CoACategory.DoesNotExist:
                raise Http404("CoA category not found")
            return JsonResponse({
                "id": cat.id,
                "code": cat.code,
                "type": cat.type,
                "description": cat.description,
                "is_active": cat.is_active,
                "is_locked": cat.is_locked,
            })

        categories = CoACategory.objects.all()
        results = [{
            "id": cat.id,
            "code": cat.code,
            "type": cat.type,
            "description": cat.description,
            "is_active": cat.is_active,
            "is_locked": cat.is_locked,
        } for cat in categories]
        return JsonResponse(results, safe=False)

    def post(self, request):
        data = request.POST
        try:
            with transaction.atomic():
                CoACategory.objects.create(
                    type=data["type"],
                    description=data["description"],
                )
            return JsonResponse({"message": "CoA category created"}, status=201)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)

    def put(self, request, id):
        try:
            cat = CoACategory.objects.get(id=id)
        except CoACategory.DoesNotExist:
            raise Http404("CoA category not found")
        if cat.is_locked:
            return JsonResponse({"error": "This category is locked."}, status=400)
        try:
            data = json.loads(request.body)
            with transaction.atomic():
                cat.type = data["type"]
                cat.description = data["description"]
                cat.save()
            return JsonResponse({"message": "CoA category updated"})
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)

    def delete(self, request, id):
        try:
            cat = CoACategory.objects.get(id=id)
        except CoACategory.DoesNotExist:
            raise Http404("CoA category not found")
        if cat.is_locked:
            return JsonResponse({"error": "This category is locked."}, status=400)
        with transaction.atomic():
            cat.delete()
        return JsonResponse({"message": "CoA category deleted"})


@login_required
def toggle_coa_category_active(request, id):
    """Toggle a CoA category's active/inactive status."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=400)
    try:
        cat = CoACategory.objects.get(id=id)
        if cat.is_locked:
            return JsonResponse({"error": "This category is locked."}, status=400)
        cat.is_active = not cat.is_active
        cat.save(update_fields=["is_active"])
        return JsonResponse({"message": "CoA category updated", "is_active": cat.is_active})
    except CoACategory.DoesNotExist:
        return JsonResponse({"error": "CoA category not found."}, status=404)


@login_required
def toggle_coa_category_lock(request, id):
    """Toggle a CoA category's locked status."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=400)
    try:
        cat = CoACategory.objects.get(id=id)
        cat.is_locked = not cat.is_locked
        cat.save(update_fields=["is_locked"])
        return JsonResponse({"message": "CoA category updated", "is_locked": cat.is_locked})
    except CoACategory.DoesNotExist:
        return JsonResponse({"error": "CoA category not found."}, status=404)


@login_required
def coa_category_bulk_upload(request):
    """Bulk-create CoA categories from an uploaded CSV or Excel file.

    Expected columns (header row required, case-insensitive): Type, Code,
    Description. Code is optional per row - if blank, one is auto-generated;
    if given, it's used as-is (this is how a reference system's existing
    category codes, with their own numbering gaps, get preserved on import).
    """
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=400)

    upload = request.FILES.get("file")
    if not upload:
        return JsonResponse({"error": "No file uploaded."}, status=400)

    valid_types = {choice[0].lower(): choice[0] for choice in CoACategory.TYPE_CHOICES}
    filename = upload.name.lower()

    try:
        if filename.endswith(".csv"):
            rows = _parse_csv_rows(upload)
        elif filename.endswith(".xlsx") or filename.endswith(".xls"):
            rows = _parse_excel_rows(upload)
        else:
            return JsonResponse({"error": "Unsupported file type. Upload a .csv or .xlsx file."}, status=400)
    except Exception as e:
        return JsonResponse({"error": f"Could not read file: {e}"}, status=400)

    created, skipped = [], []
    with transaction.atomic():
        for row_num, row in rows:
            row_type = str(row.get("type") or "").strip()
            description = str(row.get("description") or "").strip()
            code = str(row.get("code") or "").strip()

            normalized_type = valid_types.get(row_type.lower())
            if not normalized_type or not description:
                skipped.append({"row": row_num, "reason": "Missing/invalid Type or Description"})
                continue
            if code and CoACategory.objects.filter(code=code).exists():
                skipped.append({"row": row_num, "reason": f"Code '{code}' already exists"})
                continue

            cat = CoACategory(type=normalized_type, description=description)
            if code:
                cat.code = code
            cat.save()
            created.append(cat.code)

    return JsonResponse({
        "message": f"{len(created)} categories imported, {len(skipped)} skipped.",
        "created": created,
        "skipped": skipped,
    })


def _parse_csv_rows(upload):
    text = io.TextIOWrapper(upload.file, encoding="utf-8-sig")
    reader = csv.DictReader(text)
    reader.fieldnames = [(f or "").strip().lower() for f in (reader.fieldnames or [])]
    return list(enumerate(reader, start=2))


def _parse_excel_rows(upload):
    workbook = openpyxl.load_workbook(upload, read_only=True, data_only=True)
    sheet = workbook.active
    rows_iter = sheet.iter_rows(values_only=True)
    headers = [str(h or "").strip().lower() for h in next(rows_iter)]
    rows = []
    for row_num, values in enumerate(rows_iter, start=2):
        if not any(values):
            continue
        rows.append((row_num, dict(zip(headers, values))))
    return rows


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
    
