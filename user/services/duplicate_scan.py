"""Find records that look like they were entered twice.

Two different problems share one page, because the question people ask is the
same — "is this in here more than once?" — even though the consequences differ.

A duplicated **entry** double-counts something that was measured: two daily
entries for one flock on one day book the mortality, culls and feed twice, and
those figures run straight into the flock count, the FCR and the settlement. A
duplicated **master** splits one real thing across two records: half a farmer's
history under one code and half under another, payments against whichever was
open at the time.

Nothing here decides anything. Names legitimately repeat, a supplier can bill
the same number twice in different years, and a flock really can be fed twice
in a day by two supervisors. Every group is a question for somebody who knows
the business, so this reports and never merges, edits or deletes.

Read-only by construction: the module imports models and runs queries, and has
no write path at all.
"""
from dataclasses import dataclass, field
from typing import Callable, Optional

from django.db.models import Count, Q
from django.db.models.functions import Lower

# Modules a check belongs to, for the page's filter.
BROILER, PURCHASE, INVENTORY, ACCOUNT, SALES, HATCHERY, HR = (
    "Broiler", "Purchase", "Inventory", "Account", "Sales", "Hatchery", "Human Resource")


@dataclass
class Row:
    """One record inside a suspected duplicate group, as table cells."""
    id: int
    cells: list[str] = field(default_factory=list)

    @property
    def searchable(self) -> str:
        return " ".join(str(c) for c in self.cells)


@dataclass
class Group:
    """Records that matched each other."""
    matched: str
    rows: list[Row] = field(default_factory=list)


#: check code -> the tab code its records are entered on. The label and the
#: module path come from the access registry, so a tab renamed there is renamed
#: here too rather than drifting into a second copy.
CHECK_TABS = {
    "daily_entry": "daily_entry_list",
    "medicine_entry": "medicine_entry_list",
    "bird_sale": "bird_sale_list",
    "bird_sale_receipt": "bird_sale_receipt_list",
    "gc_payment": "farmer_gc_payment",
    "purchase_bill": "general_purchase_list",
    "purchase_line": "general_purchase_list",
    "debitnote": "debit_note_list",
    "creditnote": "credit_note_list",
    "customerdebitnote": "customer_debit_note_list",
    "customercreditnote": "customer_credit_note_list",
    "sales_invoice_reference": "sales_invoice_list",
    "sales_receipt": "sales_receipt_list",
    "voucher_narration": "vouchers",
    "stock_transfer": "stock_transfer_list",
    "medicine_transfer": "medicine_transfer_list",
    "inventory_adjustment": "inventory_adjustment_list",
    "stock_issue": "stock_issue_list",
    "stock_receive": "stock_receive_list",
    "egg_purchase_line": "egg_purchase_list",
    "egg_grading": "egg_grading_list",
    "tray_setting": "tray_set_list",
    "delivery_challan": "delivery_challan_list",
    "payroll_period": "payroll",
    # Masters
    "farmer_name": "branch_farm",
    "farmer_mobile_no": "branch_farm",
    "farmer_pan_no": "branch_farm",
    "farmer_aadhar_no": "branch_farm",
    "farm_name": "branch_farm",
    "item_description": "items",
    "supplier_name": "supplier",
    "supplier_mobile": "supplier",
    "supplier_gstin": "supplier",
    "customer_name": "customer",
    "employee_name": "employee_list",
    "employee_personal_contact": "employee_list",
    "employee_pan_card": "employee_list",
    "employee_aadhar_number": "employee_list",
}

#: nav key -> the module name shown on the page.
NAV_LABELS = {
    "broiler": "Broiler", "hatchery": "Hatchery", "purchase": "Purchase",
    "sales": "Sales", "account": "Account", "inventory": "Inventory",
    "hr": "Human Resource", "user": "User",
}

_TAB_PATHS: Optional[dict] = None


def _tab_paths() -> dict:
    """``{tab code: (module, section, label)}``, read once from the registry."""
    global _TAB_PATHS
    if _TAB_PATHS is None:
        from user.access import iter_tabs

        _TAB_PATHS = {code: (NAV_LABELS.get(nav, nav.title()), section, label)
                      for nav, section, code, label, _extra in iter_tabs()}
    return _TAB_PATHS


@dataclass
class Check:
    """One question asked of one model."""
    code: str
    title: str
    kind: str                                    # "entry" or "master"
    module: str
    matched_on: str                              # what had to be equal
    why: str                                     # what a duplicate here costs
    columns: list[str] = field(default_factory=list)
    groups: list[Group] = field(default_factory=list)
    error: str = ""                              # set when the check could not run
    tab: str = ""                                # where these records are entered
    url: str = ""                                # that tab's page, when it can be reached

    @property
    def count(self) -> int:
        return len(self.groups)

    @property
    def where(self) -> str:
        """"Broiler › Transactions › Daily Entry" — the page to go and look at.

        Knowing a duplicate exists is only half of it; the other half is where
        to open it. Built from the access registry rather than written out
        here, so a tab renamed there does not leave this saying the old name.
        """
        path = _tab_paths().get(self.tab)
        return " › ".join(path) if path else self.module

    @property
    def tab_label(self) -> str:
        path = _tab_paths().get(self.tab)
        return path[2] if path else ""

    @property
    def records(self) -> int:
        return sum(len(g.rows) for g in self.groups)


def _duplicate_keys(queryset, fields):
    """``(key, how_many)`` for every value of ``fields`` on more than one row.

    The count rides along because the counts-only pass needs it: without it a
    card could say how many groups there were but not how many records they
    held, and "records involved" would read zero for ever.
    """
    rows = (queryset.values(*fields).annotate(n=Count("id")).filter(n__gt=1).order_by())
    return [({f: row[f] for f in fields}, row["n"]) for row in rows]


#: Set while a caller only wants the counts. The checks are written as one
#: expression each, so the cheapest way to skip the row fetch is to make the
#: fetch itself a no-op that still reports how many groups there were.
_COUNTS_ONLY = False


def _collect(queryset, fields, keys, cells, matched=None, limit=200):
    """Turn duplicate keys back into groups of real rows.

    One query for all of them rather than one per group: a master with a long
    tail of repeats would otherwise cost hundreds of round trips.
    """
    if not keys:
        return []
    if _COUNTS_ONLY:
        # Placeholder rows, real counts: enough for "3 groups, 7 records", and
        # cheap enough for a dashboard that renders on every page load.
        return [Group(matched="", rows=[Row(id=0) for _ in range(n)])
                for _key, n in keys[:limit]]
    match = Q()
    for key, _n in keys[:limit]:
        match |= Q(**key)
    grouped: dict[tuple, Group] = {}
    for obj in queryset.filter(match):
        signature = tuple(_value(obj, f) for f in fields)
        group = grouped.get(signature)
        if group is None:
            group = Group(matched=(matched(obj) if matched else " · ".join(
                str(v) for v in signature if v not in (None, ""))))
            grouped[signature] = group
        group.rows.append(Row(id=obj.pk, cells=[_text(c) for c in cells(obj)]))
    # A key that ends up with one row came from a filter the re-query narrowed;
    # it is not a duplicate, so it does not belong in the answer.
    return [g for g in grouped.values() if len(g.rows) > 1]


def _value(obj, field_path):
    """Read a grouping key off a row.

    Annotations land on the instance as plain attributes, so the lower-cased
    name the query grouped by is read exactly like a real column. Skipping it
    here — the first version did — gave every row a signature of its own, so
    nothing ever grouped and every case-insensitive check reported clean.
    """
    value = obj
    for part in field_path.split("__"):
        value = getattr(value, part, None)
        if value is None:
            return None
    return value


def _text(value):
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%d %b %Y")
    return str(value)


def _date(obj):
    return _text(getattr(obj, "date", None))


def _where(obj, *names):
    """The first of ``names`` this row actually has, as a place name.

    Warehouses, farms and branches are all "where" to the person reading the
    table, and each model spells it differently — warehouse, farm_warehouse,
    sector, storage_location, to_farm. One reader keeps the column meaning the
    same thing across every check.
    """
    for name in names:
        value = _value(obj, name) if "__" in name else getattr(obj, name, None)
        if value is None:
            continue
        for attr in ("name", "farm_name", "branch_name", "description"):
            label = getattr(value, attr, None)
            if label:
                return label
        return str(value)
    return ""


def _branch_of_farm(obj, farm_attr="farm"):
    """The branch a farm belongs to, for rows that carry a farm but not a branch."""
    farm = getattr(obj, farm_attr, None)
    branch = getattr(farm, "branch", None) if farm is not None else None
    return getattr(branch, "branch_name", "") if branch is not None else ""


# ---------------------------------------------------------------------------
# Transaction entries
# ---------------------------------------------------------------------------

def _entry_checks():
    from broiler.models import BirdSale, DailyEntry, MedicineVaccineEntry

    daily = (DailyEntry.objects
             .select_related("farm", "farm__branch", "batch", "supervisor", "feed_1", "feed_2")
             .exclude(batch__isnull=True))
    yield Check(
        code="daily_entry", kind="entry", module=BROILER,
        title="Two daily entries for one flock on one day",
        matched_on="Farm + Batch + Date",
        why="Mortality, culls and feed are counted twice, which moves the FCR and the settlement.",
        columns=["Entry No", "Date", "Branch", "Farm", "Batch", "Age", "Mortality", "Culls",
                 "Feed 1", "Qty", "Feed 2", "Qty", "Entered by", "Entered at"],
        groups=_collect(
            daily, ["batch_id", "date"], _duplicate_keys(daily, ["batch_id", "date"]),
            cells=lambda e: [e.entry_no or f"#{e.pk}", e.date, _branch_of_farm(e),
                             e.farm.farm_name if e.farm_id else "",
                             e.batch.batch_name if e.batch_id else "",
                             f"{e.age_days} d" if e.age_days else "",
                             e.mortality, e.culls,
                             e.feed_1.description if e.feed_1_id else "", e.feed_1_qty,
                             e.feed_2.description if e.feed_2_id else "", e.feed_2_qty,
                             e.supervisor.name if e.supervisor_id else "",
                             _text(getattr(e, "created_at", None))],
            matched=lambda e: f"{e.batch.batch_name if e.batch_id else ''} on {_date(e)}"))

    medicine = (MedicineVaccineEntry.objects
                .select_related("farm", "farm__branch", "batch", "item", "supervisor")
                .exclude(item__isnull=True))
    yield Check(
        code="medicine_entry", kind="entry", module=BROILER,
        title="Same medicine booked twice on one day",
        matched_on="Farm + Item + Date",
        why="The farm is charged twice and its medicine stock is understated.",
        columns=["Entry No", "Date", "Branch", "Farm", "Batch", "Age", "Item", "Qty",
                 "Entered by"],
        groups=_collect(
            medicine, ["farm_id", "item_id", "date"],
            _duplicate_keys(medicine, ["farm_id", "item_id", "date"]),
            cells=lambda e: [e.entry_no or f"#{e.pk}", e.date, _branch_of_farm(e),
                             e.farm.farm_name if e.farm_id else "",
                             e.batch.batch_name if e.batch_id else "",
                             f"{e.age_days} d" if e.age_days else "",
                             e.item.description if e.item_id else "", e.qty,
                             e.supervisor.name if e.supervisor_id else ""],
            matched=lambda e: f"{e.item.description if e.item_id else ''} on {_date(e)}"))

    sales = (BirdSale.objects
             .select_related("farm", "farm__branch", "batch", "customer", "farmer")
             .exclude(batch__isnull=True))
    yield Check(
        code="bird_sale", kind="entry", module=BROILER,
        title="Identical bird sales on one day",
        matched_on="Batch + Date + Birds",
        why="Birds are taken off the flock twice, so what is left reads low.",
        columns=["Sale No", "Date", "Branch", "Farm", "Batch", "Birds", "Net weight",
                 "Sold to", "Doc No"],
        groups=_collect(
            sales, ["batch_id", "date", "birds"],
            _duplicate_keys(sales, ["batch_id", "date", "birds"]),
            cells=lambda s: [s.sale_no or f"#{s.pk}", s.date, _branch_of_farm(s),
                             s.farm.farm_name if s.farm_id else "",
                             s.batch.batch_name if s.batch_id else "", s.birds, s.net_weight,
                             (s.customer.name if s.customer_id else
                              s.farmer.farmer_name if s.farmer_id else ""),
                             s.doc_no or ""],
            matched=lambda s: f"{s.birds} birds on {_date(s)}"))


def _purchase_checks():
    from purchase.models import GeneralPurchase, GeneralPurchaseItem

    bills = (GeneralPurchase.objects.select_related("supplier")
             .exclude(Q(bill_no__isnull=True) | Q(bill_no="")))
    yield Check(
        code="purchase_bill", kind="entry", module=PURCHASE,
        title="One supplier bill entered twice",
        matched_on="Supplier + Bill No",
        why="The same invoice is paid and stocked twice.",
        columns=["Purchase No", "Date", "Supplier", "Bill No"],
        groups=_collect(
            bills, ["supplier_id", "bill_no"], _duplicate_keys(bills, ["supplier_id", "bill_no"]),
            cells=lambda p: [p.purchase_no or f"#{p.pk}", p.date,
                             p.supplier.name if p.supplier_id else "", p.bill_no],
            matched=lambda p: f"bill {p.bill_no}"))

    lines = GeneralPurchaseItem.objects.select_related(
        "purchase", "purchase__supplier", "item", "farm_warehouse", "farm")
    fields = ["purchase__supplier_id", "item_id", "purchase__date", "rcv_qty", "rate"]
    yield Check(
        code="purchase_line", kind="entry", module=PURCHASE,
        title="Same purchase line entered twice",
        matched_on="Supplier + Item + Date + Qty + Rate",
        why="The same delivery is stocked and costed twice, even under different bill numbers.",
        columns=["Purchase No", "Date", "Supplier", "Bill No", "Warehouse", "Item", "Unit",
                 "Sent", "Received", "Free", "Rate", "Discount", "GST %", "Amount"],
        groups=_collect(
            lines, fields, _duplicate_keys(lines, fields),
            cells=lambda l: [l.purchase.purchase_no if l.purchase_id else f"#{l.pk}",
                             l.purchase.date if l.purchase_id else "",
                             l.purchase.supplier.name if l.purchase_id and l.purchase.supplier_id else "",
                             l.purchase.bill_no if l.purchase_id else "",
                             _where(l, "farm_warehouse", "farm"),
                             l.item.description if l.item_id else "", l.unit or "",
                             l.sent_qty, l.rcv_qty, l.free_qty, l.rate,
                             l.discount_amount, l.gst_percent, l.amount],
            matched=lambda l: f"{l.item.description if l.item_id else ''} × {l.rcv_qty}"))


def _transfer_checks():
    from inventory.models import StockTransfer

    transfers = StockTransfer.objects.select_related(
        "item", "from_warehouse", "to_warehouse", "from_farm", "to_farm")
    # Source as well as destination. Without it, two transfers of the same item
    # and quantity arriving somewhere on one day looked identical even when they
    # came from different farms — which is a delivery from each, not a duplicate.
    fields = ["item_id", "date", "quantity",
              "from_warehouse_id", "from_farm_id", "to_warehouse_id", "to_farm_id"]

    def where(t):
        for obj in (t.to_warehouse, t.to_farm):
            if obj is not None:
                return getattr(obj, "name", None) or getattr(obj, "farm_name", "")
        return ""

    yield Check(
        code="stock_transfer", kind="entry", module=INVENTORY,
        title="Same stock transfer entered twice",
        matched_on="Item + Source + Destination + Date + Quantity",
        why="Stock is moved twice on paper, so the source reads low and the destination high.",
        columns=["Transfer No", "Date", "DC No", "Item", "From", "To", "Quantity", "Rate"],
        groups=_collect(
            transfers, fields, _duplicate_keys(transfers, fields),
            cells=lambda t: [t.trnum or f"#{t.pk}", t.date, t.dc_no or "",
                             t.item.description if t.item_id else "",
                             _where(t, "from_warehouse", "from_farm"), where(t),
                             t.quantity, t.rate],
            matched=lambda t: f"{t.item.description if t.item_id else ''} × {t.quantity} on {_date(t)}"))


def _voucher_checks():
    from account.models import Voucher

    vouchers = Voucher.objects.select_related("sector").exclude(
        Q(narration__isnull=True) | Q(narration=""))
    fields = ["voucher_type", "date", "narration"]
    yield Check(
        code="voucher_narration", kind="entry", module=ACCOUNT,
        title="Same voucher entered twice",
        matched_on="Type + Date + Narration",
        why="The same expense or payment is posted twice to the ledger.",
        columns=["Voucher No", "Date", "Type", "Sector", "Narration"],
        groups=_collect(
            vouchers, fields, _duplicate_keys(vouchers, fields),
            cells=lambda v: [v.voucher_no or f"#{v.pk}", v.date, v.voucher_type,
                             _where(v, "sector"), (v.narration or "")[:80]],
            matched=lambda v: f"{v.voucher_type} on {_date(v)}"))


def _money_checks():
    """Where a duplicate moves cash rather than a figure.

    Receipts and payments are matched on party, date and amount: the same
    money, from the same person, on the same day. That is a real pattern in
    honest data — somebody can pay in two instalments of the same size — so
    these are questions like all the rest, not findings.
    """
    from broiler.models import BirdSaleReceipt, FarmerGCPayment
    from purchase.models import CreditNote, DebitNote
    from sales.models import CustomerCreditNote, CustomerDebitNote, SalesInvoice, SalesReceipt

    invoices = SalesInvoice.objects.select_related("customer")
    fields = ["customer_id", "date", "reference_no"]
    yield Check(
        code="sales_invoice_reference", kind="entry", module=SALES,
        title="Same sales invoice reference twice",
        matched_on="Customer + Date + Reference",
        why="One despatch is billed twice, so the customer's balance reads high.",
        columns=["Invoice No", "Date", "Customer", "Reference"],
        groups=_collect(
            invoices.exclude(Q(reference_no__isnull=True) | Q(reference_no="")),
            fields,
            _duplicate_keys(invoices.exclude(Q(reference_no__isnull=True) | Q(reference_no="")), fields),
            cells=lambda i: [i.invoice_no or f"#{i.pk}", i.date,
                             i.customer.name if i.customer_id else "", i.reference_no],
            matched=lambda i: f"reference {i.reference_no}"))

    receipts = SalesReceipt.objects.select_related("customer", "location")
    fields = ["customer_id", "date", "amount"]
    yield Check(
        code="sales_receipt", kind="entry", module=SALES,
        title="Same customer receipt twice on one day",
        matched_on="Customer + Date + Amount",
        why="Money is credited twice, so the customer appears to owe less than they do.",
        columns=["Receipt No", "Date", "Customer", "Location", "Mode", "Reference",
                 "Remarks", "Amount"],
        groups=_collect(
            receipts, fields, _duplicate_keys(receipts, fields),
            cells=lambda r: [r.receipt_no or f"#{r.pk}", r.date,
                             r.customer.name if r.customer_id else "",
                             _where(r, "location"), r.mode, r.reference_no or "",
                             (r.remarks or "")[:40], r.amount],
            matched=lambda r: f"{r.amount} on {_date(r)}"))

    bird_receipts = BirdSaleReceipt.objects.select_related("customer", "farmer", "location")
    fields = ["customer_id", "farmer_id", "date", "amount"]
    yield Check(
        code="bird_sale_receipt", kind="entry", module=BROILER,
        title="Same bird sale receipt twice on one day",
        matched_on="Payer + Date + Amount",
        why="Collection against bird sales is counted twice.",
        columns=["Receipt No", "Date", "Received from", "Location", "Mode", "Reference",
                 "Remarks", "Amount"],
        groups=_collect(
            bird_receipts, fields, _duplicate_keys(bird_receipts, fields),
            cells=lambda r: [r.receipt_no or f"#{r.pk}", r.date,
                             (r.customer.name if r.customer_id else
                              r.farmer.farmer_name if r.farmer_id else ""),
                             _where(r, "location"), r.mode, r.reference_no or "",
                             (r.remarks or "")[:40], r.amount],
            matched=lambda r: f"{r.amount} on {_date(r)}"))

    payments = FarmerGCPayment.objects.all()
    fields = ["date", "narration"]
    yield Check(
        code="gc_payment", kind="entry", module=BROILER,
        title="Same growing charge payment twice",
        matched_on="Date + Narration",
        why="A farmer is paid twice for the same settlement.",
        columns=["Payment No", "Date", "Narration"],
        groups=_collect(
            payments.exclude(narration=""), fields,
            _duplicate_keys(payments.exclude(narration=""), fields),
            cells=lambda p: [p.payment_no or f"#{p.pk}", p.date, (p.narration or "")[:70]],
            matched=lambda p: f"on {_date(p)}"))

    # The four note types share a shape, so they share a loop: party, date and
    # amount, against the same bill.
    for model, module, party, label in (
            (DebitNote, PURCHASE, "supplier", "supplier debit note"),
            (CreditNote, PURCHASE, "supplier", "supplier credit note"),
            (CustomerDebitNote, SALES, "customer", "customer debit note"),
            (CustomerCreditNote, SALES, "customer", "customer credit note")):
        rows = model.objects.select_related(party, "sector")
        fields = [f"{party}_id", "date", "amount"]
        yield Check(
            code=f"{model.__name__.lower()}", kind="entry", module=module,
            title=f"Same {label} twice on one day",
            matched_on=f"{party.capitalize()} + Date + Amount",
            why="The adjustment is applied twice, moving the balance twice as far.",
            columns=["Note No", "Date", party.capitalize(), "Sector", "Against bill", "Amount"],
            groups=_collect(
                rows, fields, _duplicate_keys(rows, fields),
                cells=lambda n, party=party: [
                    n.note_no or f"#{n.pk}", n.date,
                    getattr(getattr(n, party, None), "name", "") or "",
                    _where(n, "sector"), n.against_bill or "", n.amount],
                matched=lambda n: f"{n.amount} on {_date(n)}"))


def _stock_movement_checks():
    """Movements that are not the plain Stock Transfer already covered."""
    from inventory.models import (InventoryAdjustmentItem, MedicineTransfer,
                                  StockIssueItem, StockReceiveItem)

    medicine = MedicineTransfer.objects.select_related(
        "from_warehouse", "to_warehouse", "from_farm", "to_farm")
    fields = ["date", "dc_no", "to_warehouse_id", "to_farm_id"]
    with_dc = medicine.exclude(Q(dc_no__isnull=True) | Q(dc_no=""))
    yield Check(
        code="medicine_transfer", kind="entry", module=INVENTORY,
        title="Same medicine transfer entered twice",
        matched_on="Destination + Date + DC No",
        why="Medicine is moved twice on paper, so the source reads low.",
        columns=["Transfer No", "Date", "DC No", "To"],
        groups=_collect(
            with_dc, fields, _duplicate_keys(with_dc, fields),
            cells=lambda t: [t.trnum or f"#{t.pk}", t.date, t.dc_no,
                             (getattr(t.to_warehouse, "name", None)
                              or getattr(t.to_farm, "farm_name", "") or "")],
            matched=lambda t: f"DC {t.dc_no} on {_date(t)}"))

    adjustments = InventoryAdjustmentItem.objects.select_related(
        "adjustment", "adjustment__warehouse", "adjustment__farm", "item")
    fields = ["adjustment__date", "item_id", "quantity", "adjustment__warehouse_id",
              "adjustment__farm_id"]
    yield Check(
        code="inventory_adjustment", kind="entry", module=INVENTORY,
        title="Same inventory adjustment twice",
        matched_on="Item + Location + Date + Quantity",
        why="Stock is corrected twice, so the correction overshoots.",
        columns=["Adjustment No", "Date", "Bill No", "Location", "Item", "Type",
                 "Quantity", "Rate", "Amount"],
        groups=_collect(
            adjustments, fields, _duplicate_keys(adjustments, fields),
            cells=lambda a: [a.adjustment.trnum if a.adjustment_id else f"#{a.pk}",
                             a.adjustment.date if a.adjustment_id else "",
                             a.adjustment.bill_no if a.adjustment_id else "",
                             _where(a, "adjustment__warehouse", "adjustment__farm"),
                             a.item.description if a.item_id else "", a.adjustment_type,
                             a.quantity, a.rate, a.amount],
            matched=lambda a: f"{a.item.description if a.item_id else ''} × {a.quantity}"))

    for model, code, title in ((StockIssueItem, "stock_issue", "stock issue"),
                               (StockReceiveItem, "stock_receive", "stock receipt")):
        parent = "issue" if model is StockIssueItem else "receive"
        rows = model.objects.select_related(parent, "item", "warehouse", "farm")
        fields = [f"{parent}__date", "item_id", "quantity"]
        yield Check(
            code=code, kind="entry", module=INVENTORY,
            title=f"Same {title} line twice on one day",
            matched_on="Item + Date + Quantity",
            why="The same movement is booked twice, so the balance moves twice.",
            columns=["Number", "Date", "Location", "Item", "Quantity"],
            groups=_collect(
                rows, fields, _duplicate_keys(rows, fields),
                cells=lambda r, parent=parent: [
                    getattr(getattr(r, parent, None), "trnum", "") or f"#{r.pk}",
                    getattr(getattr(r, parent, None), "date", ""),
                    _where(r, "warehouse", "farm"),
                    r.item.description if r.item_id else "", r.quantity],
                matched=lambda r: f"{r.item.description if r.item_id else ''} × {r.quantity}"))


def _hatchery_production_checks():
    """Hatchery work that is neither a purchase nor a despatch.

    No hatch entry check: ``HatchEntry.tray_setting`` is a one-to-one, so the
    database already refuses a second hatch against one setting — the same
    reason there is no attendance check, and no settlement one.

    Matched on more than the date. Grading twice in a day is ordinary; grading
    the same supplier's same item twice in a day is the thing worth asking
    about.
    """
    from hatchery.models import EggGrading, TraySetting

    gradings = EggGrading.objects.select_related("supplier", "item", "storage_location")
    fields = ["supplier_id", "item_id", "date", "purchase_invoice_id"]
    yield Check(
        code="egg_grading", kind="entry", module=HATCHERY,
        title="Same egg grading entered twice",
        matched_on="Supplier + Item + Date + Invoice",
        why="The same intake is graded twice, so the eggs it sorted are counted twice.",
        columns=["Transaction No", "Date", "Supplier", "Storage", "Item"],
        groups=_collect(
            gradings, fields, _duplicate_keys(gradings, fields),
            cells=lambda g: [g.transaction_no or f"#{g.pk}", g.date,
                             g.supplier.name if g.supplier_id else "",
                             _where(g, "storage_location"),
                             g.item.description if g.item_id else ""],
            matched=lambda g: f"{g.item.description if g.item_id else ''} on {_date(g)}"))

    trays = TraySetting.objects.select_related("hatchery", "grading")
    fields = ["hatchery_id", "grading_id", "setting_date"]
    yield Check(
        code="tray_setting", kind="entry", module=HATCHERY,
        title="Same grading set twice on one day",
        matched_on="Hatchery + Grading + Setting date",
        why="Eggs are recorded into the setters twice, overstating what is incubating.",
        columns=["Setting No", "Setting date", "Hatchery", "Hatch date"],
        groups=_collect(
            trays, fields, _duplicate_keys(trays, fields),
            cells=lambda t: [t.setting_no or f"#{t.pk}", t.setting_date,
                             getattr(t.hatchery, "name", "") if t.hatchery_id else "",
                             t.hatch_date],
            matched=lambda t: f"set on {_text(t.setting_date)}"))


# ---------------------------------------------------------------------------
# Master records
# ---------------------------------------------------------------------------

FARMER_COLUMNS = ["Code", "Farmer", "Mobile", "Group", "Status"]


def _farmer_cells(f):
    return [f.farmer_code, f.farmer_name, f.mobile_no or "",
            f.farmer_group.description if f.farmer_group_id else "",
            "Inactive" if f.status == "inactive" else "Active"]


def _farmer_checks():
    from broiler.models import Farmer

    base = Farmer.objects.select_related("farmer_group")
    named = base.annotate(lower=Lower("farmer_name")).exclude(farmer_name="")
    yield Check(
        code="farmer_name", kind="master", module=BROILER,
        title="Farmers with the same name", matched_on="Name, ignoring case",
        why="Two records for one farmer split their farms, settlements and payments.",
        columns=FARMER_COLUMNS,
        groups=_collect(named, ["lower"], _duplicate_keys(named, ["lower"]), _farmer_cells))

    for fieldname, human in (("mobile_no", "mobile number"), ("pan_no", "PAN"),
                             ("aadhar_no", "Aadhaar number")):
        rows = base.exclude(**{f"{fieldname}__isnull": True}).exclude(**{fieldname: ""})
        yield Check(
            code=f"farmer_{fieldname}", kind="master", module=BROILER,
            title=f"Farmers sharing a {human}", matched_on=human.capitalize(),
            why=f"A {human} belongs to one person, so this is usually the same farmer twice.",
            columns=FARMER_COLUMNS,
            groups=_collect(rows, [fieldname], _duplicate_keys(rows, [fieldname]), _farmer_cells))


def _farm_checks():
    from broiler.models import BroilerFarm

    rows = (BroilerFarm.objects.select_related("branch", "farmer")
            .annotate(lower=Lower("farm_name")).exclude(farm_name=""))
    yield Check(
        code="farm_name", kind="master", module=BROILER,
        title="Farms with the same name at one branch",
        matched_on="Farm name + Branch",
        why="Entries and placements can land on the wrong one, splitting a flock's history.",
        columns=["Code", "Farm", "Branch", "Farmer", "District"],
        groups=_collect(
            rows, ["lower", "branch_id"], _duplicate_keys(rows, ["lower", "branch_id"]),
            cells=lambda f: [f.farm_code, f.farm_name,
                             f.branch.branch_name if f.branch_id else "",
                             f.farmer.farmer_name if f.farmer_id else "", f.district or ""]))


def _item_checks():
    from inventory.models import Item

    rows = (Item.objects.select_related("category")
            .annotate(lower=Lower("description")).exclude(description=""))
    yield Check(
        code="item_description", kind="master", module=INVENTORY,
        title="Items with the same name in one category",
        matched_on="Description + Category",
        why="Stock and cost for one thing end up spread over two codes.",
        columns=["Code", "Item", "Category", "Unit", "Status"],
        groups=_collect(
            rows, ["lower", "category_id"], _duplicate_keys(rows, ["lower", "category_id"]),
            cells=lambda i: [i.item_code, i.description,
                             i.category.name if i.category_id else "",
                             i.storage_uom or "", "Active" if i.is_active else "Inactive"]))


SUPPLIER_COLUMNS = ["Code", "Supplier", "Mobile", "GSTIN", "Place"]


def _supplier_cells(s):
    return [s.code or "", s.name or "", s.mobile or "", s.gstin or "", s.place or ""]


def _party_checks():
    from purchase.models import Supplier
    from sales.models import Customer

    suppliers = Supplier.objects.annotate(lower=Lower("name")).exclude(
        Q(name__isnull=True) | Q(name=""))
    yield Check(
        code="supplier_name", kind="master", module=PURCHASE,
        title="Suppliers with the same name", matched_on="Name, ignoring case",
        why="Purchases and balances split between two records for one supplier.",
        columns=SUPPLIER_COLUMNS,
        groups=_collect(suppliers, ["lower"], _duplicate_keys(suppliers, ["lower"]), _supplier_cells))

    for fieldname, human in (("mobile", "mobile number"), ("gstin", "GSTIN")):
        rows = Supplier.objects.exclude(**{f"{fieldname}__isnull": True}).exclude(**{fieldname: ""})
        yield Check(
            code=f"supplier_{fieldname}", kind="master", module=PURCHASE,
            title=f"Suppliers sharing a {human}", matched_on=human.upper() if fieldname == "gstin" else human.capitalize(),
            why=f"A {human} belongs to one business, so this is usually one supplier entered twice.",
            columns=SUPPLIER_COLUMNS,
            groups=_collect(rows, [fieldname], _duplicate_keys(rows, [fieldname]), _supplier_cells))

    customers = Customer.objects.annotate(lower=Lower("name")).exclude(name="")
    yield Check(
        code="customer_name", kind="master", module=SALES,
        title="Customers with the same name", matched_on="Name, ignoring case",
        why="Sales and receipts split between two records for one customer.",
        columns=["Code", "Customer", "Mobile", "Place", "State"],
        groups=_collect(customers, ["lower"], _duplicate_keys(customers, ["lower"]),
                        cells=lambda c: [c.code or "", c.name, c.mobile or "",
                                         c.place or "", c.state or ""]))


def _hatchery_checks():
    from hatchery.models import DeliveryChallan, EggPurchaseItem

    lines = EggPurchaseItem.objects.select_related(
        "egg_purchase", "egg_purchase__supplier", "egg_purchase__warehouse", "item")
    fields = ["egg_purchase__supplier_id", "item_id", "egg_purchase__date", "rcv_qty", "rate"]
    yield Check(
        code="egg_purchase_line", kind="entry", module=HATCHERY,
        title="Same egg purchase line entered twice",
        matched_on="Supplier + Item + Date + Qty + Rate",
        why="The same intake is stocked and costed twice, which carries into every hatch it feeds.",
        columns=["Transaction No", "Date", "Supplier", "Warehouse", "Item", "Qty", "Rate"],
        groups=_collect(
            lines, fields, _duplicate_keys(lines, fields),
            cells=lambda l: [l.egg_purchase.transaction_no if l.egg_purchase_id else f"#{l.pk}",
                             l.egg_purchase.date if l.egg_purchase_id else "",
                             (l.egg_purchase.supplier.name
                              if l.egg_purchase_id and l.egg_purchase.supplier_id else ""),
                             _where(l, "egg_purchase__warehouse"),
                             l.item.description if l.item_id else "", l.rcv_qty, l.rate],
            matched=lambda l: f"{l.item.description if l.item_id else ''} × {l.rcv_qty}"))

    challans = (DeliveryChallan.objects.select_related("customer")
                .exclude(Q(vehicle_no__isnull=True) | Q(vehicle_no="")))
    fields = ["customer_id", "date", "vehicle_no"]
    yield Check(
        code="delivery_challan", kind="entry", module=HATCHERY,
        title="Same delivery challan raised twice",
        matched_on="Customer + Date + Vehicle",
        why="One lorry-load is billed and taken out of stock twice.",
        columns=["Challan No", "Date", "Customer", "Vehicle"],
        groups=_collect(
            challans, fields, _duplicate_keys(challans, fields),
            cells=lambda d: [d.challan_no or f"#{d.pk}", d.date,
                             d.customer.name if d.customer_id else "", d.vehicle_no],
            matched=lambda d: f"{d.vehicle_no} on {_date(d)}"))


EMPLOYEE_COLUMNS = ["Employee ID", "Name", "Contact", "Warehouse", "Designation", "Department"]


def _employee_cells(e):
    return [e.employee_id, e.full_name or "", e.personal_contact or "",
            _where(e, "warehouse"),
            e.designation.name if e.designation_id and hasattr(e.designation, "name") else "",
            e.department.name if e.department_id and hasattr(e.department, "name") else ""]


def _hr_checks():
    from hr.models import Employee, Payroll

    base = Employee.objects.select_related("designation", "department", "warehouse")
    named = base.annotate(lower=Lower("full_name")).exclude(
        Q(full_name__isnull=True) | Q(full_name=""))
    yield Check(
        code="employee_name", kind="master", module=HR,
        title="Employees with the same name", matched_on="Name, ignoring case",
        why="Two records for one person split their attendance, payroll and access.",
        columns=EMPLOYEE_COLUMNS,
        groups=_collect(named, ["lower"], _duplicate_keys(named, ["lower"]), _employee_cells))

    # personal_contact is a number column, so excluding "" from it is not a
    # comparison the database will accept — only the text fields get that.
    for fieldname, human, is_text in (("personal_contact", "contact number", False),
                                      ("pan_card", "PAN", True),
                                      ("aadhar_number", "Aadhaar number", True)):
        rows = base.exclude(**{f"{fieldname}__isnull": True})
        if is_text:
            rows = rows.exclude(**{fieldname: ""})
        yield Check(
            code=f"employee_{fieldname}", kind="master", module=HR,
            title=f"Employees sharing a {human}", matched_on=human.capitalize(),
            why=f"A {human} belongs to one person, so this is usually one employee entered twice.",
            columns=EMPLOYEE_COLUMNS,
            groups=_collect(rows, [fieldname], _duplicate_keys(rows, [fieldname]), _employee_cells))

    # No attendance check: hr.Attendance carries unique_together on
    # (employee, date), so the database refuses a second mark for one person on
    # one day. A check for it could never fire, and a row reading "Nothing
    # found" for ever says less than the constraint already does.

    payroll = Payroll.objects.select_related("employee")
    fields = ["employee_id", "month", "year"]
    yield Check(
        code="payroll_period", kind="entry", module=HR,
        title="One employee paid twice for a month",
        matched_on="Employee + Month + Year",
        why="The same month's salary is booked twice.",
        columns=["Employee", "Month", "Year", "Gross", "Net", "Payable"],
        groups=_collect(
            payroll, fields, _duplicate_keys(payroll, fields),
            cells=lambda p: [p.employee.full_name if p.employee_id else "", p.month, p.year,
                             p.gross_salary, p.net_salary, p.payable_salary],
            matched=lambda p: f"{p.employee.full_name if p.employee_id else ''} — {p.month}/{p.year}"))


CHECK_SOURCES: list[Callable] = [
    _entry_checks, _purchase_checks, _transfer_checks, _voucher_checks, _hatchery_checks,
    _money_checks, _stock_movement_checks, _hatchery_production_checks,
    _farmer_checks, _farm_checks, _item_checks, _party_checks, _hr_checks,
]


def run(only: Optional[str] = None, module: Optional[str] = None,
        counts_only: bool = False) -> list[Check]:
    """Every check, in the order they are shown.

    A check that raises is reported as a failed check rather than taking the
    page down with it: a scan that answers eleven questions and admits it could
    not answer the twelfth is worth more than an error screen.
    """
    global _COUNTS_ONLY

    checks: list[Check] = []
    was = _COUNTS_ONLY
    _COUNTS_ONLY = counts_only
    try:
        checks = _run_sources()
    finally:
        _COUNTS_ONLY = was
    if only:
        checks = [c for c in checks if c.code == only]
    if module:
        checks = [c for c in checks if c.module == module]
    return checks


def _run_sources() -> list[Check]:
    checks: list[Check] = []
    for source in CHECK_SOURCES:
        try:
            produced = list(source())
        except Exception as exc:                      # noqa: BLE001 — reported, not swallowed
            checks.append(Check(code=source.__name__.strip("_"), title=source.__name__,
                                kind="entry", module="", matched_on="", why="",
                                error=f"{type(exc).__name__}: {exc}"))
            continue
        checks.extend(produced)
    for check in checks:
        check.tab = CHECK_TABS.get(check.code, "")
    return checks


def modules(checks: list[Check]) -> list[str]:
    return sorted({c.module for c in checks if c.module})


def summary(checks: list[Check]) -> dict:
    return {
        "checks": len(checks),
        "with_findings": sum(1 for c in checks if c.count),
        "groups": sum(c.count for c in checks),
        "records": sum(c.records for c in checks),
        "entry_groups": sum(c.count for c in checks if c.kind == "entry"),
        "master_groups": sum(c.count for c in checks if c.kind == "master"),
        "entry_checks": sum(1 for c in checks if c.kind == "entry"),
        "master_checks": sum(1 for c in checks if c.kind == "master"),
        "failed": [c for c in checks if c.error],
    }
