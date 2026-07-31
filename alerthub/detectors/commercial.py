"""Sales and finance detectors — receivables, payables and unposted vouchers.

The party-balance rules call the **balance reports' own row builders**
(``sales.views._customer_balance_row`` / ``purchase.views._supplier_balance_row``)
rather than re-deriving a balance. The dashboard widgets take the same approach
and for the same reason: this codebase has repeatedly grown parallel copies of a
calculation that then drift, and an alert that disagrees with the report it
links to destroys trust in both.

Those builders run several queries per party, so the scan cost grows with the
customer master. That is acceptable for a scheduled scan and would not be for a
request-path check — which is why these rules live in the scanner and not in a
signal.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from alerthub.constants import compare
from alerthub.engine import raise_alert
from alerthub.measures import safe_url
from alerthub.scoping import rule_applies_to

from . import detector


def _customer_rows():
    """Every customer's current balance position, via the report's builder."""
    from sales.models import Customer
    from sales.views import _customer_balance_row

    today = timezone.localdate()
    return [
        (customer, _customer_balance_row(customer, None, None, today))
        for customer in Customer.objects.all()
    ]


def _supplier_rows():
    from purchase.models import Supplier
    from purchase.views import _supplier_balance_row

    today = timezone.localdate()
    return [
        (supplier, _supplier_balance_row(supplier, None, None, today))
        for supplier in Supplier.objects.all()
    ]


# ---------------------------------------------------------------------------
# Sales
# ---------------------------------------------------------------------------

@detector("sales.credit_limit_exceeded")
def credit_limit_exceeded(rule):
    """Customers owing more than their configured credit limit.

    The limit itself is the threshold, so the rule's own threshold is unused —
    a single global number would override every customer's individually agreed
    limit, which is the opposite of what the master is for.
    """
    for customer, row in _customer_rows():
        excess = row.get("limit_exceeded") or Decimal("0")
        if excess <= 0:
            continue
        if not rule_applies_to(rule):
            continue

        raise_alert(
            rule,
            title="Credit Limit Exceeded",
            message=(
                f"{row['name']} owes ₹{row['debit']:,.2f} against a limit of "
                f"₹{row['credit_limit']:,.2f} — ₹{excess:,.2f} over."
            ),
            dedupe_key=f"{rule.pk}:credit_limit:{customer.pk}",
            measured_value=excess,
            threshold_value=row.get("credit_limit"),
            object_label="sales.Customer",
            object_id=customer.pk,
            object_display=row["name"],
            action_url=safe_url("customer_balance"),
            metadata={"outstanding": str(row["debit"]),
                      "credit_limit": str(row["credit_limit"])},
        )


def _aged_receivable(rule, title):
    """Customers carrying a debit balance that has not moved in a long time."""
    for customer, row in _customer_rows():
        if (row.get("debit") or 0) <= 0:
            continue
        gap = Decimal(row.get("gap") or 0)
        if not compare(gap, rule.operator, rule.threshold):
            continue
        if not rule_applies_to(rule):
            continue

        raise_alert(
            rule,
            title=title,
            message=(
                f"{row['name']} owes ₹{row['debit']:,.2f} with no receipt for "
                f"{int(gap)} day(s) (limit {rule.threshold})."
            ),
            dedupe_key=f"{rule.pk}:{title}:{customer.pk}",
            measured_value=gap,
            threshold_value=rule.threshold,
            object_label="sales.Customer",
            object_id=customer.pk,
            object_display=row["name"],
            action_url=safe_url("customer_balance"),
            metadata={"outstanding": str(row["debit"])},
        )


@detector("sales.overdue_customer")
def overdue_customer(rule):
    _aged_receivable(rule, "Overdue Customer")


@detector("finance.receivable_overdue")
def receivable_overdue(rule):
    _aged_receivable(rule, "Receivable Overdue")


@detector("sales.payment_pending")
def payment_pending(rule):
    """Invoices past their due date, for customers who still owe money.

    There is no per-invoice payment allocation in this ERP — receipts settle a
    customer's balance, not a specific bill. So "unpaid" is approximated as
    *the customer has an outstanding balance*, and the alert names the overdue
    invoice as the likely reason. That approximation is stated in the alert's
    metadata so nobody reads it as a settled per-invoice fact.
    """
    from sales.models import SalesInvoice

    today = timezone.localdate()
    owing = {
        customer.pk: row
        for customer, row in _customer_rows()
        if (row.get("debit") or 0) > 0
    }
    if not owing:
        return

    invoices = (
        SalesInvoice.objects.filter(
            is_active=True, due_date__isnull=False, due_date__lt=today,
            customer_id__in=list(owing),
        )
        .select_related("customer", "branch", "organization_centre")
    )

    for invoice in invoices:
        overdue_days = Decimal((today - invoice.due_date).days)
        if not compare(overdue_days, rule.operator, rule.threshold):
            continue

        scope = {"warehouse": invoice.branch,
                 "org_centre": invoice.organization_centre}
        if not rule_applies_to(rule, **scope):
            continue

        row = owing[invoice.customer_id]
        raise_alert(
            rule,
            title="Payment Pending",
            message=(
                f"Invoice {invoice.invoice_no} for {invoice.customer.name} was due "
                f"{invoice.due_date:%d %b %Y} — {int(overdue_days)} day(s) ago. "
                f"Customer balance ₹{row['debit']:,.2f}."
            ),
            dedupe_key=f"{rule.pk}:payment_pending:{invoice.pk}",
            measured_value=overdue_days,
            threshold_value=rule.threshold,
            object_label="sales.SalesInvoice",
            object_id=invoice.pk,
            object_display=invoice.invoice_no,
            voucher_no=invoice.invoice_no,
            action_url=safe_url("sales_invoice_list"),
            metadata={
                "net_amount": str(invoice.net_amount),
                "customer_balance": str(row["debit"]),
                "basis": "Customer-level balance; receipts are not allocated "
                         "per invoice in this ERP.",
            },
            **scope,
        )


# ---------------------------------------------------------------------------
# Finance
# ---------------------------------------------------------------------------

@detector("finance.payment_due")
def payment_due(rule):
    """Suppliers we owe money to."""
    for supplier, row in _supplier_rows():
        outstanding = row.get("credit") or Decimal("0")
        if outstanding <= 0:
            continue
        if not compare(outstanding, rule.operator, rule.threshold):
            continue
        if not rule_applies_to(rule):
            continue

        raise_alert(
            rule,
            title="Payment Due",
            message=(
                f"₹{outstanding:,.2f} payable to {row['name']}"
                + (f", unpaid for {row['gap']} day(s)." if row.get("gap") else ".")
            ),
            dedupe_key=f"{rule.pk}:payable:{supplier.pk}",
            measured_value=outstanding,
            threshold_value=rule.threshold,
            object_label="purchase.Supplier",
            object_id=supplier.pk,
            object_display=row["name"],
            action_url=safe_url("supplier_balance"),
        )


@detector("finance.journal_approval_pending")
def journal_approval_pending(rule):
    """Vouchers left in Draft.

    Draft is this ERP's "awaiting approval": a voucher has no accounting effect
    until it is posted, so one sitting in Draft is a transaction that has
    happened in the business and not in the books.
    """
    from account.models import Voucher

    today = timezone.localdate()
    rows = Voucher.objects.filter(status="Draft").select_related("sector")

    for voucher in rows:
        waiting = Decimal((today - voucher.date).days)
        if waiting < 0:
            continue
        if not compare(waiting, rule.operator, rule.threshold):
            continue

        scope = {"warehouse": voucher.sector}
        if not rule_applies_to(rule, **scope):
            continue

        raise_alert(
            rule,
            title="Journal Approval Pending",
            message=(
                f"{voucher.voucher_type} voucher "
                f"{voucher.voucher_no or f'#{voucher.pk}'} dated "
                f"{voucher.date:%d %b %Y} is still in Draft — "
                f"{int(waiting)} day(s) unposted, ₹{voucher.total_debit:,.2f}."
            ),
            dedupe_key=f"{rule.pk}:draft_voucher:{voucher.pk}",
            measured_value=waiting,
            threshold_value=rule.threshold,
            object_label="account.Voucher",
            object_id=voucher.pk,
            object_display=voucher.voucher_no or f"Draft #{voucher.pk}",
            voucher_no=voucher.voucher_no,
            action_url=safe_url("vouchers"),
            metadata={"amount": str(voucher.total_debit),
                      "voucher_type": voucher.voucher_type},
            **scope,
        )
