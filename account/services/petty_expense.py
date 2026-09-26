"""Petty expense: what it posts, what it costs an account, and how it reads.

The screen is operational; the books are the ERP's own. Everything here ends
up calling ``account.services.journal``, so a petty expense is a voucher like
any other and shows up in the ledger, the trial balance, the cost-centre
report and the branch summary without any of them knowing this module exists.

Nothing in this file keeps a second petty-cash balance. A petty-cash account's
balance is the balance of its Chart-of-Account ledger, read back through
``journal.account_balance``.
"""
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone

from account.models import (BankCashMaster, ChartOfAccount, CompanyProfile,
                            PettyExpense, Voucher)
from account.services import journal
from account.services.bank_cash import ledger_for_bank_cash

ZERO = Decimal("0")


class PettyExpenseError(Exception):
    """Something that must stop a post, said in words a user can act on."""


def company():
    profile = CompanyProfile.objects.filter(pk=1).first()
    if profile is None:
        raise PettyExpenseError("No company profile; the chart of accounts has no owner.")
    return profile


# --------------------------------------------------------------------------
# What the form offers
# --------------------------------------------------------------------------

def expense_categories(profile=None):
    """The expense side of the chart of accounts, as category -> ledgers.

    This ERP has no separate expense-classification master, and it does not
    need one: the Expense branch of the chart of accounts is already the two
    levels a classification wants -- groups to choose a category from, and the
    postable ledgers under them. Using it means the account a line posts to is
    the classification itself, so a line can never be classified and unmapped
    at the same time, which is the failure the spec's "mapping missing"
    warning exists to catch.
    """
    profile = profile or company()
    accounts = list(
        ChartOfAccount.objects
        .filter(company=profile, account_type__name="Expense", status="Active")
        .order_by("code")
        .values("id", "code", "description", "parent_id", "is_group", "is_postable")
    )
    by_id = {a["id"]: a for a in accounts}
    groups = {}
    for account in accounts:
        if account["is_group"] or not account["is_postable"]:
            continue
        parent = by_id.get(account["parent_id"])
        if parent is None:                      # a ledger hung straight off the root
            parent = {"id": 0, "description": "Other Expenses"}
        groups.setdefault(parent["id"], {"id": parent["id"],
                                         "name": parent["description"],
                                         "items": []})
        groups[parent["id"]]["items"].append({
            "id": account["id"], "code": account["code"],
            "name": account["description"],
        })
    return sorted(groups.values(), key=lambda g: g["name"])


def paid_from_accounts(cash_only=True):
    """The accounts a petty expense can be paid from, with each one's balance.

    Cash only by default, because that is what "petty" means here: money out
    of a cash box. Anything paid by bank belongs in a payment voucher, where
    it will carry the bank's own reference. The balance comes from the ledger,
    not from a column kept here: one place holds what an account is worth, and
    it is the place the reports read.
    """
    masters = BankCashMaster.objects.all().order_by("-is_cash", "code")
    if cash_only:
        masters = masters.filter(is_cash=True)
    rows = []
    for master in masters:
        ledger = ledger_for_bank_cash(master)
        rows.append({
            "id": master.pk,
            "label": str(master),
            "is_cash": _is_cash(master),
            "account_id": ledger.pk if ledger else None,
            "balance": float(journal.account_balance(ledger)) if ledger else None,
        })
    return rows


def cash_payment_modes():
    """The payment modes that mean cash, as the Payment Mode master defines it.

    Categorised there as Cash -- not matched on the name, so renaming a mode
    or adding a second cash mode needs no change here.
    """
    from account.models import PaymentMode
    return list(PaymentMode.objects.filter(is_active=True, category="Cash")
                .order_by("display_order", "name").values("id", "name"))


def policy():
    from account.models import PettyCashPolicy
    return PettyCashPolicy.get_solo()


def cash_health(master=None):
    """Each cash box, its balance, and whether that balance is worryingly low.

    "Low" is the policy's figure, not a guess: a box with a 10,000 float and a
    2,000 warning line is a different thing from one with a 500 float.
    """
    rule = policy()
    rows = []
    masters = ([master] if master is not None
               else BankCashMaster.objects.filter(is_cash=True).order_by("code"))
    for box in masters:
        balance = balance_of(box)
        rows.append({
            "id": box.pk,
            "label": str(box),
            "balance": float(balance) if balance is not None else None,
            "low": balance is not None and balance <= (rule.low_balance_at or ZERO),
            "float_amount": float(rule.float_amount or 0),
            "top_up": float(max((rule.float_amount or ZERO) - (balance or ZERO), ZERO)),
        })
    return rows


@transaction.atomic
def replenish(box, amount, from_account, date=None, user=None, reference="",
              remark=""):
    """Put money into a cash box from a bank account.

    A contra, because nothing is earned or spent by moving your own money
    between your own accounts -- and posted through the same engine as
    everything else, so the box's balance stays the balance of its ledger.
    """
    amount = Decimal(str(amount or 0))
    if amount <= ZERO:
        raise PettyExpenseError("Say how much is going into the box.")
    if not _is_cash(box):
        raise PettyExpenseError(f"{box} is not a cash box.")
    if _is_cash(from_account):
        raise PettyExpenseError("Cash is drawn from a bank account, not from "
                                "another cash box.")

    to_ledger = ledger_for_bank_cash(box)
    from_ledger = ledger_for_bank_cash(from_account)
    if to_ledger is None or from_ledger is None:
        raise PettyExpenseError("One of those accounts has no ledger in the "
                                "chart of accounts, so nothing can be posted.")

    date = date or timezone.localdate()
    # What the engine would say, and what the person added to it. Both are
    # kept, so the voucher screen can tell which half is whose.
    written = f"Cash drawn from {from_account} into {box}."
    remark = " ".join(str(remark or "").split())
    narration = f"{written} {remark}".strip() if remark else written
    try:
        return journal.create_voucher(
            company(), date,
            [{"account": to_ledger.pk, "debit": amount, "credit": 0,
              "narration": narration},
             {"account": from_ledger.pk, "debit": 0, "credit": amount,
              "narration": narration}],
            user=user, voucher_type="Contra", manual=False,
            system_generated=True, reference=reference or "",
            narration=narration, auto_narration=written,
            narration_source="MANUAL" if remark else "AUTO", post=True)
    except DjangoValidationError as exc:
        raise PettyExpenseError("  ".join(exc.messages)) from exc


def bank_accounts():
    """The accounts a cash box can be replenished from."""
    rows = []
    for master in BankCashMaster.objects.filter(is_cash=False).order_by("code"):
        ledger = ledger_for_bank_cash(master)
        rows.append({"id": master.pk, "label": str(master),
                     "balance": (float(journal.account_balance(ledger))
                                 if ledger else None)})
    return rows


def duplicate_of(expense):
    """An expense already on file with the same payee, date and amount.

    Not a rule -- a warning. Two identical payments on one day happen; two
    identical *entries* of one payment happen more often.
    """
    from account.models import PettyExpense as PE

    if not policy().warn_on_duplicates:
        return None
    if not (expense.paid_to_name or "").strip():
        return None
    twin = (PE.objects.filter(company=expense.company,
                              expense_date=expense.expense_date,
                              paid_to_name__iexact=expense.paid_to_name.strip(),
                              net_amount=expense.net_amount)
            .exclude(pk=expense.pk)
            .exclude(status=PE.STATUS_CANCELLED)
            .first())
    return twin


def _is_cash(master):
    """The master says so itself -- no guessing from a name."""
    return bool(getattr(master, "is_cash", False))


def balance_of(master):
    """What is left in a petty-cash or bank account, or None if it has no ledger."""
    ledger = ledger_for_bank_cash(master)
    if ledger is None:
        return None
    return journal.account_balance(ledger)


def petty_cash_movement(master, date_from=None, date_to=None):
    """Opening, received, spent and current for a petty-cash account.

    Assembled from the account's own posted journal lines, so it agrees with
    the ledger report by construction rather than by reconciliation.
    """
    ledger = ledger_for_bank_cash(master)
    if ledger is None:
        return None
    ledger_report = journal.account_ledger(ledger, date_from=date_from,
                                           date_to=date_to)
    rows = ledger_report["rows"]
    received = sum((Decimal(str(r["debit"] or 0)) for r in rows), ZERO)
    spent = sum((Decimal(str(r["credit"] or 0)) for r in rows), ZERO)
    return {
        "opening": Decimal(str(ledger_report["opening"] or 0)),
        "received": received,
        "spent": spent,
        "current": Decimal(str(ledger_report["closing"] or 0)),
    }


def statement(box, date_from=None, date_to=None, by_day=False):
    """A cash box's statement: opening, each movement, and the running balance.

    Built from the ledger's posted lines rather than from this module's own
    rows, so money that reached the box another way -- an opening balance, a
    correction in the journal -- is in the statement rather than missing from
    it.
    """
    ledger = ledger_for_bank_cash(box)
    if ledger is None:
        return {"opening": 0, "received": 0, "spent": 0, "closing": 0, "rows": []}

    # The ledger helper has already worked out the opening balance and the
    # running one; recomputing them here would be a second answer to the same
    # question, and the two would drift.
    report = journal.account_ledger(ledger, date_from=date_from, date_to=date_to)
    opening = Decimal(str(report["opening"] or 0))
    balance = Decimal(str(report["closing"] or 0))

    rows, received, spent = [], ZERO, ZERO
    for line in report["rows"]:
        debit = Decimal(str(line["debit"] or 0))
        credit = Decimal(str(line["credit"] or 0))
        received += debit
        spent += credit
        rows.append({
            "kind": "entry",
            "date": str(line["date"] or ""),
            "voucher_no": line.get("voucher_no") or "",
            "particulars": line.get("narration") or line.get("voucher_type") or "",
            "debit": float(debit), "credit": float(credit),
            "balance": float(line["balance"] or 0),
        })

    if by_day:
        rows = _by_day(rows, opening)

    return {"opening": float(opening), "received": float(received),
            "spent": float(spent), "closing": float(balance), "rows": rows}


def _by_day(rows, opening):
    """One line per day, for someone who wants the shape rather than the detail."""
    days, order = {}, []
    for row in rows:
        day = row["date"]
        if day not in days:
            days[day] = {"kind": "day", "date": day, "voucher_no": "",
                         "particulars": "", "debit": 0.0, "credit": 0.0,
                         "balance": 0.0, "count": 0}
            order.append(day)
        days[day]["debit"] += row["debit"]
        days[day]["credit"] += row["credit"]
        days[day]["balance"] = row["balance"]
        days[day]["count"] += 1
    for day in order:
        entry = days[day]
        entry["particulars"] = (f"{entry['count']} entries" if entry["count"] > 1
                                else "1 entry")
    return [days[day] for day in order]


# --------------------------------------------------------------------------
# Where it went
# --------------------------------------------------------------------------

#: What a summary can be grouped by, and how each row is labelled.
SUMMARY_GROUPS = {
    "category": "Category",
    "sub_category": "Sub Category",
    "branch": "Branch",
    "farm": "Farm",
    "payee": "Paid To",
    "mode": "Payment Mode",
    "paid_from": "Paid From",
    "month": "Month",
}


def summary(expenses, group_by="category"):
    """Totals for ``expenses``, grouped one way, biggest first.

    ``expenses`` is a queryset the caller has already filtered and scoped --
    this decides nothing about who may see what.
    """
    from account.models import PettyExpenseItem

    if group_by not in SUMMARY_GROUPS:
        group_by = "category"

    posted = expenses.filter(status=PettyExpense.STATUS_POSTED)
    lines = (PettyExpenseItem.objects
             .filter(petty_expense__in=posted)
             .select_related("account", "account__parent",
                             "petty_expense__branch", "petty_expense__farm",
                             "petty_expense__payment_mode",
                             "petty_expense__paid_from"))

    groups = {}
    for line in lines:
        expense = line.petty_expense
        if group_by == "category":
            key = (line.account.parent.description if line.account.parent_id
                   else line.account.description)
        elif group_by == "sub_category":
            key = line.account.description
        elif group_by == "branch":
            key = expense.branch.branch_name
        elif group_by == "farm":
            key = expense.farm.farm_name if expense.farm_id else "Branch office"
        elif group_by == "payee":
            key = expense.paid_to_name or "\u2014"
        elif group_by == "mode":
            key = expense.payment_mode.name if expense.payment_mode_id else "\u2014"
        elif group_by == "paid_from":
            key = str(expense.paid_from) if expense.paid_from_id else "\u2014"
        else:
            key = expense.expense_date.strftime("%Y-%m")

        row = groups.setdefault(key, {"label": key, "amount": ZERO,
                                      "lines": 0, "expenses": set()})
        row["amount"] += line.amount or ZERO
        row["lines"] += 1
        row["expenses"].add(expense.pk)

    # Other charges and discounts sit on the header, not on a line, so they
    # would vanish from a total built only from lines. They are spread across
    # the expense's own lines in proportion, which is where they were spent.
    header_extra = sum(((e.other_charges or ZERO) - (e.adjustment or ZERO)
                        for e in posted), ZERO)
    line_total = sum((row["amount"] for row in groups.values()), ZERO)
    if header_extra and line_total:
        for row in groups.values():
            row["amount"] += header_extra * (row["amount"] / line_total)

    total = sum((row["amount"] for row in groups.values()), ZERO)
    rows = []
    for row in groups.values():
        rows.append({
            "label": row["label"],
            "amount": float(row["amount"].quantize(Decimal("0.01"))),
            "expenses": len(row["expenses"]),
            "lines": row["lines"],
            "share": float((row["amount"] / total * 100).quantize(Decimal("0.1")))
                     if total else 0.0,
        })

    # Months read in order; everything else biggest first, which is the order
    # the question "where did it go" is asked in.
    rows.sort(key=(lambda r: r["label"]) if group_by == "month"
              else (lambda r: -r["amount"]))
    return {
        "group_by": group_by,
        "group_label": SUMMARY_GROUPS[group_by],
        "rows": rows,
        "total": float(total.quantize(Decimal("0.01"))),
        "expenses": posted.count(),
    }


def trend(expenses, days=15, date_to=None):
    """What was posted on each of the last ``days`` days, zeros included.

    The gaps matter: a line that skips the days nothing was spent implies a
    slow trickle where there were two busy days and a fortnight of nothing.
    """
    import datetime

    end = date_to or timezone.localdate()
    start = end - datetime.timedelta(days=days - 1)
    posted = (expenses.filter(status=PettyExpense.STATUS_POSTED,
                              expense_date__gte=start, expense_date__lte=end)
              .values_list("expense_date", "net_amount"))

    totals = {}
    for day, amount in posted:
        totals[day] = totals.get(day, ZERO) + (amount or ZERO)

    return [{"date": (start + datetime.timedelta(days=offset)).isoformat(),
             "amount": float(totals.get(start + datetime.timedelta(days=offset), ZERO))}
            for offset in range(days)]


def report(expenses, group_by="category", limit=500):
    """The whole page: the figures, the trend, the register and the summaries."""
    posted = expenses.filter(status=PettyExpense.STATUS_POSTED)
    today = timezone.localdate()

    spent = sum((e.net_amount or ZERO for e in posted), ZERO)
    today_rows = [e for e in posted if e.expense_date == today]

    rows = []
    for expense in (expenses.select_related(
            "branch", "farm", "shed", "paid_from", "payment_mode", "journal")
            .prefetch_related("items__account")[:limit]):
        items = list(expense.items.all())
        rows.append({
            "id": expense.pk,
            "expense_no": expense.expense_no,
            "date": expense.expense_date.isoformat(),
            "branch": expense.branch.branch_name if expense.branch_id else "",
            "farm": (expense.farm.farm_name if expense.farm_id else ""),
            "shed": ((expense.shed.shed_name or expense.shed.shed_code)
                     if expense.shed_id else ""),
            "category": ", ".join(sorted({(i.account.parent.description
                                           if i.account.parent_id
                                           else i.account.description) for i in items})),
            "sub_category": ", ".join(sorted({i.account.description for i in items})),
            "description": "; ".join(i.description for i in items if i.description),
            "paid_to": expense.paid_to_name,
            "mode": expense.payment_mode.name if expense.payment_mode_id else "",
            "paid_from": str(expense.paid_from) if expense.paid_from_id else "",
            "amount": float(expense.net_amount or 0),
            "status": expense.status,
            "voucher_no": expense.journal.voucher_no if expense.journal_id else "",
            "attachments": expense.attachments.count(),
        })

    return {
        "kpi": {
            "total": float(spent),
            "count": posted.count(),
            "today": float(sum((e.net_amount or ZERO for e in today_rows), ZERO)),
            "today_count": len(today_rows),
            "branches": len({e.branch_id for e in posted if e.branch_id}),
            "farms": len({e.farm_id for e in posted if e.farm_id}),
            "farm_total": float(sum((e.net_amount or ZERO for e in posted
                                     if e.farm_id), ZERO)),
            "boxes": cash_health(),
        },
        "trend": trend(expenses),
        "main": summary(expenses, group_by=group_by),
        "by_category": summary(expenses, group_by="category"),
        "by_branch": summary(expenses, group_by="branch"),
        "by_mode": summary(expenses, group_by="mode"),
        "by_paid_from": summary(expenses, group_by="paid_from"),
        "rows": rows,
    }


# --------------------------------------------------------------------------
# Narration
# --------------------------------------------------------------------------

def narration_is_auto(expense):
    """Whether the narration on this expense is still the one we wrote.

    Compared rather than flagged: no column to keep in step, and an expense
    edited back to the engine's own words is honestly automatic again.
    """
    return (expense.narration or "").strip() == compose_narration(expense).strip()


def compose_narration(expense):
    """A sentence from the transaction, for the user to accept or rewrite.

    Written from what the expense is, in the order someone would say it: what
    was bought, where, and what it was paid out of.
    """
    items = list(expense.items.all())
    what = items[0].description if len(items) == 1 else f"{len(items)} items"
    where = expense.farm.farm_name if expense.farm_id else expense.branch.branch_name
    if expense.shed_id:
        where = f"{where}, {expense.shed.shed_name or expense.shed.shed_code}"
    payee = f" to {expense.paid_to_name}" if expense.paid_to_name else ""
    return (f"Petty expense for {what} at {where}{payee}, "
            f"paid through {expense.paid_from}.")


# --------------------------------------------------------------------------
# Posting
# --------------------------------------------------------------------------

def _link(voucher, expense):
    voucher.source_content_type = ContentType.objects.get_for_model(PettyExpense)
    voucher.source_object_id = expense.pk
    voucher.save(update_fields=["source_content_type", "source_object_id"])
    return voucher


def validate(expense, items=None):
    """Everything that must be true before this can go on the books.

    Returned as a list rather than raised one at a time, so a form can show
    every problem at once instead of making the user find them in turn.
    """
    problems = []
    items = items if items is not None else list(expense.items.all())

    if not expense.expense_date:
        problems.append("Choose the expense date.")
    if not expense.branch_id:
        problems.append("Choose the branch.")
    if not expense.paid_from_id:
        problems.append("Choose the account the money came from.")
    if not expense.payment_mode_id:
        problems.append("Choose the payment mode.")
    if not (expense.paid_to_name or "").strip():
        problems.append("Say who was paid.")
    if not items:
        problems.append("Add at least one expense line.")

    for index, item in enumerate(items, start=1):
        if not item.account_id:
            problems.append(f"Line {index}: choose the expense category and sub category.")
        elif item.account.is_group or not item.account.is_postable:
            problems.append(f"Line {index}: {item.account.description} is a group, "
                            f"not an expense ledger — choose a sub category under it.")
        if (item.amount or ZERO) <= ZERO:
            problems.append(f"Line {index}: amount must be more than zero.")

    if expense.shed_id and not expense.farm_id:
        problems.append("A shed belongs to a farm — choose the farm as well.")
    # Compared as text on both sides: a caller that assigned a picker's
    # string to a ``*_id`` would otherwise be told its own farm belongs to
    # another branch, because 2 != "2".
    if (expense.shed_id and expense.farm_id
            and str(expense.shed.farm_id) != str(expense.farm_id)):
        problems.append("That shed is not on the chosen farm.")
    if expense.farm_id and str(expense.farm.branch_id) != str(expense.branch_id):
        problems.append("That farm is not on the chosen branch.")

    net = expense.net_amount or ZERO
    if net <= ZERO:
        problems.append("The net amount must be more than zero.")

    # No bill, no posting, above the figure the policy names.
    rule = policy()
    threshold = rule.bill_required_above or ZERO
    if threshold > ZERO and net > threshold and expense.pk:
        if not expense.attachments.exists():
            problems.append(f"Attach the bill: anything above "
                            f"{threshold:,.2f} needs one.")

    # A date outside every financial year is the commonest reason a post is
    # refused, and the engine's own message arrives too late to be useful on
    # the form -- so it is asked here, with the rest.
    if expense.expense_date:
        from account.models import FinancialYear
        covered = FinancialYear.objects.filter(
            start_date__lte=expense.expense_date,
            end_date__gte=expense.expense_date).first()
        if covered is None:
            problems.append(f"No financial year covers {expense.expense_date}. "
                            f"Open it under Account > Financial Year first.")
        elif covered.state != "Open":
            problems.append(f"The financial year covering {expense.expense_date} "
                            f"is {covered.state.lower()}, so nothing can be posted into it.")

    if expense.paid_from_id and not _is_cash(expense.paid_from):
        problems.append(f"{expense.paid_from} is a bank account. A petty expense "
                        f"is paid out of a cash box; anything paid by bank belongs "
                        f"in a payment voucher.")
    if (expense.payment_mode_id
            and getattr(expense.payment_mode, "category", "Cash") != "Cash"):
        problems.append(f"{expense.payment_mode.name} is not a cash payment mode. "
                        f"A petty expense leaves the cash box.")

    if expense.paid_from_id:
        ledger = ledger_for_bank_cash(expense.paid_from)
        if ledger is None:
            problems.append(f"{expense.paid_from} has no ledger in the chart of accounts, "
                            f"so nothing can be posted against it.")
        elif _is_cash(expense.paid_from):
            # Cash cannot go below zero: there is no overdraft in a cash box.
            available = journal.account_balance(ledger)
            if net > available:
                problems.append(f"Not enough petty cash: {expense.paid_from} holds "
                                f"{available:,.2f} and this expense is {net:,.2f}.")
    return problems


@transaction.atomic
def post(expense, user=None):
    """Put the expense on the books, through the ERP's own journal engine.

    One debit per line, to the ledger the line is classified as, and one
    credit to the account the money left. The cost centre rides on every line,
    which is what makes the cost-centre report see petty spend.
    """
    if expense.status == PettyExpense.STATUS_POSTED:
        raise PettyExpenseError(f"{expense.expense_no} is already posted.")
    if expense.status == PettyExpense.STATUS_CANCELLED:
        raise PettyExpenseError(f"{expense.expense_no} has been cancelled and cannot be posted.")

    expense.recalculate()
    problems = validate(expense)
    if problems:
        raise PettyExpenseError(problems[0] if len(problems) == 1 else
                                "  ".join(problems))

    profile = expense.company or company()
    credit_ledger = ledger_for_bank_cash(expense.paid_from)
    centre = expense.cost_centre_id or None

    rows = []
    for item in expense.items.all():
        rows.append({"account": item.account_id, "cost_center": centre,
                     "debit": item.amount, "credit": 0,
                     "narration": item.description[:255]})

    # Other charges ride on the first line's account: they are part of what
    # that spend cost, and inventing a "sundries" account to hold them would
    # be this module writing its own chart of accounts.
    extra = (expense.other_charges or ZERO) - (expense.adjustment or ZERO)
    if extra and rows:
        rows[0]["debit"] = Decimal(str(rows[0]["debit"])) + extra

    # The cash line says who the money went to. It used to carry the bill
    # number, which is already on the voucher and tells a cash-book reader
    # nothing about what left the box.
    rows.append({"account": credit_ledger.pk, "cost_center": centre,
                 "debit": 0, "credit": expense.net_amount,
                 "narration": (expense.paid_to_name or expense.expense_no)[:255]})

    # The narration the engine would write, and whether this one is still it.
    # The journal keeps both so the voucher screen can say which narrations
    # were written for the company and which a person replaced.
    written = compose_narration(expense)
    narration = expense.narration or written

    # NarrationSettings can switch narration off, or drop the amount, party or
    # reference from it, for the whole company. A module that writes its own
    # sentence has to honour that or it becomes the exception nobody knows about.
    from account.models import NarrationSettings
    settings = NarrationSettings.get_solo()
    if settings is not None and not settings.enabled:
        narration = expense.narration or ""
        written = ""

    # Whatever the engine refuses is the user's problem to fix, not a crash:
    # its own wording is passed straight through to the screen.
    try:
        voucher = journal.create_voucher(
            profile, expense.expense_date, rows,
            user=user, voucher_type="Payment", manual=False, system_generated=True,
            reference=expense.reference or expense.expense_no,
            narration=narration,
            auto_narration=written,
            narration_source=("AUTO" if narration.strip() == written.strip()
                              else "MANUAL"),
            post=True,
        )
    except DjangoValidationError as exc:
        raise PettyExpenseError("  ".join(exc.messages)) from exc
    _link(voucher, expense)

    expense.journal = voucher
    expense.status = PettyExpense.STATUS_POSTED
    expense.posted_by = user
    expense.posted_at = timezone.now()
    expense.save(update_fields=["journal", "status", "posted_by", "posted_at",
                                "subtotal", "net_amount", "updated_at"])
    return voucher


@transaction.atomic
def repost(expense, user=None):
    """Put a corrected expense back on the books in place of its old voucher.

    The old voucher is deleted rather than cancelled, so the journal shows one
    entry for one expense instead of a pair that cancel each other out. What
    it costs is that voucher's number; what it buys is a ledger that always
    agrees with the register.
    """
    old = expense.journal
    expense.journal = None
    expense.status = PettyExpense.STATUS_DRAFT
    expense.save(update_fields=["journal", "status", "updated_at"])
    if old is not None:
        old.delete()
    return post(expense, user=user)


@transaction.atomic
def cancel(expense, user=None, reason=""):
    """Take it off the books without taking it off the record.

    The voucher is cancelled through the journal engine, which keeps its lines
    for the audit trail; the expense stays, marked cancelled, with who did it
    and why.
    """
    if expense.status == PettyExpense.STATUS_CANCELLED:
        raise PettyExpenseError(f"{expense.expense_no} is already cancelled.")

    if expense.journal_id and expense.journal.status == "Posted":
        journal.cancel_voucher(expense.journal, user=user,
                               reason=reason or "Petty expense cancelled")

    expense.status = PettyExpense.STATUS_CANCELLED
    expense.cancelled_by = user
    expense.cancelled_at = timezone.now()
    expense.cancel_reason = (reason or "")[:255]
    expense.save(update_fields=["status", "cancelled_by", "cancelled_at",
                                "cancel_reason", "updated_at"])
    return expense


def vouchers_for(expense):
    """Every voucher this expense has raised, cancelled ones included."""
    return Voucher.objects.filter(
        source_content_type=ContentType.objects.get_for_model(PettyExpense),
        source_object_id=expense.pk,
    )
