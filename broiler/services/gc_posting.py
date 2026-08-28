"""Posting growing charges and farmer payments to the ledger.

Phase two: the service that writes the vouchers, with nothing calling it yet.
Settlement save, payment save and their delete paths are wired in phase three,
and together — posting only the payment would make Cash fall against nothing
and put the Trial Balance out in a way nobody could trace.

The entries
-----------
A settled growing charge raises the cost and what is owed for it::

    Dr  Growing Charges                     gross
        Cr  Farmer Payable / <farmer>       gross

A payment discharges it and takes the money out of the account it left::

    Dr  Farmer Payable / <farmer>           amount
    Dr  Bank Charges                        charges
        Cr  <the line's Code account>       amount + charges

Bank charges are our cost, not the farmer's, so they never touch Farmer
Payable. That is the same rule the Farmer Ledger report already follows, and
the two have to agree or the reconciliation in phase four is meaningless.

TDS is deliberately absent. ``Farmer.tds_percent`` is captured and unused, the
deduction falls at credit rather than at payment under Indian practice, and
guessing at a compliance rule is worse than leaving a decision visible. When it
is decided, it is one more credit line on the settlement entry — the shape here
does not have to change.

Rather than editing a posted voucher, an amendment cancels it and posts a new
one. A posted figure that silently changes is exactly what an audit trail
exists to prevent.
"""
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction

from account.models import ChartOfAccount, CompanyProfile, Voucher
from account.services import journal


class PostingError(ValidationError):
    """Raised when a document cannot be posted.

    A subclass so callers can tell a posting problem from any other validation
    failure, and refuse the save rather than leaving a document without its
    voucher.
    """


def _company():
    company = CompanyProfile.objects.filter(pk=1).first()
    if company is None:
        raise PostingError("No company profile; the chart of accounts has no owner.")
    return company


def _by_role(company, role, label):
    account = ChartOfAccount.objects.filter(company=company, system_role=role).first()
    if account is None:
        raise PostingError(
            f"{label} is missing from the chart of accounts. "
            f"Run `manage.py backfill_farmer_accounts` and try again.")
    return account


def farmer_ledger(farmer, company=None):
    """The named farmer's own ledger under Farmer Payable.

    Created by ``account.signals.farmer_ledger`` when the farmer is saved, so a
    missing one means either the chart predates that signal or the farmer has
    not been saved since. The backfill command fixes both.
    """
    company = company or _company()
    payable = _by_role(company, "FARMER_PAYABLE", "Farmer Payable")
    ct = ContentType.objects.get_for_model(type(farmer))
    ledger = ChartOfAccount.objects.filter(
        company=company, parent=payable,
        source_content_type=ct, source_object_id=farmer.pk).first()
    if ledger is None:
        raise PostingError(
            f"{farmer.farmer_name} has no ledger under Farmer Payable. "
            f"Run `manage.py backfill_farmer_accounts` and try again.")
    return ledger


def vouchers_for(document):
    """Every voucher this document has produced, cancelled ones included."""
    ct = ContentType.objects.get_for_model(type(document))
    return Voucher.objects.filter(source_content_type=ct, source_object_id=document.pk)


def _link(voucher, document):
    voucher.source_content_type = ContentType.objects.get_for_model(type(document))
    voucher.source_object_id = document.pk
    voucher.save(update_fields=["source_content_type", "source_object_id"])
    return voucher


def reverse(document, user=None, reason="Source document changed"):
    """Cancel whatever this document has posted. Safe when it has posted nothing.

    Returns the number of vouchers cancelled. A voucher in a locked year cannot
    be cancelled, and that raises rather than being skipped: silently leaving a
    stale posting behind is the failure this whole exercise is meant to remove.
    """
    cancelled = 0
    for voucher in vouchers_for(document).filter(status="Posted"):
        journal.cancel_voucher(voucher, user=user, reason=reason)
        cancelled += 1
    return cancelled


@transaction.atomic
def post_settlement(settlement, user=None):
    """Raise the growing charge and what is owed to the farmer for it."""
    gross = Decimal(str(settlement.farmer_payable or 0))
    if gross <= 0:
        # Nothing owed is not an error - a settlement can come out at zero -
        # but there is no entry to make, and a one-sided voucher is not one.
        return None

    company = _company()
    reverse(settlement, user=user, reason="Settlement re-posted")

    expense = _by_role(company, "GROWING_CHARGES", "Growing Charges")
    ledger = farmer_ledger(settlement.farm.farmer, company)

    voucher = journal.create_voucher(
        company, settlement.gc_date,
        [{"account": expense.id, "debit": gross, "credit": 0,
          "narration": f"Growing charge — {settlement.batch.batch_name}"},
         {"account": ledger.id, "debit": 0, "credit": gross,
          "narration": settlement.settlement_code}],
        user=user, voucher_type="Journal", manual=False, system_generated=True,
        reference=settlement.settlement_code,
        narration=(f"Being growing charge of {journal_amount(gross)} due to "
                   f"{settlement.farm.farmer.farmer_name} for batch "
                   f"{settlement.batch.batch_name}."),
        post=True,
    )
    return _link(voucher, settlement)


@transaction.atomic
def post_payment(payment, user=None):
    """Discharge what the farmer is owed, and take the money out of the account."""
    lines = list(payment.lines.select_related("farm__farmer", "pay_account", "batch"))
    if not lines:
        return None

    company = _company()
    reverse(payment, user=user, reason="Payment re-posted")

    rows = []
    for line in lines:
        amount = Decimal(str(line.amount or 0))
        charges = Decimal(str(line.bank_charges or 0))
        if amount <= 0 and charges <= 0:
            continue
        ledger = farmer_ledger(line.farm.farmer, company)
        if amount > 0:
            rows.append({"account": ledger.id, "debit": amount, "credit": 0,
                         "narration": f"{line.pay_type} — {line.farm.farm_name}"})
        if charges > 0:
            bank_charges = _by_role(company, "BANK_CHARGES", "Bank Charges")
            rows.append({"account": bank_charges.id, "debit": charges, "credit": 0,
                         "narration": f"Bank charges — {payment.payment_no}"})
        rows.append({"account": line.pay_account_id, "debit": 0,
                     "credit": amount + charges,
                     "narration": line.reference_no or payment.payment_no})

    if not rows:
        return None

    voucher = journal.create_voucher(
        company, payment.date, rows,
        user=user, voucher_type="Payment", manual=False, system_generated=True,
        reference=payment.payment_no,
        narration=payment.narration or payment.compose_narration(),
        post=True,
    )
    return _link(voucher, payment)


def journal_amount(value):
    """₹ with Indian grouping, borrowed from the narration engine so a posted
    narration reads the same as every other one in the system."""
    from account.services.narration import format_inr
    return format_inr(value)
