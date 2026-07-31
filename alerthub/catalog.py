"""The catalogue of every alert this ERP knows how to talk about.

One :class:`RuleSpec` per alert in the specification — all of them, including
the ones nothing can raise yet. That completeness is the point: an operator
opening the Alert Configuration master should see the whole map of what the
system could tell them, not a short list that silently omits the rest.

**Supported vs. planned.** A spec whose ``requires`` is empty has a detector
behind it and will genuinely fire. A spec with ``requires`` set names the data
that does not exist yet — a reorder level on the item master, a vaccination
schedule, a backup monitor. Those rows are configurable and visible but are
marked in the UI and refused by the scanner, because a rule that looks armed and
never fires is worse than one that admits it is waiting on a data source: the
first teaches people to distrust the whole feed.

Adding a detector later is a two-line change — clear ``requires`` and register
the function. Nothing else in the module needs to know.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .constants import Module, Operator, Priority


@dataclass(frozen=True)
class Threshold:
    """The single tunable number on a rule, and how to read it.

    ``unit`` is display-only but load-bearing for comprehension: "1.00" means
    nothing until it says whether it is a percent, a day, a kilogram or a rupee.
    """

    label: str
    unit: str = ""
    default: Decimal = Decimal("0")
    operator: str = Operator.GTE
    help_text: str = ""


@dataclass(frozen=True)
class RuleSpec:
    """One alert type: what it is called, what it watches, how it is scoped."""

    key: str
    label: str
    module: str
    priority: str = Priority.MEDIUM
    threshold: Threshold | None = None
    #: Scope dimensions an alert of this kind carries. Drives both which
    #: notify-targets the config master offers and how visibility is filtered.
    scopes: tuple[str, ...] = ()
    #: Empty when a detector exists. Otherwise, the missing data source — shown
    #: in the UI and checked by the scanner.
    requires: str = ""
    description: str = ""

    @property
    def supported(self) -> bool:
        return not self.requires


def _t(label, unit="", default="0", operator=Operator.GTE, help_text=""):
    return Threshold(label, unit, Decimal(default), operator, help_text)


# Scope shorthands. "branch" and "farm" travel together for anything that
# happens at a farm, because a farm always belongs to a branch and a user
# scoped to the branch must see it.
FARM = ("branch", "farm")
WAREHOUSE = ("warehouse",)
BRANCH = ("branch",)
CENTRE = ("branch", "org_centre")


CATALOG: tuple[RuleSpec, ...] = (
    # ---------------------------------------------------------------- Production
    RuleSpec(
        "production.high_mortality", "High Mortality", Module.PRODUCTION,
        Priority.CRITICAL,
        _t("Daily mortality", "%", "0.50", Operator.GTE,
           "Share of the flock alive that morning that died in one day."),
        FARM,
        description="A single day's mortality on a live batch crosses the limit.",
    ),
    RuleSpec(
        "production.cumulative_mortality", "Cumulative Mortality Exceeds %",
        Module.PRODUCTION, Priority.HIGH,
        _t("Batch-to-date mortality", "%", "5.00", Operator.GTE),
        FARM,
        description="Total mortality since placement, as a share of birds placed.",
    ),
    RuleSpec(
        "production.low_body_weight", "Low Body Weight", Module.PRODUCTION,
        Priority.HIGH,
        _t("Below breed standard", "%", "10.00", Operator.GTE,
           "How far under the breed's standard weight for that age counts as low."),
        FARM,
        description="Average bird weight trails the breed standard for its age.",
    ),
    RuleSpec(
        "production.poor_fcr", "Poor FCR", Module.PRODUCTION, Priority.HIGH,
        _t("FCR", "ratio", "1.80", Operator.GTE),
        FARM,
        description="Settled feed conversion ratio is worse than the limit.",
    ),
    RuleSpec(
        "production.poor_cfcr", "Poor CFCR", Module.PRODUCTION, Priority.HIGH,
        _t("CFCR", "ratio", "1.90", Operator.GTE),
        FARM,
        description="Settled corrected FCR is worse than the limit.",
    ),
    RuleSpec(
        "production.low_eef", "Low EEF", Module.PRODUCTION, Priority.MEDIUM,
        _t("EEF", "index", "300", Operator.LTE),
        FARM,
        description="European Efficiency Factor at settlement falls below target.",
    ),
    RuleSpec(
        "production.placement_pending", "Placement Pending", Module.PRODUCTION,
        Priority.MEDIUM,
        _t("Days since batch created", "days", "3", Operator.GTE),
        FARM,
        description="A batch exists but no chicks have been placed into it.",
    ),
    RuleSpec(
        "production.dispatch_pending", "Dispatch Pending", Module.PRODUCTION,
        Priority.MEDIUM,
        _t("Days past harvest age", "days", "3", Operator.GTE),
        FARM,
        description="A flock is past harvest age with no bird sale recorded.",
    ),
    RuleSpec(
        "production.bird_age", "Bird Age Alert", Module.PRODUCTION, Priority.LOW,
        _t("Flock age", "days", "35", Operator.GTE),
        FARM,
        description="A live flock reaches the configured age.",
    ),
    RuleSpec(
        "production.harvest_due", "Harvest Due", Module.PRODUCTION, Priority.HIGH,
        _t("Flock age", "days", "40", Operator.GTE),
        FARM,
        description="A live flock has reached harvest age and is still open.",
    ),

    # --------------------------------------------------------------------- Feed
    RuleSpec(
        "feed.low_feed_stock", "Low Feed Stock", Module.FEED, Priority.CRITICAL,
        _t("Feed left at farm", "kg", "200", Operator.LTE),
        FARM,
        description="Closing feed stock at a farm has fallen to the limit.",
    ),
    RuleSpec(
        "feed.consumption_above_standard", "Feed Consumption exceeds Standard",
        Module.FEED, Priority.MEDIUM,
        _t("Above breed standard", "%", "15.00", Operator.GTE),
        FARM,
        description="Feed per bird exceeds the breed standard intake for its age.",
    ),
    RuleSpec(
        "feed.transfer_pending", "Feed Transfer Pending", Module.FEED,
        Priority.MEDIUM, _t("Age of request", "days", "2", Operator.GTE),
        WAREHOUSE,
        requires="A feed transfer request/approval state. Stock transfers post "
                 "immediately today, so there is no pending stage to watch.",
    ),
    RuleSpec(
        "feed.production_pending", "Feed Production Pending", Module.FEED,
        Priority.MEDIUM, _t("Age of order", "days", "1", Operator.GTE),
        WAREHOUSE,
        requires="A feed-mill production order model. Feed production is not "
                 "tracked as a document in this ERP yet.",
    ),
    RuleSpec(
        "feed.dispatch_delayed", "Feed Dispatch Delayed", Module.FEED,
        Priority.HIGH, _t("Days late", "days", "1", Operator.GTE),
        WAREHOUSE,
        requires="A promised dispatch date on feed movements to measure lateness "
                 "against.",
    ),
    RuleSpec(
        "feed.purchase_pending", "Feed Purchase Pending", Module.FEED,
        Priority.MEDIUM, _t("Days pending", "days", "3", Operator.GTE),
        WAREHOUSE,
        requires="A purchase order stage. Purchases are entered as completed "
                 "invoices, so nothing sits in a pending state.",
    ),

    # ----------------------------------------------------------------- Hatchery
    RuleSpec(
        "hatchery.egg_setting_due", "Egg Setting Due", Module.HATCHERY,
        Priority.HIGH, _t("Days graded and unset", "days", "2", Operator.GTE),
        BRANCH,
        description="Graded eggs have not been set into a setter.",
    ),
    RuleSpec(
        "hatchery.candling_due", "Candling Due", Module.HATCHERY, Priority.MEDIUM,
        _t("Days after setting", "days", "18", Operator.GTE),
        BRANCH,
        requires="A candling date or stage on the tray setting. Candling counts "
                 "are recorded only in the hatcher output, after the fact.",
    ),
    RuleSpec(
        "hatchery.transfer_due", "Transfer Due", Module.HATCHERY, Priority.MEDIUM,
        _t("Days after setting", "days", "18", Operator.GTE),
        BRANCH,
        description="A tray setting has reached setter-to-hatcher transfer age.",
    ),
    RuleSpec(
        "hatchery.hatching_due", "Hatching Due", Module.HATCHERY, Priority.HIGH,
        _t("Days after setting", "days", "21", Operator.GTE),
        BRANCH,
        description="A tray setting has reached hatch age with no hatch entry.",
    ),
    RuleSpec(
        "hatchery.poor_hatchability", "Poor Hatchability", Module.HATCHERY,
        Priority.HIGH, _t("Hatchability", "%", "80.00", Operator.LTE),
        BRANCH,
        description="Chicks hatched as a share of eggs set falls below target.",
    ),
    RuleSpec(
        "hatchery.low_chick_output", "Low Chick Output", Module.HATCHERY,
        Priority.MEDIUM, _t("Saleable chicks", "chicks", "1000", Operator.LTE),
        BRANCH,
        description="A hatch produced fewer saleable chicks than expected.",
    ),
    RuleSpec(
        "hatchery.high_reject", "High Reject %", Module.HATCHERY, Priority.HIGH,
        _t("Rejects of eggs set", "%", "10.00", Operator.GTE),
        BRANCH,
        description="Culls, malformed and dead-in-shell as a share of eggs set.",
    ),

    # ------------------------------------------------------------------- Health
    RuleSpec(
        "health.vaccination_due", "Vaccination Due", Module.HEALTH, Priority.HIGH,
        _t("Days before due", "days", "1", Operator.LTE), FARM,
        requires="A vaccination schedule master (which vaccine at which bird "
                 "age). Only consumption is recorded today, with nothing to "
                 "compare it against.",
    ),
    RuleSpec(
        "health.vaccination_overdue", "Vaccination Overdue", Module.HEALTH,
        Priority.CRITICAL, _t("Days overdue", "days", "1", Operator.GTE), FARM,
        requires="A vaccination schedule master — same gap as Vaccination Due.",
    ),
    RuleSpec(
        "health.medicine_stock_low", "Medicine Stock Low", Module.HEALTH,
        Priority.HIGH, _t("Quantity on hand", "units", "10", Operator.LTE),
        WAREHOUSE,
        description="A medicine or vaccine item has fallen to the limit.",
    ),
    RuleSpec(
        "health.medicine_expired", "Medicine Expired", Module.HEALTH,
        Priority.CRITICAL, None, WAREHOUSE,
        description="A purchased medicine batch is past its expiry date.",
    ),
    RuleSpec(
        "health.medicine_expiring", "Medicine Expiring Soon", Module.HEALTH,
        Priority.HIGH, _t("Days to expiry", "days", "30", Operator.LTE),
        WAREHOUSE,
        description="A medicine batch expires within the warning window.",
    ),
    RuleSpec(
        "health.disease_alert", "Disease Alert", Module.HEALTH, Priority.CRITICAL,
        None, FARM,
        description="A disease has been recorded against a live flock.",
    ),
    RuleSpec(
        "health.lab_report_pending", "Lab Report Pending", Module.HEALTH,
        Priority.MEDIUM, _t("Days pending", "days", "3", Operator.GTE), FARM,
        requires="A lab sample / report model. Nothing records lab submissions.",
    ),
    RuleSpec(
        "health.vet_visit_due", "Vet Visit Due", Module.HEALTH, Priority.MEDIUM,
        _t("Days since last visit", "days", "14", Operator.GTE), FARM,
        requires="A veterinary visit log or schedule.",
    ),

    # ---------------------------------------------------------------- Inventory
    RuleSpec(
        "inventory.low_stock", "Low Stock", Module.INVENTORY, Priority.HIGH,
        _t("Quantity on hand", "units", "10", Operator.LTE), WAREHOUSE,
        description="An item's balance at a location has fallen to the limit.",
    ),
    RuleSpec(
        "inventory.negative_stock", "Negative Stock", Module.INVENTORY,
        Priority.CRITICAL, None, WAREHOUSE,
        description="Stock was booked out of a location it was never booked into.",
    ),
    RuleSpec(
        "inventory.reorder_level", "Reorder Level Crossed", Module.INVENTORY,
        Priority.HIGH, None, WAREHOUSE,
        requires="A reorder level field on the Item master. Use Low Stock with a "
                 "threshold until each item can carry its own level.",
    ),
    RuleSpec(
        "inventory.verification_due", "Stock Verification Due", Module.INVENTORY,
        Priority.MEDIUM, _t("Days since last count", "days", "90", Operator.GTE),
        WAREHOUSE,
        requires="A physical stock verification / count document to date from.",
    ),
    RuleSpec(
        "inventory.item_expired", "Item Expired", Module.INVENTORY,
        Priority.CRITICAL, None, WAREHOUSE,
        description="A purchased batch is past its expiry date.",
    ),
    RuleSpec(
        "inventory.item_near_expiry", "Item Near Expiry", Module.INVENTORY,
        Priority.HIGH, _t("Days to expiry", "days", "30", Operator.LTE),
        WAREHOUSE,
        description="A purchased batch expires within the warning window.",
    ),
    RuleSpec(
        "inventory.transfer_pending", "Warehouse Transfer Pending",
        Module.INVENTORY, Priority.MEDIUM,
        _t("Days pending", "days", "2", Operator.GTE), WAREHOUSE,
        requires="An in-transit or approval state on stock transfers; they post "
                 "in one step today.",
    ),

    # ----------------------------------------------------------------- Purchase
    RuleSpec(
        "purchase.order_pending", "Purchase Order Pending", Module.PURCHASE,
        Priority.MEDIUM, _t("Days pending", "days", "3", Operator.GTE), CENTRE,
        requires="A purchase order document. Purchases are recorded as completed "
                 "invoices with no preceding order.",
    ),
    RuleSpec(
        "purchase.grn_pending", "GRN Pending", Module.PURCHASE, Priority.MEDIUM,
        _t("Days pending", "days", "2", Operator.GTE), WAREHOUSE,
        requires="A goods receipt note separate from the purchase invoice.",
    ),
    RuleSpec(
        "purchase.supplier_invoice_pending", "Supplier Invoice Pending",
        Module.PURCHASE, Priority.MEDIUM,
        _t("Days pending", "days", "7", Operator.GTE), CENTRE,
        requires="A receipt-without-invoice state, which needs GRN first.",
    ),
    RuleSpec(
        "purchase.approval_pending", "Purchase Approval Pending", Module.PURCHASE,
        Priority.HIGH, _t("Days pending", "days", "1", Operator.GTE), CENTRE,
        requires="An approval workflow on purchases. Nothing marks a purchase as "
                 "awaiting approval.",
    ),
    RuleSpec(
        "purchase.rate_difference", "Rate Difference", Module.PURCHASE,
        Priority.HIGH, _t("Above last rate", "%", "10.00", Operator.GTE), CENTRE,
        description="An item was purchased well above its previous rate.",
    ),
    RuleSpec(
        "purchase.duplicate_invoice", "Duplicate Invoice", Module.PURCHASE,
        Priority.CRITICAL, None, CENTRE,
        description="The same supplier invoice reference has been entered twice.",
    ),

    # -------------------------------------------------------------------- Sales
    RuleSpec(
        "sales.order_pending", "Sales Order Pending", Module.SALES,
        Priority.MEDIUM, _t("Days pending", "days", "2", Operator.GTE), CENTRE,
        requires="A sales order document preceding the invoice.",
    ),
    RuleSpec(
        "sales.dispatch_pending", "Dispatch Pending", Module.SALES,
        Priority.MEDIUM, _t("Days pending", "days", "1", Operator.GTE), CENTRE,
        requires="A dispatch/delivery state on sales invoices.",
    ),
    RuleSpec(
        "sales.invoice_pending", "Invoice Pending", Module.SALES, Priority.MEDIUM,
        _t("Days pending", "days", "2", Operator.GTE), CENTRE,
        requires="A delivered-but-uninvoiced state, which needs dispatch first.",
    ),
    RuleSpec(
        "sales.payment_pending", "Payment Pending", Module.SALES, Priority.HIGH,
        _t("Days past due", "days", "1", Operator.GTE), CENTRE,
        description="A sales invoice is past its due date and unpaid.",
    ),
    RuleSpec(
        "sales.credit_limit_exceeded", "Credit Limit Exceeded", Module.SALES,
        Priority.CRITICAL, None, CENTRE,
        description="A customer's outstanding balance is over their credit limit.",
    ),
    RuleSpec(
        "sales.overdue_customer", "Overdue Customer", Module.SALES, Priority.HIGH,
        _t("Days since last receipt", "days", "45", Operator.GTE), CENTRE,
        description="A customer owes money and has not paid in a long time.",
    ),

    # ------------------------------------------------------------------ Finance
    RuleSpec(
        "finance.payment_due", "Payment Due", Module.FINANCE, Priority.HIGH,
        _t("Outstanding", "₹", "1", Operator.GTE), CENTRE,
        description="A supplier balance is payable.",
    ),
    RuleSpec(
        "finance.receivable_overdue", "Receivable Overdue", Module.FINANCE,
        Priority.HIGH, _t("Days since last receipt", "days", "30", Operator.GTE),
        CENTRE,
        description="A customer receivable has aged past the limit.",
    ),
    RuleSpec(
        "finance.cheque_bounce", "Cheque Bounce", Module.FINANCE,
        Priority.CRITICAL, None, CENTRE,
        requires="A cheque status / dishonour field on receipts and payments.",
    ),
    RuleSpec(
        "finance.journal_approval_pending", "Journal Approval Pending",
        Module.FINANCE, Priority.MEDIUM,
        _t("Days in draft", "days", "2", Operator.GTE), CENTRE,
        description="A voucher has sat in Draft without being posted.",
    ),
    RuleSpec(
        "finance.bank_reconciliation_pending", "Bank Reconciliation Pending",
        Module.FINANCE, Priority.MEDIUM,
        _t("Days since last reconciliation", "days", "30", Operator.GTE), CENTRE,
        requires="A bank reconciliation document or a cleared flag on bank lines.",
    ),
    RuleSpec(
        "finance.cash_balance_low", "Cash Balance Low", Module.FINANCE,
        Priority.HIGH, _t("Balance", "₹", "10000", Operator.LTE), CENTRE,
        requires="A posted-ledger balance per cash account. The journal engine "
                 "exists but cash/bank balances are not yet summarised for it.",
    ),
    RuleSpec(
        "finance.budget_exceeded", "Cost Centre Budget Exceeded", Module.FINANCE,
        Priority.HIGH, _t("Of budget", "%", "100.00", Operator.GTE), CENTRE,
        requires="A budget figure per organization centre to compare actuals to.",
    ),

    # ----------------------------------------------------------------------- HR
    RuleSpec(
        "hr.attendance_missing", "Attendance Missing", Module.HR, Priority.MEDIUM,
        _t("Days missing", "days", "1", Operator.GTE), BRANCH,
        description="An active employee has no attendance recorded for a day.",
    ),
    RuleSpec(
        "hr.leave_approval_pending", "Leave Approval Pending", Module.HR,
        Priority.MEDIUM, _t("Days pending", "days", "2", Operator.GTE), BRANCH,
        description="A leave request is still awaiting a decision.",
    ),
    RuleSpec(
        "hr.salary_processing_due", "Salary Processing Due", Module.HR,
        Priority.HIGH, _t("Day of month", "day", "1", Operator.GTE), BRANCH,
        description="The month has closed with no payroll run recorded.",
    ),
    RuleSpec(
        "hr.document_expired", "Employee Document Expired", Module.HR,
        Priority.HIGH, _t("Days to expiry", "days", "30", Operator.LTE), BRANCH,
        requires="Expiry dates on employee documents. Documents are stored "
                 "without validity dates.",
    ),
    RuleSpec(
        "hr.contract_renewal", "Contract Renewal", Module.HR, Priority.MEDIUM,
        _t("Days to end", "days", "30", Operator.LTE), BRANCH,
        requires="A contract end date on the employee master.",
    ),

    # ------------------------------------------------------------------- System
    RuleSpec(
        "system.backup_failed", "Backup Failed", Module.SYSTEM, Priority.CRITICAL,
        None, (),
        requires="A backup job that reports its outcome to the ERP.",
    ),
    RuleSpec(
        "system.license_expiry", "License Expiry", Module.SYSTEM, Priority.HIGH,
        _t("Days to expiry", "days", "30", Operator.LTE), (),
        requires="A licence record with an expiry date.",
    ),
    RuleSpec(
        "system.storage_low", "Database Storage Low", Module.SYSTEM,
        Priority.CRITICAL, _t("Free space", "%", "10.00", Operator.LTE), (),
        description="Free disk space on the database volume is running out.",
    ),
    RuleSpec(
        "system.login_failed", "Login Failed", Module.SYSTEM, Priority.MEDIUM,
        _t("Failures in an hour", "attempts", "5", Operator.GTE), (),
        description="Repeated failed logins for one account.",
    ),
    RuleSpec(
        "system.unauthorized_login", "Unauthorized Login", Module.SYSTEM,
        Priority.CRITICAL, None, (),
        description="A request was refused by the Web-Access matrix.",
    ),
    RuleSpec(
        "system.server_offline", "Server Offline", Module.SYSTEM,
        Priority.CRITICAL, None, (),
        requires="An external uptime monitor. A server that is down cannot "
                 "raise its own alert from inside itself.",
    ),
    RuleSpec(
        "system.api_failure", "API Failure", Module.SYSTEM, Priority.HIGH,
        _t("Failures in an hour", "errors", "10", Operator.GTE), (),
        requires="An API error counter. Failures are logged to file, which the "
                 "scanner cannot query reliably (see the log-rotation caveat).",
    ),
)


#: key -> RuleSpec, the lookup everything else uses.
BY_KEY = {spec.key: spec for spec in CATALOG}

#: The choices tuple for AlertRule.rule_key, grouped by module so the config
#: master's dropdown is navigable rather than a flat list of seventy.
def rule_key_choices():
    groups: dict[str, list] = {}
    for spec in CATALOG:
        label = spec.label if spec.supported else f"{spec.label} (needs data source)"
        groups.setdefault(Module(spec.module).label, []).append((spec.key, label))
    return [(module, options) for module, options in groups.items()]


def specs_for_module(module: str) -> list[RuleSpec]:
    return [spec for spec in CATALOG if spec.module == module]


def supported_keys() -> set[str]:
    return {spec.key for spec in CATALOG if spec.supported}
