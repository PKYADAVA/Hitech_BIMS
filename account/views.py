import csv
import io

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, Http404
from django.views import View
from django.utils.decorators import method_decorator
import json
import openpyxl

from django.contrib import messages
from django.core.exceptions import ValidationError

from account.models import ChartOfAccount, CompanyProfile, FinancialYear, TermsConditions
from hatchery_master.models import STATES_AND_TERRITORIES

# Create your views here.
@login_required
def coa(request):
    from account.models import AccountGroup, AccountType
    context = {
        'account_types': AccountType.objects.all(),
        'account_groups': AccountGroup.objects.filter(is_active=True),
    }

    return render(request, "coa.html", context)


@login_required
def ledger_report(request):
    return render(request, "ledger_report.html")


@login_required
def vouchers(request):
    from account.models import Voucher
    from inventory.models import Warehouse
    return render(request, "journal.html", {
        "voucher_types": Voucher.TYPE_CHOICES,
        "sectors": Warehouse.objects.all().order_by("name"),
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
                        "state": fin_year.state,
                    }
                )
            except FinancialYear.DoesNotExist:
                raise Http404("Financial Year not found")
        else:
            fin_years = list(
                FinancialYear.objects.values(
                    "id", "start_date", "end_date", "is_active", "state"
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
            if data.get("state") in dict(FinancialYear.STATE_CHOICES):
                fin_year.state = data["state"]
            fin_year.save()
            return JsonResponse(
                {
                    "message": "Financial year updated",
                    "id": fin_year.id,
                    "start_date": fin_year.start_date,
                    "end_date": fin_year.end_date,
                    "is_active": fin_year.is_active,
                    "state": fin_year.state,
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


@login_required
def company_profile(request):
    profile = CompanyProfile.get_solo()

    if request.method == "POST":
        profile.name = request.POST.get("name", "").strip()
        profile.address = request.POST.get("address", "").strip()
        profile.state = request.POST.get("state", "").strip()
        profile.mobile = request.POST.get("mobile", "").strip()
        profile.email = request.POST.get("email", "").strip()
        profile.gstin = request.POST.get("gstin", "").strip()
        profile.pan = request.POST.get("pan", "").strip()
        profile.bank_name = request.POST.get("bank_name", "").strip()
        profile.bank_account_no = request.POST.get("bank_account_no", "").strip()
        profile.ifsc_code = request.POST.get("ifsc_code", "").strip()
        profile.bank_branch = request.POST.get("bank_branch", "").strip()
        try:
            profile.full_clean()
            profile.save()
            messages.success(request, "Company profile updated successfully.")
            return redirect("company_profile")
        except ValidationError as e:
            messages.error(request, " ".join(e.messages) if hasattr(e, "messages") else str(e))

    return render(request, "company_profile.html", {
        "profile": profile,
        "states_and_union_territories": STATES_AND_TERRITORIES,
    })


@login_required()
def terms(request):
    return render(request, "t&c.html", {"party_types": TermsConditions.PartyType.choices})


@method_decorator(login_required, name="dispatch")
class TermsConditionsAPI(View):

    def get(self, request, id=None):
        if id:
            try:
                terms_conditions = TermsConditions.objects.get(id=id)
                return JsonResponse(
                    {
                        "id": terms_conditions.id,
                        "type": terms_conditions.type,
                        "party_type": terms_conditions.party_type,
                        "condition": terms_conditions.condition,
                    }
                )
            except TermsConditions.DoesNotExist:
                raise Http404("TermsConditions not found")
        else:
            terms_conditions = list(
                TermsConditions.objects.values("id", "type", "party_type", "condition")
            )
            return JsonResponse(terms_conditions, safe=False)

    def post(self, request):
        try:
            data = json.loads(request.body)  # Expect JSON payload
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        TermsConditions.objects.create(
            type=data.get("type"),
            party_type=data.get("party_type") or TermsConditions.PartyType.CUSTOMER,
            condition=data.get("condition"),
        )
        return JsonResponse({"message": "TermsConditions created"}, status=201)

    def put(self, request, id):
        try:
            terms_conditions = TermsConditions.objects.get(id=id)
        except TermsConditions.DoesNotExist:
            raise Http404("TermsConditions not found")

        try:
            data = json.loads(request.body)  # Expect JSON payload
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        terms_conditions.type = data.get("type", terms_conditions.type)
        terms_conditions.party_type = data.get("party_type", terms_conditions.party_type)
        terms_conditions.condition = data.get("condition", terms_conditions.condition)
        terms_conditions.save()

        return JsonResponse({"message": "TermsConditions updated"})

    def delete(self, request, id):
        try:
            terms_conditions = TermsConditions.objects.get(id=id)
        except TermsConditions.DoesNotExist:
            raise Http404("TermsConditions not found")

        terms_conditions.delete()
        return JsonResponse({"message": "TermsConditions deleted"})

