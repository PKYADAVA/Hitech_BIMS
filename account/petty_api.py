"""Petty expense: the page, the list, and the four things a user can do to one.

Kept apart from ``account.views`` because it is a transaction screen rather
than a master, and apart from ``journal_api`` because it posts through that
engine instead of alongside it.
"""
import json
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from account.models import (BankCashMaster, PaymentMode, PettyExpense,
                            PettyExpenseAttachment, PettyExpenseItem)
from account.services import petty_expense as service
from broiler.models import Branch, BroilerFarm, BroilerFarmShed
from inventory.models import UnitOfMeasurement
from user.access import user_can
from user.services.scoping import branches_for, farms_for, scope_queryset

ZERO = Decimal("0")


def _int(value):
    """A picker's value as the integer a foreign key holds.

    The form sends its selections as strings. Assigning "2" to a ``*_id``
    leaves it a string in memory until the row is re-read, and a later
    ``farm.branch_id != branch_id`` then compares 2 with "2" and reports a
    farm as belonging to another branch. Coerced once, here.
    """
    if value in (None, "", "null"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _tidy(value, limit=None):
    """One space between words, none at the ends."""
    text = " ".join(str(value or "").split())
    return text[:limit] if limit else text


def _proper(value, limit=None):
    """Proper case for a name, leaving anything the typist capitalised alone.

    A word typed in lower case is capitalised; "HDFC", "UPPCL" and "McLeod"
    are left as they are, because someone who typed capitals meant them and
    title-casing would give "Hdfc" and "Mcleod".
    """
    # Joining words stay small unless they start the name: "Ram & Sons of
    # Akbarpur", not "Ram & Sons Of Akbarpur".
    small = {"and", "or", "of", "the", "for", "to", "in", "at", "on", "by"}
    words = []
    for index, word in enumerate(_tidy(value).split(" ")):
        if not word.islower():
            words.append(word)                       # capitals were meant
        elif index and word in small:
            words.append(word)
        else:
            words.append(word.capitalize())
    return _tidy(" ".join(words), limit)


def _sentence(value, limit=None):
    """A sentence: first letter up, the rest as written.

    Not title case -- "Tea For The Vaccination Team" reads like a headline,
    and these are descriptions.
    """
    text = _tidy(value)
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    return text[:limit] if limit else text


def _reference(value, limit=None):
    """A document number, in the case every other document number here uses."""
    return _tidy(value, limit).upper()


def _dec(value, default=ZERO):
    try:
        return Decimal(str(value).replace(",", "").strip() or default)
    except (InvalidOperation, AttributeError, ValueError):
        return default


def _masters(user=None):
    """Everything the form picks from, in one payload.

    All of it comes from masters that already exist -- branches, farms, sheds,
    cost centres, payment modes, bank/cash accounts, units, and the expense
    side of the chart of accounts. Nothing here is a list this module owns.
    """
    from account.services.bank_cash import payment_mode_map

    # Only what this user is allowed to work in. The same service the rest of
    # the ERP uses, so one Web-Access setting governs every screen.
    branch_qs = branches_for(user)
    farm_qs = farms_for(user)
    branches = list(branch_qs.order_by("branch_name").values("id", "branch_name"))
    farms = list(farm_qs.order_by("farm_name")
                 .values("id", "farm_name", "branch_id"))
    sheds = list(BroilerFarmShed.objects.filter(farm__in=farm_qs)
                 .order_by("farm__farm_code", "unit_no")
                 .values("id", "farm_id", "shed_name", "shed_code", "unit_no"))
    # A branch already owns a cost centre in this ERP, so the mapping the spec
    # asks for exists: it is read, not entered.
    centres = [{"id": b.organization_centre.id if hasattr(b, "organization_centre") and b.organization_centre else None,
                "branch_id": b.id,
                "name": (b.organization_centre.name
                         if hasattr(b, "organization_centre") and b.organization_centre else "")}
               for b in branch_qs.select_related("organization_centre")]
    return {
        "branches": branches,
        "farms": farms,
        "sheds": [{"id": s["id"], "farm_id": s["farm_id"],
                   "label": (s["shed_name"] or s["shed_code"] or f"Unit {s['unit_no']}")}
                  for s in sheds],
        "centres": [c for c in centres if c["id"]],
        "categories": service.expense_categories(),
        "paid_from": service.paid_from_accounts(),
        # Cash only, at both ends: a petty expense is money leaving the cash
        # box, so the pickers offer nothing that could take it elsewhere.
        "modes": service.cash_payment_modes(),
        "mode_accounts": payment_mode_map("payment"),
        "banks": service.bank_accounts(),
        "uoms": list(UnitOfMeasurement.objects.order_by("name").values("id", "name")),
        # The years the register can actually show, so the picker offers no
        # year that would come back empty. This year is always offered.
        "years": sorted({d.year for d in PettyExpense.objects.values_list(
            "expense_date", flat=True)} | {timezone.localdate().year}, reverse=True),
    }


# Never cached: these pages change with the data and with the code, and a
# browser holding yesterday's copy is indistinguishable from a bug.
def _visible(request):
    """The expenses this user may see, by the ERP's own branch and farm scopes.

    A farm is optional on an expense, so scope_or_null would be wrong here:
    the branch is always set, and it is the branch that decides.
    """
    return scope_queryset(request.user, PettyExpense.objects.all(),
                          "branches", "branch_id")


def _mine(request, id):
    """One expense, or a 404 if it belongs to a branch this user cannot see."""
    return get_object_or_404(_visible(request), pk=id)


@never_cache
@login_required
def petty_expense_list(request):
    """The register, its filters and the four figures above it."""
    return render(request, "petty_expense.html", {
        "masters": _masters(request.user),
        "today": timezone.localdate().isoformat(),
    })


# Never cached: these pages change with the data and with the code, and a
# browser holding yesterday's copy is indistinguishable from a bug.
@never_cache
@login_required
def petty_expense_form(request, id=None):
    """The entry screen. With an id, it opens an existing expense."""
    expense = None
    if id:
        expense = _mine(request, id)
    return render(request, "petty_expense_form.html", {
        "masters": _masters(request.user),
        "expense": expense,
        "today": timezone.localdate().isoformat(),
        "next_no": PettyExpense.next_expense_no(service.company()),
    })


@login_required
def petty_expense_rows(request):
    """The register's rows, filtered — and the figures for the cards above it."""
    qs = (_visible(request)
          .select_related("branch", "farm", "shed", "paid_from", "payment_mode",
                          "cost_centre", "journal")
          .prefetch_related("items__account", "attachments"))

    get = request.GET
    date_from = parse_date(get.get("from") or "")
    date_to = parse_date(get.get("to") or "")
    if date_from:
        qs = qs.filter(expense_date__gte=date_from)
    if date_to:
        qs = qs.filter(expense_date__lte=date_to)
    for field, param in (("branch_id", "branch"), ("farm_id", "farm"),
                         ("shed_id", "shed"), ("cost_centre_id", "centre"),
                         ("paid_from_id", "paid_from"), ("payment_mode_id", "mode")):
        value = get.get(param)
        if value:
            qs = qs.filter(**{field: value})
    # Month and year stand on their own: "September", or "2026", or both.
    if get.get("month"):
        qs = qs.filter(expense_date__month=get["month"])
    if get.get("year"):
        qs = qs.filter(expense_date__year=get["year"])
    if get.get("status"):
        qs = qs.filter(status=get["status"])
    if get.get("account"):
        qs = qs.filter(items__account_id=get["account"]).distinct()
    if get.get("paid_to"):
        qs = qs.filter(paid_to_name__icontains=get["paid_to"])
    if get.get("min"):
        qs = qs.filter(net_amount__gte=_dec(get["min"]))
    if get.get("max"):
        qs = qs.filter(net_amount__lte=_dec(get["max"]))
    if get.get("q"):
        term = get["q"]
        qs = qs.filter(Q(expense_no__icontains=term) | Q(paid_to_name__icontains=term)
                       | Q(narration__icontains=term) | Q(reference__icontains=term)
                       | Q(items__description__icontains=term)).distinct()

    rows = []
    for expense in qs[:500]:
        items = list(expense.items.all())
        rows.append({
            "id": expense.pk,
            "expense_no": expense.expense_no,
            "date": expense.expense_date.isoformat(),
            "branch": expense.branch.branch_name,
            "farm": expense.farm.farm_name if expense.farm_id else "",
            "shed": (expense.shed.shed_name or expense.shed.shed_code) if expense.shed_id else "",
            "centre": expense.cost_centre.name if expense.cost_centre_id else "",
            "category": ", ".join(sorted({(i.account.parent.description
                                           if i.account.parent_id else i.account.description)
                                          for i in items})),
            # One per account, not one per line: two lines charged to the
            # same ledger printed "Vaccination, Vaccination".
            "sub_category": ", ".join(sorted({i.account.description for i in items})),
            "paid_to": expense.paid_to_name,
            "mode": expense.payment_mode.name,
            "paid_from": str(expense.paid_from),
            "amount": float(expense.net_amount or 0),
            "status": expense.status,
            "attachments": len(expense.attachments.all()),
            "voucher_no": expense.journal.voucher_no if expense.journal_id else "",
            "editable": expense.is_editable,
        })

    # The cards. Today and this month count what is on the books, so a draft
    # nobody posted is not reported as money spent.
    today = timezone.localdate()
    mine = _visible(request)
    posted = mine.filter(status=PettyExpense.STATUS_POSTED)
    # Each cash box with its balance, and whether the policy calls it low.
    health = service.cash_health()
    cards = {
        "today": float(posted.filter(expense_date=today)
                       .aggregate(t=Sum("net_amount"))["t"] or 0),
        "month": float(posted.filter(expense_date__year=today.year,
                                     expense_date__month=today.month)
                       .aggregate(t=Sum("net_amount"))["t"] or 0),
        "drafts": mine.filter(status=PettyExpense.STATUS_DRAFT).count(),
        "cash": health,
    }
    return JsonResponse({"rows": rows, "cards": cards})


def _apply(expense, data, user):
    """Write the header from a payload, leaving what it does not mention."""
    expense.expense_date = parse_date(data.get("expense_date") or "") or timezone.localdate()
    expense.branch_id = _int(data.get("branch"))
    expense.farm_id = _int(data.get("farm"))
    expense.shed_id = _int(data.get("shed"))
    expense.cost_centre_id = _int(data.get("cost_centre"))
    expense.payment_mode_id = _int(data.get("payment_mode"))
    expense.paid_from_id = _int(data.get("paid_from"))
    expense.paid_to_name = _proper(data.get("paid_to_name"), 150)
    expense.reference = _reference(data.get("reference"), 100)
    expense.other_charges = _dec(data.get("other_charges"))
    expense.adjustment = _dec(data.get("adjustment"))
    expense.narration = _sentence(data.get("narration"))
    # One tag per name, properly cased, in the order they were given.
    seen, tags = set(), []
    for tag in str(data.get("tags") or "").split(","):
        tag = _proper(tag, 40)
        if tag and tag.lower() not in seen:
            seen.add(tag.lower())
            tags.append(tag)
    expense.tags = _tidy(", ".join(tags), 200)

    # A payee chosen from a master keeps the link; one typed at the counter is
    # just a name, which is what most petty expenses are.
    kind, payee_id = data.get("paid_to_type"), data.get("paid_to_id")
    if kind and payee_id:
        model = {"supplier": ("purchase", "supplier"),
                 "employee": ("hr", "employee")}.get(kind)
        if model:
            expense.paid_to_content_type = ContentType.objects.get(
                app_label=model[0], model=model[1])
            expense.paid_to_object_id = _int(payee_id)
    else:
        expense.paid_to_content_type = None
        expense.paid_to_object_id = None

    if not expense.company_id:
        expense.company = service.company()
    if expense._state.adding:
        expense.created_by = user
    expense.updated_by = user
    return expense


def _write_items(expense, rows):
    expense.items.all().delete()
    for index, row in enumerate(rows, start=1):
        if not row.get("account"):
            continue
        PettyExpenseItem(
            petty_expense=expense, line_no=index,
            account_id=_int(row["account"]),
            description=_sentence(row.get("description"), 255),
            quantity=_dec(row.get("quantity"), Decimal("1")),
            uom_id=_int(row.get("uom")),
            rate=_dec(row.get("rate")),
        ).save()


@login_required
@require_POST
@transaction.atomic
def petty_expense_save(request, id=None):
    """Save a draft, or save and post in one step.

    Posting goes through the same service the Post button uses, so a
    "Save & Post" and a "Save" followed by "Post" cannot disagree.
    """
    if not user_can(request.user, "petty_expense_list", "add" if not id else "edit"):
        return JsonResponse({"error": "Not permitted."}, status=403)

    data = json.loads(request.body.decode("utf-8") or "{}")
    expense = _mine(request, id) if id else PettyExpense()
    if id and not expense.is_editable:
        return JsonResponse(
            {"error": f"{expense.expense_no} is {expense.status.lower()} and cannot be edited."},
            status=400)
    # Something already posted stays posted: the correction goes back onto the
    # books rather than quietly dropping the expense to a draft.
    was_posted = bool(id) and expense.status == PettyExpense.STATUS_POSTED

    _apply(expense, data, request.user)
    if not expense.branch_id:
        return JsonResponse({"error": "Choose the branch."}, status=400)
    # The picker only offers branches in scope; a payload can still name one
    # that is not, and the server is where that has to be refused.
    if not branches_for(request.user).filter(pk=expense.branch_id).exists():
        return JsonResponse({"error": "That branch is not one of yours."}, status=403)
    expense.save()
    _write_items(expense, data.get("items") or [])
    expense.recalculate()
    if not expense.narration:
        expense.narration = service.compose_narration(expense)
    expense.save(update_fields=["subtotal", "net_amount", "narration", "updated_at"])

    # Said, not enforced: two identical payments on one day happen; two
    # identical entries of one payment happen more often.
    twin = service.duplicate_of(expense)
    warning = (f"{twin.expense_no} on the same day is also "
               f"{twin.net_amount:,.2f} to {twin.paid_to_name}." if twin else "")

    if was_posted:
        try:
            service.repost(expense, user=request.user)
        except service.PettyExpenseError as exc:
            # Nothing is half-done: the atomic block rolls the edit back, so
            # the expense and its voucher stay as they were.
            transaction.set_rollback(True)
            return JsonResponse({"error": str(exc), "id": expense.pk,
                                 "expense_no": expense.expense_no}, status=400)
    elif data.get("post"):
        try:
            service.post(expense, user=request.user)
        except service.PettyExpenseError as exc:
            # The draft is kept: the user fixes what the message names and
            # presses again, rather than typing it all in a second time.
            return JsonResponse({"error": str(exc), "id": expense.pk,
                                 "expense_no": expense.expense_no}, status=400)

    return JsonResponse({"id": expense.pk, "expense_no": expense.expense_no,
                         "status": expense.status,
                         "net_amount": float(expense.net_amount or 0),
                         "duplicate": warning,
                         "voucher_no": expense.journal.voucher_no if expense.journal_id else ""},
                        status=201 if not id else 200)


@login_required
@require_POST
def petty_cash_replenish(request):
    """Put money into a cash box, as a contra from a bank account."""
    if not user_can(request.user, "petty_expense_list", "add"):
        return JsonResponse({"error": "Not permitted."}, status=403)
    data = json.loads(request.body.decode("utf-8") or "{}")
    box = get_object_or_404(BankCashMaster, pk=_int(data.get("box")))
    bank = get_object_or_404(BankCashMaster, pk=_int(data.get("from")))
    try:
        voucher = service.replenish(
            box, _dec(data.get("amount")), bank,
            date=parse_date(data.get("date") or "") or timezone.localdate(),
            user=request.user, reference=_reference(data.get("reference"), 100),
            remark=_sentence(data.get("remark"), 255))
    except service.PettyExpenseError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"voucher_no": voucher.voucher_no,
                         "balance": float(service.balance_of(box) or 0)})


@login_required
@require_POST
def petty_expense_post(request, id):
    """Put an existing draft on the books."""
    if not user_can(request.user, "petty_expense_list", "edit"):
        return JsonResponse({"error": "Not permitted."}, status=403)
    expense = _mine(request, id)
    try:
        voucher = service.post(expense, user=request.user)
    except service.PettyExpenseError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"status": expense.status, "voucher_no": voucher.voucher_no})


@login_required
@require_POST
def petty_expense_cancel(request, id):
    """Reverse what it posted, and keep the record."""
    if not user_can(request.user, "petty_expense_list", "delete"):
        return JsonResponse({"error": "Not permitted."}, status=403)
    expense = _mine(request, id)
    reason = (json.loads(request.body.decode("utf-8") or "{}").get("reason") or "").strip()
    try:
        service.cancel(expense, user=request.user, reason=reason)
    except service.PettyExpenseError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"status": expense.status})


@login_required
@require_POST
def petty_expense_delete(request, id):
    """Throw the expense away, whatever state it is in.

    A draft has posted nothing, so it simply goes. A posted or cancelled one
    takes its voucher with it: the voucher's lines go, so the money returns to
    the account it left and the ledger, the trial balance and the cost-centre
    report all stop counting it.

    What that costs is a gap in the voucher numbering, which cancelling would
    not leave -- so the screen says so before it happens, and the deletion
    itself is recorded in the audit log.
    """
    if not user_can(request.user, "petty_expense_list", "delete"):
        return JsonResponse({"error": "Not permitted."}, status=403)
    expense = _mine(request, id)

    voucher = expense.journal          # read before the row goes
    voucher_no = voucher.voucher_no if voucher else ""

    # The bills go with it; nothing else refers to them.
    for attachment in expense.attachments.all():
        attachment.file.delete(save=False)
    number = expense.expense_no
    with transaction.atomic():
        expense.delete()
        if voucher is not None:
            voucher.delete()           # its lines go with it, and so does its effect
    return JsonResponse({"deleted": id, "expense_no": number,
                         "voucher_no": voucher_no})


@login_required
def petty_expense_detail(request, id):
    """One expense, in full: its lines, its bills and what it posted."""
    expense = get_object_or_404(_visible(request).select_related(
        "branch", "farm", "shed", "cost_centre", "paid_from", "payment_mode",
        "journal", "created_by", "posted_by", "cancelled_by"), pk=id)
    return JsonResponse({
        "id": expense.pk,
        "expense_no": expense.expense_no,
        "expense_date": expense.expense_date.isoformat(),
        "branch": expense.branch_id, "farm": expense.farm_id, "shed": expense.shed_id,
        "cost_centre": expense.cost_centre_id,
        "paid_to_name": expense.paid_to_name,
        "payment_mode": expense.payment_mode_id,
        "paid_from": expense.paid_from_id,
        "reference": expense.reference,
        "other_charges": float(expense.other_charges or 0),
        "adjustment": float(expense.adjustment or 0),
        "subtotal": float(expense.subtotal or 0),
        "net_amount": float(expense.net_amount or 0),
        "narration": expense.narration,
        "tags": expense.tags,
        "status": expense.status,
        "editable": expense.is_editable,
        "items": [{"account": i.account_id, "account_name": i.account.description,
                   "description": i.description, "quantity": float(i.quantity or 0),
                   "uom": i.uom_id, "rate": float(i.rate or 0),
                   "amount": float(i.amount or 0)}
                  for i in expense.items.select_related("account").all()],
        "attachments": [{"id": a.pk, "name": a.file_name, "url": a.file.url,
                         "type": a.file_type}
                        for a in expense.attachments.all()],
        "voucher": ({"id": expense.journal_id, "no": expense.journal.voucher_no,
                     "status": expense.journal.status} if expense.journal_id else None),
        "audit": {
            "created_by": str(expense.created_by or ""),
            "created_at": expense.created_at.isoformat() if expense.created_at else "",
            "posted_by": str(expense.posted_by or ""),
            "posted_at": expense.posted_at.isoformat() if expense.posted_at else "",
            "cancelled_by": str(expense.cancelled_by or ""),
            "cancelled_at": expense.cancelled_at.isoformat() if expense.cancelled_at else "",
            "cancel_reason": expense.cancel_reason,
        },
    })


@login_required
@require_POST
def petty_expense_attach(request, id):
    """Attach a bill. Several at once; each kept with the expense it proves."""
    expense = _mine(request, id)
    allowed = {"application/pdf", "image/jpeg", "image/png", "image/jpg"}
    saved, refused = [], []
    for upload in request.FILES.getlist("files"):
        if upload.content_type not in allowed:
            refused.append(f"{upload.name}: only PDF, JPG and PNG are accepted.")
            continue
        if upload.size > 5 * 1024 * 1024:
            refused.append(f"{upload.name}: larger than 5 MB.")
            continue
        attachment = PettyExpenseAttachment.objects.create(
            petty_expense=expense, file=upload, file_name=upload.name[:255],
            file_type=upload.content_type, uploaded_by=request.user)
        saved.append({"id": attachment.pk, "name": attachment.file_name,
                      "url": attachment.file.url})
    return JsonResponse({"saved": saved, "refused": refused},
                        status=400 if refused and not saved else 200)


@login_required
@require_POST
def petty_expense_detach(request, id, attachment_id):
    """Remove a bill from a draft. A posted expense keeps its evidence.

    Deliberately stricter than editing the expense itself: the figures can be
    corrected, but the bill that justified the payment is not something to be
    quietly removed from a payment that has been made.
    """
    expense = _mine(request, id)
    if expense.status != PettyExpense.STATUS_DRAFT:
        return JsonResponse(
            {"error": "A posted expense keeps its attachments."}, status=400)
    get_object_or_404(PettyExpenseAttachment, pk=attachment_id,
                      petty_expense=expense).delete()
    return JsonResponse({"removed": attachment_id})


def _filtered(request, qs):
    """Apply the filters the report and the register share."""
    get = request.GET
    date_from = parse_date(get.get("from") or "")
    date_to = parse_date(get.get("to") or "")
    if date_from:
        qs = qs.filter(expense_date__gte=date_from)
    if date_to:
        qs = qs.filter(expense_date__lte=date_to)
    for field, param in (("branch_id", "branch"), ("farm_id", "farm"),
                         ("cost_centre_id", "centre"), ("paid_from_id", "paid_from"),
                         ("payment_mode_id", "mode")):
        if get.get(param):
            qs = qs.filter(**{field: get[param]})
    if get.get("account"):
        qs = qs.filter(items__account_id=get["account"]).distinct()
    return qs


@never_cache
@login_required
def petty_expense_report(request):
    """Where the petty money went: one question, grouped six ways."""
    return render(request, "petty_expense_report.html", {
        "masters": _masters(request.user),
        "groups": service.SUMMARY_GROUPS,
    })


@login_required
def petty_expense_report_rows(request):
    """The figures, the trend, the register and the summaries, of one set."""
    expenses = _filtered(request, _visible(request))
    if request.GET.get("status"):
        expenses = expenses.filter(status=request.GET["status"])
    if request.GET.get("paid_to"):
        expenses = expenses.filter(paid_to_name__icontains=request.GET["paid_to"])
    if request.GET.get("shed"):
        expenses = expenses.filter(shed_id=request.GET["shed"])
    return JsonResponse(service.report(
        expenses, group_by=request.GET.get("group_by") or "category"))


@never_cache
@login_required
def petty_cash_statement(request):
    """The page: a cash box, a period, and what moved."""
    return render(request, "petty_cash_statement.html", {
        "boxes": [{"id": row["id"], "label": row["label"]}
                  for row in service.paid_from_accounts()],
    })


@login_required
def petty_cash_statement_rows(request):
    """Opening, every movement, and the running balance.

    Read from the posted journal lines of the box's own ledger, so this agrees
    with the ledger report and with the figure on the register by construction
    rather than by reconciliation.
    """
    box = get_object_or_404(BankCashMaster, pk=_int(request.GET.get("box")))
    date_from = parse_date(request.GET.get("from") or "")
    date_to = parse_date(request.GET.get("to") or "")
    movement = service.statement(box, date_from=date_from, date_to=date_to,
                                 by_day=request.GET.get("group") == "day")
    return JsonResponse(movement)


@login_required
def petty_cash_balance(request, id):
    """What is left in an account, and how a petty-cash one got there."""
    master = get_object_or_404(BankCashMaster, pk=id)
    movement = service.petty_cash_movement(
        master,
        date_from=parse_date(request.GET.get("from") or ""),
        date_to=parse_date(request.GET.get("to") or ""))
    balance = service.balance_of(master)
    return JsonResponse({
        "id": master.pk, "label": str(master), "is_cash": bool(master.is_cash),
        "balance": float(balance) if balance is not None else None,
        "movement": ({k: float(v) for k, v in movement.items()} if movement else None),
    })
