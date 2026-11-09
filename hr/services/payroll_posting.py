"""Posting payroll accruals and employee salary payments to the ledger.

The entries
-----------
Generating payroll raises the cost and what is owed for it::

    Dr  Salaries & Wages                    payable
        Cr  Salary Payable / <employee>     payable

Paying discharges it and takes the money out of the account it left::

    Dr  Salary Payable / <employee>         amount
    Dr  Bank Charges                        charges
        Cr  <the line's pay account>        amount + charges

Bank charges are our cost, not the employee's, so they never touch Salary
Payable — the same rule ``broiler.services.gc_posting`` follows for farmer
payments, and the two have to agree or a reconciliation across them means
nothing.

The accrual posts ``payable_salary``, not ``net_salary``. What the employee
earned is the expense; an advance recovered against it is a reduction of the
Employee Advances asset, not a smaller wage bill. Advances are not posted
here — ``Employee.advance`` is a standing figure on the employee record
rather than a dated transaction, so there is nothing to post from. Recovering
one properly needs an advance document of its own, and until that exists the
accrual deliberately stops at the gross figure rather than inventing a date
for a movement nobody recorded.

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

    A subclass so callers can tell a posting problem from any other
    validation failure, and refuse the save rather than leaving a document
    without its voucher.
    """


def _company():
    return CompanyProfile.get_solo()


def _by_role(company, role, label):
    account = ChartOfAccount.objects.filter(company=company, system_role=role).first()
    if account is None:
        raise PostingError(
            f"{label} is missing from the chart of accounts. "
            f"Generate the company's chart of accounts and try again.")
    return account


def salary_payable_ledger(employee, company=None):
    """The named employee's own ledger under Salary Payable.

    Created by ``account.signals`` when the employee is saved, so a missing
    one means either the chart predates that signal or the employee has not
    been saved since.
    """
    company = company or _company()
    payable = _by_role(company, "SALARY_PAYABLE", "Salary Payable")
    ct = ContentType.objects.get_for_model(type(employee))
    ledger = ChartOfAccount.objects.filter(
        company=company, parent=payable,
        source_content_type=ct, source_object_id=employee.pk).first()
    if ledger is None:
        raise PostingError(
            f"{employee.full_name} has no ledger under Salary Payable. "
            f"Re-save the employee to have one created, then try again.")
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

    Returns the number of vouchers cancelled. A voucher in a locked year
    cannot be cancelled, and that raises rather than being skipped: silently
    leaving a stale posting behind is the failure this is meant to remove.
    """
    cancelled = 0
    for voucher in vouchers_for(document).filter(status="Posted"):
        journal.cancel_voucher(voucher, user=user, reason=reason)
        cancelled += 1
    return cancelled


@transaction.atomic
def post_payroll(payroll, user=None):
    """Raise the wage cost and what is owed to the employee for it."""
    payable = Decimal(str(payroll.payable_salary or 0))
    if payable <= 0:
        # A month worth nothing is a real outcome, not an error — but there
        # is no entry to make, and a one-sided voucher is not a voucher.
        return None

    company = _company()
    reverse(payroll, user=user, reason="Payroll re-generated")

    ledger = salary_payable_ledger(payroll.employee, company)
    expense = _by_role(company, "SALARY_EXPENSE", "Salaries & Wages")
    period = f"{payroll.month:02d}/{payroll.year}"
    rows = [
        {"account": expense.id, "debit": payable, "credit": 0,
         "narration": f"Salary {period} — {payroll.employee.full_name}"},
        {"account": ledger.id, "debit": 0, "credit": payable,
         "narration": f"Salary {period} — {payroll.employee.full_name}"},
    ]

    voucher = journal.create_voucher(
        company, _accrual_date(payroll), rows,
        user=user, voucher_type="Journal", manual=False, system_generated=True,
        reference=f"PAYROLL-{payroll.year}{payroll.month:02d}-{payroll.employee_id}",
        narration=f"Salary accrual {period} — {payroll.employee.full_name}",
        post=True,
    )
    return _link(voucher, payroll)


def _accrual_date(payroll):
    """Last day of the payroll month — when the wage bill is incurred."""
    from calendar import monthrange
    from datetime import date as _date
    return _date(payroll.year, payroll.month,
                 monthrange(payroll.year, payroll.month)[1])


@transaction.atomic
def post_payment(payment, user=None):
    """Discharge what the employee is owed, and take the money out."""
    lines = list(payment.lines.select_related("employee", "pay_account"))
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
        if amount > 0:
            ledger = salary_payable_ledger(line.employee, company)
            rows.append({"account": ledger.id, "debit": amount, "credit": 0,
                         "narration": f"Salary paid — {line.employee.full_name}"})
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


# ---------------------------------------------------------------------------
# The gate the documents call through.
#
# Everything above will post whatever it is handed; these decide whether it
# should be handed anything at all. Keeping the switch out here means the
# save paths read the same whether posting is on or off, and that turning it
# on is a settings change rather than a deployment.
# ---------------------------------------------------------------------------
def posting_enabled(on_date=None):
    from hr.models import PayrollPostingSettings
    return PayrollPostingSettings.get_solo().posts_on(on_date)


def post_payroll_if_enabled(payroll, user=None):
    """Post a payroll accrual, or don't, according to the switch.

    A posting failure is allowed to propagate. The save paths are atomic, so
    it takes the payroll down with it — which is the intent: payroll that
    exists without its voucher is the silent divergence this is meant to
    remove.
    """
    if not posting_enabled(_accrual_date(payroll)):
        return None
    return post_payroll(payroll, user=user)


def post_payment_if_enabled(payment, user=None):
    """Post a payment, or don't, according to the switch."""
    if not posting_enabled(payment.date):
        return None
    return post_payment(payment, user=user)
