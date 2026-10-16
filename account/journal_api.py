"""REST APIs for the journal engine.

Routes (account/urls.py):
    GET  /api/vouchers/                 list (paginated, filterable)
    GET  /api/vouchers/cards/           the register's four figures
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
from django.db.models import Sum
from django.core.exceptions import ValidationError
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.clickjacking import xframe_options_sameorigin

from account.api_views import _audit, _company, _get_account, _parse_body, MAX_PAGE_SIZE
from account.models import FinancialYear, Voucher
from account.services import journal
from user.access import user_can


def _serialize_voucher(voucher, with_lines=False, edit_count=0):
    data = {
        "id": voucher.id,
        "edit_count": edit_count,
        "voucher_no": voucher.voucher_no or f"DRAFT-{voucher.id}",
        "voucher_type": voucher.voucher_type,
        "date": voucher.date.strftime("%Y-%m-%d"),
        "financial_year": journal.fy_label(voucher.financial_year),
        "narration": voucher.narration,
        "auto_narration": voucher.auto_narration,
        "narration_source": voucher.narration_source,
        "narration_edited_at": (voucher.narration_edited_at
                                and timezone.localtime(voucher.narration_edited_at).strftime("%d-%b-%Y %H:%M")),
        "reference": voucher.reference,
        "sector": voucher.sector_id,
        "sector_name": voucher.sector.name if voucher.sector_id else None,
        "status": voucher.status,
        "system_generated": voucher.system_generated,
        "total_debit": str(voucher.total_debit),
        "total_credit": str(voucher.total_credit),
        "created_by": voucher.created_by and voucher.created_by.get_username(),
        "posted_at": (voucher.posted_at
                      and timezone.localtime(voucher.posted_at).strftime("%d-%b-%Y %H:%M")),
        "cancelled_at": (voucher.cancelled_at
                         and timezone.localtime(voucher.cancelled_at).strftime("%d-%b-%Y %H:%M")),
        "cancel_reason": voucher.cancel_reason,
    }
    # The documents that justify it, so one fetch fills the whole screen.
    data["attachments"] = [
        {"id": a.pk, "name": a.file_name, "url": a.file.url, "type": a.file_type}
        for a in voucher.attachments.all()
    ]
    if with_lines:
        data["lines"] = [
            {
                "line_no": line.line_no,
                "account": line.account_id,
                "account_code": line.account.code,
                "account_name": line.account.description,
                "cost_center": line.cost_center_id,
                "cost_center_name": f"{line.cost_center.code} - {line.cost_center.name}" if line.cost_center_id else None,
                "debit": str(line.debit),
                "credit": str(line.credit),
                "narration": line.narration,
            }
            for line in voucher.lines.select_related("account", "cost_center").order_by("line_no")
        ]
    return data


def _get_voucher(company, id):
    voucher = Voucher.objects.filter(company=company, pk=id).select_related("financial_year").first()
    if voucher is None:
        raise Http404("Voucher not found")
    return voucher


def _forbidden(action):
    return JsonResponse(
        {"error": f"You do not have permission to {action} vouchers."}, status=403)


@login_required
def voucher_cards(request):
    """Posted today, posted this month, drafts waiting, cancelled this month.

    Counted over the company, not over whatever the register is filtered to:
    a figure that moves with the filter under it tells you nothing you could
    not already see.
    """
    company = _company(request)
    today = timezone.localdate()
    month_start = today.replace(day=1)
    vouchers = Voucher.objects.filter(company=company)
    posted = vouchers.filter(status="Posted")

    def total(qs):
        return qs.aggregate(t=Sum("total_debit"))["t"] or 0

    return JsonResponse({
        "today": str(total(posted.filter(date=today))),
        "month": str(total(posted.filter(date__gte=month_start, date__lte=today))),
        "month_count": posted.filter(date__gte=month_start, date__lte=today).count(),
        "drafts": vouchers.filter(status="Draft").count(),
        "cancelled": vouchers.filter(status="Cancelled",
                                     date__gte=month_start, date__lte=today).count(),
        "month_from": month_start.strftime("%Y-%m-%d"),
        "today_date": today.strftime("%Y-%m-%d"),
    })


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
        vouchers = list(qs[offset:offset + page_size])
        # One batched query for "how many times has this voucher been edited
        # in a way the Transaction History report shows" rather than a query
        # per row — the report icon reads the count to color itself.
        from collections import Counter

        from alerts.models import AuditLog

        displayed_fields = {"date", "narration", "reference", "total_debit", "total_credit"}
        edit_counts = Counter(
            object_id for object_id, changed_fields in AuditLog.objects.filter(
                model_name="account.Voucher",
                object_id__in=[str(v.pk) for v in vouchers],
                action__in=("update", "status_change"),
            ).values_list("object_id", "changed_fields")
            if displayed_fields & set(changed_fields)
        )
        return JsonResponse({
            "count": qs.count(),
            "page": page,
            "results": [_serialize_voucher(v, edit_count=edit_counts.get(str(v.pk), 0))
                       for v in vouchers],
        })

    def post(self, request):
        if not user_can(request.user, "vouchers", "add"):
            return _forbidden("add")
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
        if not user_can(request.user, "vouchers", "view"):
            return _forbidden("view")
        company = _company(request)
        return JsonResponse(_serialize_voucher(_get_voucher(company, id), with_lines=True))

    def put(self, request, id):
        if not user_can(request.user, "vouchers", "edit"):
            return _forbidden("edit")
        data = _parse_body(request)
        company = _company(request)
        voucher = _get_voucher(company, id)
        try:
            if voucher.status == "Posted":
                # One click, matching what Petty Expense's Save & Repost
                # does for a user: edit a posted entry and save it. The
                # voucher row, its id and its number never change — see
                # journal.repost_voucher's docstring for why it is not the
                # same mechanism as petty_expense.repost.
                voucher = journal.repost_voucher(
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
            else:
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
        if not user_can(request.user, "vouchers", "delete"):
            return _forbidden("delete")
        company = _company(request)
        voucher = _get_voucher(company, id)
        if voucher.status == "Cancelled":
            return JsonResponse({"error": "A cancelled voucher is already off the books."}, status=400)
        if voucher.status == "Posted":
            # Same trade Petty Expense's Delete makes on its own voucher: the
            # lines come off the ledger entirely rather than staying (as
            # Cancel leaves them) for the audit trail. A system-generated
            # voucher is owned by whatever module posted it (Petty Expense,
            # a sale, ...) — it is deleted from there, not from this list.
            if voucher.system_generated:
                return JsonResponse(
                    {"error": "This voucher was posted automatically by another module; delete it from there."},
                    status=400)
            if FinancialYear.objects.get(pk=voucher.financial_year_id).state == "Locked":
                return JsonResponse({"error": "The financial year is locked; the voucher cannot be deleted."}, status=400)
        was_posted = voucher.status == "Posted"
        voucher.delete()
        return JsonResponse({"message": "Voucher deleted." if was_posted else "Draft voucher deleted."})


@method_decorator(login_required, name="dispatch")
class VoucherAttachmentAPI(View):
    """Bills and advices on a voucher: add one, or take one off a draft."""

    ALLOWED = {"application/pdf", "image/jpeg", "image/png", "image/jpg"}
    LIMIT = 5 * 1024 * 1024

    def post(self, request, id, attachment_id=None):
        if not user_can(request.user, "vouchers", "edit"):
            return _forbidden("edit")
        from account.models import VoucherAttachment

        company = _company(request)
        voucher = _get_voucher(company, id)

        if attachment_id is not None:              # removing one
            if voucher.status != "Draft":
                return JsonResponse(
                    {"error": "A posted voucher keeps its documents."}, status=400)
            get_object_or_404(VoucherAttachment, pk=attachment_id,
                              voucher=voucher).delete()
            return JsonResponse({"removed": attachment_id})

        saved, refused = [], []
        for upload in request.FILES.getlist("files"):
            if upload.content_type not in self.ALLOWED:
                refused.append(f"{upload.name}: only PDF, JPG and PNG are accepted.")
                continue
            if upload.size > self.LIMIT:
                refused.append(f"{upload.name}: larger than 5 MB.")
                continue
            row = VoucherAttachment.objects.create(
                voucher=voucher, file=upload, file_name=upload.name[:255],
                file_type=upload.content_type, uploaded_by=request.user)
            saved.append({"id": row.pk, "name": row.file_name,
                          "url": row.file.url, "type": row.file_type})
        return JsonResponse({"saved": saved, "refused": refused},
                            status=400 if refused and not saved else 200)


@method_decorator(login_required, name="dispatch")
class VoucherPostAPI(View):
    def post(self, request, id):
        if not user_can(request.user, "vouchers", "edit"):
            return _forbidden("post")
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
        if not user_can(request.user, "vouchers", "delete"):
            return _forbidden("cancel")
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
                    "cost_center": row["cost_center"],
                    "cost_center_code": row["cost_center_code"],
                    "debit": str(row["debit"]),
                    "credit": str(row["credit"]),
                    "balance": str(abs(row["balance"])),
                    "balance_side": "Dr" if row["balance"] >= 0 else "Cr",
                }
                for row in statement["rows"]
            ],
        })


@method_decorator(login_required, name="dispatch")
class BranchSummaryReportAPI(View):
    def get(self, request):
        company = _company(request)
        report = journal.branch_summary_report(
            company,
            date_from=request.GET.get("from") or None,
            date_to=request.GET.get("to") or None,
        )
        return JsonResponse({
            "rows": [
                {key: (str(value) if key in ("debit", "credit", "net") else value)
                 for key, value in row.items()}
                for row in report["rows"]
            ],
            "totals": {key: str(value) for key, value in report["totals"].items()},
        })


@method_decorator(login_required, name="dispatch")
class CostCenterReportAPI(View):
    def get(self, request):
        company = _company(request)
        report = journal.cost_center_report(
            company,
            date_from=request.GET.get("from") or None,
            date_to=request.GET.get("to") or None,
            category=request.GET.get("category") or None,
        )
        return JsonResponse({
            "rows": [
                {key: (str(value) if key in ("debit", "credit", "net") else value)
                 for key, value in row.items()}
                for row in report["rows"]
            ],
            "totals": {key: str(value) for key, value in report["totals"].items()},
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


@login_required
@xframe_options_sameorigin
def voucher_transaction_history(request, id):
    """Transaction History Report — every alerts.AuditLog entry for one
    Voucher, same report shape as inventory's and account's other versions.

    Reuses the audit trail every model already writes to (see
    alerts.signals) rather than adding separate change-tracking. Vouchers
    also log a ``status_change`` action (Draft -> Posted -> Cancelled),
    which gets the same "Edit" treatment here as a plain update.
    """
    from alerts.models import AuditLog

    company = _company(request)
    voucher = get_object_or_404(Voucher, pk=id, company=company)
    logs = list(AuditLog.objects.filter(
        model_name="account.Voucher", object_id=str(id)
    ).order_by("created_at"))

    ACTION_LABELS = {
        "create": "Entry Added", "update": "Edit", "status_change": "Edit",
        "delete": "Deleted", "bulk_create": "Entry Added", "bulk_update": "Edit",
        "bulk_delete": "Deleted", "soft_delete": "Deleted",
    }
    # Report column -> the field name(s) that back it, so an edit row can
    # highlight only the values that actually changed.
    COLUMN_FIELDS = {
        "date": ("date",),
        "narration": ("narration",),
        "reference": ("reference",),
        "total_debit": ("total_debit",),
        "total_credit": ("total_credit",),
    }
    # A handful of older rows may have no real `create` audit entry (seeded
    # before this model was wired into the audit signal) — the earliest
    # logged event is still the first *known* state, shown as Entry Added
    # rather than the report having nothing to say about how it came to be.
    first_log_id = logs[0].pk if logs else None

    rows = []
    sl_no = 0
    for log in logs:
        changed = {
            column for column, fields in COLUMN_FIELDS.items()
            if any(f in log.changed_fields for f in fields)
        }
        is_origin = log.action == "create" or log.pk == first_log_id
        # A save that only touched a field this report doesn't show (status,
        # posted_by, ...) isn't a transaction edit as far as this report is
        # concerned.
        if not is_origin and not changed:
            continue

        snapshot = log.after or log.before
        sl_no += 1
        rows.append({
            "sl_no": sl_no,
            "log": log,
            "activity_type": "Entry Added" if is_origin else ACTION_LABELS.get(log.action, log.get_action_display()),
            "is_origin": is_origin,
            "date": snapshot.get("date") or voucher.date,
            "narration": snapshot.get("narration") or voucher.narration,
            "reference": snapshot.get("reference") or voucher.reference,
            "total_debit": snapshot.get("total_debit") or voucher.total_debit,
            "total_credit": snapshot.get("total_credit") or voucher.total_credit,
            "changed": changed,
        })

    return render(request, "voucher_transaction_history.html", {
        "voucher": voucher,
        "rows": rows,
    })
