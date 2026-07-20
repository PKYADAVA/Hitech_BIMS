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
from django.db import IntegrityError
from django.db.models.deletion import ProtectedError

from account.models import BankCashMaster, ChartOfAccount, CompanyProfile, CostCenter, FinancialYear, TermsConditions
from hatchery_master.models import STATES_AND_TERRITORIES
from inventory.models import Mapping, Sector, Warehouse

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
def profit_loss_report(request):
    return render(request, "profit_loss_report.html")


@login_required
def balance_sheet_report(request):
    return render(request, "balance_sheet_report.html")


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


def _coa_head_label(is_cash):
    """The COA anchor group a Bank/Cash row's auto-created ledger files
    under — 'Bank Accounts' for a bank, 'Cash & Cash Equivalents' for cash.
    Shown read-only on the Bank/Cash Master so the mapping is visible before
    and after saving; falls back gracefully if the company's COA hasn't
    been generated yet."""
    role = 'CASH' if is_cash else 'BANK_ACCOUNTS'
    anchor = ChartOfAccount.objects.filter(system_role=role).first()
    return f"{anchor.code} - {anchor.description}" if anchor else "Not yet generated"


@login_required
def bank_cash(request):
    return render(request, "bank_cash.html", {
        "sectors": Warehouse.objects.all().order_by("name"),
        "bank_coa_head": _coa_head_label(is_cash=False),
        "cash_coa_head": _coa_head_label(is_cash=True),
    })


def _resolve_sectors(raw_ids):
    """(warehouses, error) for a list of office ids. Empty is valid and
    means 'All Offices' — a bank/cash record isn't pinned to one place."""
    ids = raw_ids or []
    warehouses = list(Warehouse.objects.filter(id__in=ids))
    if len(warehouses) != len(set(ids)):
        return None, "Invalid office ID"
    return warehouses, None


def _bank_cash_dict(row):
    offices = list(row.sectors.all())
    all_offices = not offices
    return {
        "id": row.id, "code": row.code, "is_cash": row.is_cash, "name": row.name,
        "sectors": [o.id for o in offices],
        "sector_names": "All Offices" if all_offices else ", ".join(o.name for o in offices),
        "micr": row.micr, "address": row.address, "email": row.email,
        "phone": row.phone, "fax": row.fax, "contact_person": row.contact_person,
        "coa_head": _coa_head_label(row.is_cash),
    }


@method_decorator(login_required, name="dispatch")
class BankCashMasterAPI(View):
    def get(self, request, id=None):
        if id:
            try:
                return JsonResponse(_bank_cash_dict(BankCashMaster.objects.prefetch_related("sectors").get(id=id)))
            except BankCashMaster.DoesNotExist:
                raise Http404("Record not found")
        rows = BankCashMaster.objects.prefetch_related("sectors").order_by("name")
        return JsonResponse([_bank_cash_dict(r) for r in rows], safe=False)

    def post(self, request):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        if not data.get("name"):
            return JsonResponse({"error": "Name is required"}, status=400)

        offices, error = _resolve_sectors(data.get("sectors"))
        if error:
            return JsonResponse({"error": error}, status=400)

        try:
            row = BankCashMaster.objects.create(
                is_cash=bool(data.get("is_cash")), name=data["name"],
                micr=data.get("micr") or None,
                address=data.get("address") or None, email=data.get("email") or None,
                phone=data.get("phone") or None, fax=data.get("fax") or None,
                contact_person=data.get("contact_person") or None,
            )
            row.sectors.set(offices)
            return JsonResponse({"message": "Saved", "id": row.id, "code": row.code}, status=201)
        except (KeyError, ValidationError) as e:
            return JsonResponse({"error": str(e)}, status=400)
        except IntegrityError:
            return JsonResponse({"error": "A record with this code may already exist."}, status=400)

    def put(self, request, id):
        try:
            row = BankCashMaster.objects.get(id=id)
        except BankCashMaster.DoesNotExist:
            raise Http404("Record not found")

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        offices, error = _resolve_sectors(data.get("sectors"))
        if error:
            return JsonResponse({"error": error}, status=400)

        try:
            row.is_cash = bool(data.get("is_cash", row.is_cash))
            row.name = data.get("name", row.name)
            row.micr = data.get("micr") or None
            row.address = data.get("address") or None
            row.email = data.get("email") or None
            row.phone = data.get("phone") or None
            row.fax = data.get("fax") or None
            row.contact_person = data.get("contact_person") or None
            row.full_clean(exclude=["code"])
            row.save()
            row.sectors.set(offices)
            return JsonResponse({"message": "Updated"})
        except ValidationError as e:
            return JsonResponse({"error": "; ".join(e.messages)}, status=400)
        except IntegrityError:
            return JsonResponse({"error": "A record with this code may already exist."}, status=400)

    def delete(self, request, id):
        try:
            row = BankCashMaster.objects.get(id=id)
        except BankCashMaster.DoesNotExist:
            raise Http404("Record not found")
        row.delete()
        return JsonResponse({"message": "Deleted"})


# ---------------------------------------------------------------------------
# Cost Center (Account > Master > Cost Center)
# ---------------------------------------------------------------------------

def _default_company():
    return CompanyProfile.objects.filter(pk=1).first()


@login_required
def cost_center(request):
    return render(request, "cost_center.html", {
        "kinds": Sector.objects.order_by("name"),
        "branch_kind_code": CostCenter.KIND_BRANCH,
        "cost_centers": CostCenter.objects.order_by("code"),
    })


def _cost_center_dict(cc):
    return {
        "id": cc.id, "code": cc.code, "name": cc.name,
        "kind": cc.kind_id, "kind_name": cc.kind.name, "kind_code": cc.kind.code,
        "parent": cc.parent_id, "parent_label": str(cc.parent) if cc.parent_id else "",
        "is_active": cc.is_active,
        "branch": cc.branch_id,
        "branch_name": cc.branch.branch_name if cc.branch_id else "",
    }


@method_decorator(login_required, name="dispatch")
class CostCenterAPI(View):
    def get(self, request, id=None):
        if id:
            try:
                return JsonResponse(_cost_center_dict(CostCenter.objects.select_related("parent", "branch", "kind").get(id=id)))
            except CostCenter.DoesNotExist:
                raise Http404("Cost center not found")
        rows = CostCenter.objects.select_related("parent", "branch", "kind").order_by("code")
        return JsonResponse([_cost_center_dict(r) for r in rows], safe=False)

    def post(self, request):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        if not data.get("name"):
            return JsonResponse({"error": "Name is required"}, status=400)
        kind = Sector.objects.filter(id=data.get("kind")).first()
        if not kind:
            return JsonResponse({"error": "Invalid kind"}, status=400)
        if kind.code == CostCenter.KIND_BRANCH:
            return JsonResponse(
                {"error": "Branch cost centers are created automatically from Broiler > Master > Branch — add the Branch there instead."},
                status=400,
            )

        try:
            cc = CostCenter.objects.create(
                company=_default_company(), name=data["name"], kind=kind,
                parent_id=data.get("parent") or None,
                is_active=bool(data.get("is_active", True)),
            )
            return JsonResponse({"message": "Saved", "id": cc.id, "code": cc.code}, status=201)
        except (KeyError, ValidationError) as e:
            return JsonResponse({"error": str(e)}, status=400)
        except IntegrityError:
            return JsonResponse({"error": "A cost center with this code may already exist."}, status=400)

    def put(self, request, id):
        try:
            cc = CostCenter.objects.select_related("kind").get(id=id)
        except CostCenter.DoesNotExist:
            raise Http404("Cost center not found")

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        kind = Sector.objects.filter(id=data.get("kind", cc.kind_id)).first()
        if not kind:
            return JsonResponse({"error": "Invalid kind"}, status=400)
        if cc.branch_id and kind.code != CostCenter.KIND_BRANCH:
            return JsonResponse(
                {"error": "This cost center is auto-linked to a Branch and must stay Kind = Branch Office."}, status=400
            )
        if not cc.branch_id and kind.code == CostCenter.KIND_BRANCH:
            return JsonResponse(
                {"error": "Branch cost centers are created automatically from Broiler > Master > Branch — this one isn't linked to a Branch."},
                status=400,
            )
        parent_id = data.get("parent") or None
        if parent_id and int(parent_id) == cc.id:
            return JsonResponse({"error": "A cost center cannot be its own parent"}, status=400)

        try:
            # Name/active state are driven by the linked Branch, not editable here.
            cc.name = cc.branch.branch_name if cc.branch_id else data.get("name", cc.name)
            cc.kind = kind
            cc.parent_id = parent_id
            cc.is_active = cc.branch.is_active if cc.branch_id else bool(data.get("is_active", cc.is_active))
            cc.full_clean(exclude=["code"])
            cc.save()
            return JsonResponse({"message": "Updated"})
        except ValidationError as e:
            return JsonResponse({"error": "; ".join(e.messages)}, status=400)
        except IntegrityError:
            return JsonResponse({"error": "A cost center with this code may already exist."}, status=400)

    def delete(self, request, id):
        try:
            cc = CostCenter.objects.get(id=id)
        except CostCenter.DoesNotExist:
            raise Http404("Cost center not found")
        if cc.branch_id:
            return JsonResponse(
                {"error": "This cost center is auto-linked to a Branch — delete/deactivate the Branch instead."},
                status=400,
            )
        try:
            cc.delete()
        except ProtectedError as e:
            related = sorted({str(obj._meta.verbose_name) for obj in list(e.protected_objects)[:50]})
            names = ", ".join(related) if related else "other records"
            return JsonResponse(
                {"error": f"Cannot delete: this cost center is used in {names}."}, status=400
            )
        return JsonResponse({"message": "Deleted"})


# ---------------------------------------------------------------------------
# Cost Center Mapping (Account > Master > Cost Center Mapping)
# ---------------------------------------------------------------------------
# Separate from the Cost Center master on purpose: that page only names/codes
# a cost center; this page is the one place that says which Office(s) route
# their postings to it. Entirely manual — no auto-creation, no auto-sync —
# built on the same generic Mapping table Inventory > Office Mapping uses,
# under its own type so it doesn't show up on that screen.

@login_required
def cost_center_mapping(request):
    return render(request, "cost_center_mapping.html")


@login_required
def cost_center_mapping_data(request):
    mapped = dict(
        Mapping.objects.filter(type=Mapping.TYPE_OFFICE_COST_CENTER, to_id__isnull=False)
        .values_list("from_id", "to_id")
    )
    cost_center_names = dict(CostCenter.objects.values_list("id", "name"))
    offices = [
        {
            "id": office.id, "name": office.name,
            "cost_center_id": mapped.get(office.id),
            "cost_center_name": cost_center_names.get(mapped.get(office.id), ""),
        }
        for office in Warehouse.objects.order_by("name")
    ]
    cost_centers = list(CostCenter.objects.order_by("code").values("id", "code", "name"))
    return JsonResponse({"offices": offices, "cost_centers": cost_centers})


@login_required
def cost_center_mapping_save(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    office_id = data.get("office")
    cost_center_id = data.get("cost_center") or None
    if not office_id:
        return JsonResponse({"error": "Office is required"}, status=400)
    if not Warehouse.objects.filter(id=office_id).exists():
        return JsonResponse({"error": "Office not found"}, status=404)
    if cost_center_id and not CostCenter.objects.filter(id=cost_center_id).exists():
        return JsonResponse({"error": "Cost center not found"}, status=404)

    if cost_center_id is None:
        Mapping.objects.filter(type=Mapping.TYPE_OFFICE_COST_CENTER, from_id=office_id).delete()
    else:
        Mapping.objects.update_or_create(
            type=Mapping.TYPE_OFFICE_COST_CENTER, from_id=office_id,
            defaults={"to_id": cost_center_id},
        )
    return JsonResponse({"message": "Mapping saved"})


@login_required
def cost_center_report(request):
    return render(request, "cost_center_report.html")


@login_required
def branch_summary_report(request):
    return render(request, "branch_summary_report.html")


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

