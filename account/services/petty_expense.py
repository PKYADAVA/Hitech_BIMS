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


def paid_from_accounts():
    """The Bank/Cash Master accounts, with the balance of each one's ledger.

    The balance comes from the ledger, not from a column kept here: one place
    holds what an account is worth, and it is the place the reports read.
    """
    rows = []
    for master in BankCashMaster.objects.all().order_by("-is_cash", "code"):
        ledger = ledger_for_bank_cash(master)
        rows.append({
            "id": master.pk,
            "label": str(master),
            "is_cash": _is_cash(master),
            "account_id": ledger.pk if ledger else None,
            "balance": float(journal.account_balance(ledger)) if ledger else None,
        })
    return rows


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
    opening = journal.account_balance(ledger, date_to=date_from) if date_from else ZERO
    lines = journal.account_ledger(ledger, date_from=date_from, date_to=date_to)
    received = sum((Decimal(str(l.get("debit") or 0)) for l in lines), ZERO)
    spent = sum((Decimal(str(l.get("credit") or 0)) for l in lines), ZERO)
    return {
        "opening": opening,
        "received": received,
        "spent": spent,
        "current": journal.account_balance(ledger, date_to=date_to),
    }


# --------------------------------------------------------------------------
# Narration
# --------------------------------------------------------------------------

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

    rows.append({"account": credit_ledger.pk, "cost_center": centre,
                 "debit": 0, "credit": expense.net_amount,
                 "narration": expense.reference or expense.expense_no})

    # Whatever the engine refuses is the user's problem to fix, not a crash:
    # its own wording is passed straight through to the screen.
    try:
        voucher = journal.create_voucher(
            profile, expense.expense_date, rows,
            user=user, voucher_type="Payment", manual=False, system_generated=True,
            reference=expense.reference or expense.expense_no,
            narration=expense.narration or compose_narration(expense),
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
