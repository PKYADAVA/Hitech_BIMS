"""REST APIs for the journal engine.

Routes (account/urls.py):
    GET  /api/vouchers/                 list (paginated, filterable)
    POST /api/vouchers/                 create draft; {"post": true} posts immediately
    GET  /api/vouchers/<id>/            detail with lines
    PUT  /api/vouchers/<id>/            update (drafts only)
    DELETE /api/vouchers/<id>/          delete (drafts only; posted must be cancelled)
    POST /api/vouchers/<id>/post/       post a draft (assigns voucher number)
    POST /api/vouchers/<id>/cancel/     cancel a posted voucher (reason kept)
    GET  /api/chart-of-accounts/<id>/ledger/   ledger statement (?from&to)
    GET  /api/reports/trial-balance/           trial balance (?from&to)
"""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View

from account.api_views import _audit, _company, _get_account, _parse_body, MAX_PAGE_SIZE
from account.models import Voucher
from account.services import journal


def _serialize_voucher(voucher, with_lines=False):
    data = {
        "id": voucher.id,
        "voucher_no": voucher.voucher_no or f"DRAFT-{voucher.id}",
        "voucher_type": voucher.voucher_type,
        "date": voucher.date.strftime("%Y-%m-%d"),
        "financial_year": journal.fy_label(voucher.financial_year),
        "narration": voucher.narration,
        "auto_narration": voucher.auto_narration,
        "narration_source": voucher.narration_source,
        "narration_edited_at": voucher.narration_edited_at and voucher.narration_edited_at.strftime("%d-%b-%Y %H:%M"),
        "reference": voucher.reference,
        "sector": voucher.sector_id,
        "sector_name": voucher.sector.name if voucher.sector_id else None,
        "status": voucher.status,
        "system_generated": voucher.system_generated,
        "total_debit": str(voucher.total_debit),
        "total_credit": str(voucher.total_credit),
        "created_by": voucher.created_by and voucher.created_by.get_username(),
        "posted_at": voucher.posted_at and voucher.posted_at.strftime("%d-%b-%Y %H:%M"),
        "cancelled_at": voucher.cancelled_at and voucher.cancelled_at.strftime("%d-%b-%Y %H:%M"),
        "cancel_reason": voucher.cancel_reason,
    }
    if with_lines:
        data["lines"] = [
            {
                "line_no": line.line_no,
                "account": line.account_id,
                "account_code": line.account.code,
                "account_name": line.account.description,
                "cost_center": line.cost_center_id,
                "debit": str(line.debit),
                "credit": str(line.credit),
                "narration": line.narration,
            }
            for line in voucher.lines.select_related("account").order_by("line_no")
        ]
    return data


def _get_voucher(company, id):
    voucher = Voucher.objects.filter(company=company, pk=id).select_related("financial_year").first()
    if voucher is None:
        raise Http404("Voucher not found")
    return voucher


@method_decorator(login_required, name="dispatch")
class VoucherListCreateAPI(View):
    def get(self, request):
        company = _company(request)
        qs = Voucher.objects.filter(company=company).select_related("financial_year", "created_by", "sector")
        for param, field in [
            ("type", "voucher_type"),
            ("status", "status"),
            ("date_from", "date__gte"),
            ("date_to", "date__lte"),
            ("account", "lines__account_id"),
            ("sector", "sector_id"),
        ]:
            value = request.GET.get(param)
            if value:
                qs = qs.filter(**{field: value})
        q = request.GET.get("q", "").strip()
        if q:
            from django.db.models import Q
            qs = qs.filter(Q(voucher_no__icontains=q) | Q(narration__icontains=q) | Q(reference__icontains=q))
        qs = qs.distinct()
        try:
            page = max(int(request.GET.get("page", 1)), 1)
            page_size = min(int(request.GET.get("page_size", 50)), MAX_PAGE_SIZE)
        except ValueError:
            return JsonResponse({"error": "Invalid pagination parameters."}, status=400)
        offset = (page - 1) * page_size
        return JsonResponse({
            "count": qs.count(),
            "page": page,
            "results": [_serialize_voucher(v) for v in qs[offset:offset + page_size]],
        })

    def post(self, request):
        data = _parse_body(request)
        company = _company(request)
        try:
            voucher = journal.create_voucher(
                company=company,
                date=data.get("date"),
                lines_data=data.get("lines", []),
                user=request.user,
                voucher_type=data.get("voucher_type", "Journal"),
                narration=data.get("narration", ""),
                reference=data.get("reference", ""),
                sector=data.get("sector"),
                post=bool(data.get("post")),
                auto_narration=data.get("auto_narration"),
                narration_source=data.get("narration_source"),
            )
        except ValidationError as exc:
            return JsonResponse({"error": "; ".join(exc.messages)}, status=400)
        except Exception as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        _audit(request, "create", company=company,
               new={"voucher": voucher.voucher_no or f"DRAFT-{voucher.id}", "total": str(voucher.total_debit)},
               reason=f"Voucher {voucher.voucher_type}")
        return JsonResponse(_serialize_voucher(voucher, with_lines=True), status=201)


@method_decorator(login_required, name="dispatch")
class VoucherDetailAPI(View):
    def get(self, request, id):
        company = _company(request)
        return JsonResponse(_serialize_voucher(_get_voucher(company, id), with_lines=True))

    def put(self, request, id):
        data = _parse_body(request)
        company = _company(request)
        voucher = _get_voucher(company, id)
        try:
            journal.update_draft(
                voucher,
                date=data.get("date", voucher.date),
                lines_data=data.get("lines", []),
                user=request.user,
                narration=data.get("narration"),
                reference=data.get("reference"),
                sector=data["sector"] if "sector" in data else Ellipsis,
                auto_narration=data.get("auto_narration"),
                narration_source=data.get("narration_source"),
            )
        except ValidationError as exc:
            return JsonResponse({"error": "; ".join(exc.messages)}, status=400)
        return JsonResponse(_serialize_voucher(voucher, with_lines=True))

    def delete(self, request, id):
        company = _company(request)
        voucher = _get_voucher(company, id)
        if voucher.status != "Draft":
            return JsonResponse({"error": "Only draft vouchers can be deleted; cancel posted vouchers instead."}, status=400)
        voucher.delete()
        return JsonResponse({"message": "Draft voucher deleted."})


@method_decorator(login_required, name="dispatch")
class VoucherPostAPI(View):
    def post(self, request, id):
        company = _company(request)
        voucher = _get_voucher(company, id)
        try:
            journal.post_voucher(voucher, user=request.user)
        except ValidationError as exc:
            return JsonResponse({"error": "; ".join(exc.messages)}, status=400)
        _audit(request, "update", company=company,
               new={"voucher": voucher.voucher_no, "status": "Posted"}, reason="Voucher posted")
        return JsonResponse(_serialize_voucher(voucher))


@method_decorator(login_required, name="dispatch")
class VoucherCancelAPI(View):
    def post(self, request, id):
        data = _parse_body(request)
        company = _company(request)
        voucher = _get_voucher(company, id)
        try:
            journal.cancel_voucher(voucher, user=request.user, reason=data.get("reason", ""))
        except ValidationError as exc:
            return JsonResponse({"error": "; ".join(exc.messages)}, status=400)
        _audit(request, "update", company=company,
               old={"voucher": voucher.voucher_no, "status": "Posted"},
               new={"status": "Cancelled"}, reason=voucher.cancel_reason)
        return JsonResponse(_serialize_voucher(voucher))


@method_decorator(login_required, name="dispatch")
class AccountLedgerAPI(View):
    def get(self, request, id):
        company = _company(request)
        account = _get_account(company, id)
        statement = journal.account_ledger(
            account,
            date_from=request.GET.get("from") or None,
            date_to=request.GET.get("to") or None,
        )
        def side(value):
            return {"amount": str(abs(value)), "side": "Dr" if value >= 0 else "Cr"}
        return JsonResponse({
            "account": {"id": account.id, "code": account.code, "description": account.description},
            "opening": side(statement["opening"]),
            "closing": side(statement["closing"]),
            "rows": [
                {
                    "date": row["date"].strftime("%d-%b-%Y"),
                    "voucher_id": row["voucher_id"],
                    "voucher_no": row["voucher_no"],
                    "voucher_type": row["voucher_type"],
                    "narration": row["narration"],
                    "debit": str(row["debit"]),
                    "credit": str(row["credit"]),
                    "balance": str(abs(row["balance"])),
                    "balance_side": "Dr" if row["balance"] >= 0 else "Cr",
                }
                for row in statement["rows"]
            ],
        })


@method_decorator(login_required, name="dispatch")
class TrialBalanceAPI(View):
    def get(self, request):
        company = _company(request)
        report = journal.trial_balance(
            company,
            date_from=request.GET.get("from") or None,
            date_to=request.GET.get("to") or None,
        )
        return JsonResponse({
            "rows": [
                {key: (str(value) if key not in ("account_id", "code", "description", "account_type") else value)
                 for key, value in row.items()}
                for row in report["rows"]
            ],
            "totals": {key: str(value) for key, value in report["totals"].items()},
        })


def _serialize_pl_rows(rows):
    return [
        {key: (str(value) if key == "amount" else value) for key, value in row.items()}
        for row in rows
    ]


@method_decorator(login_required, name="dispatch")
class ProfitAndLossAPI(View):
    def get(self, request):
        company = _company(request)
        report = journal.profit_and_loss(
            company,
            date_from=request.GET.get("from") or None,
            date_to=request.GET.get("to") or None,
        )
        return JsonResponse({
            "income": _serialize_pl_rows(report["income"]),
            "cogs": _serialize_pl_rows(report["cogs"]),
            "expense": _serialize_pl_rows(report["expense"]),
            "total_income": str(report["total_income"]),
            "total_cogs": str(report["total_cogs"]),
            "gross_profit": str(report["gross_profit"]),
            "total_expense": str(report["total_expense"]),
            "net_profit": str(report["net_profit"]),
        })


@method_decorator(login_required, name="dispatch")
class BalanceSheetAPI(View):
    def get(self, request):
        company = _company(request)
        report = journal.balance_sheet(company, date_upto=request.GET.get("to") or None)
        return JsonResponse({
            "assets": _serialize_pl_rows(report["assets"]),
            "liabilities": _serialize_pl_rows(report["liabilities"]),
            "equity": _serialize_pl_rows(report["equity"]),
            "total_assets": str(report["total_assets"]),
            "total_liabilities": str(report["total_liabilities"]),
            "total_equity_recorded": str(report["total_equity_recorded"]),
            "current_earnings": str(report["current_earnings"]),
            "total_equity": str(report["total_equity"]),
            "total_liabilities_and_equity": str(report["total_liabilities_and_equity"]),
            "balanced": report["balanced"],
        })
