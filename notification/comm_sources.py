"""Document sources and variable resolution for the SMS Transaction module.

Two registries keep the module future-proof without redesign:

* ``SMS_VARIABLES`` — every placeholder the template editor offers. Adding a
  new variable means adding one entry here (and providing it in a source's
  context); templates and the picker pick it up automatically.
* ``DOC_SOURCES`` — each ERP module that can feed the transaction grid. A
  source returns plain row dicts carrying the party, mobile, document number
  and a ready variable context. New channels/modules register here.
"""
from django.utils import timezone

from account.models import CompanyProfile
from hatchery.models import ChickSale, DeliveryChallan, EggPurchase


# Placeholder -> short description shown in the template editor's picker.
SMS_VARIABLES = {
    "CompanyName": "Your company name (Company Profile)",
    "CustomerName": "Customer name",
    "SupplierName": "Supplier name",
    "InvoiceNo": "Document/invoice number",
    "InvoiceDate": "Document date",
    "Amount": "Document amount",
    "Outstanding": "Outstanding amount (when available)",
    "PaidAmount": "Paid amount (when available)",
    "Balance": "Balance amount (when available)",
    "VehicleNo": "Vehicle number",
    "DriverName": "Driver name",
    "LRNo": "LR / transport document number",
    "Warehouse": "Warehouse / stock point",
    "EmployeeName": "Employee name (when available)",
    "Quantity": "Document quantity (birds/eggs)",
    "Rate": "Rate per unit",
    "Weight": "Weight in Kgs (manual/future)",
    "Place": "Delivery place / place of supply",
    "PaymentMode": "Payment mode (manual/future)",
    "ReceiptNo": "Receipt number (manual/future)",
    "TotalDues": "Total dues (manual/future)",
    "CurrentDate": "Today's date",
    "CurrentTime": "Current time",
    "UserName": "Logged-in user sending the SMS",
}


_GENERIC_KEYS = ("CompanyName", "CurrentDate", "CurrentTime", "UserName")
DEFAULT_CONTEXT = {k: "" for k in SMS_VARIABLES if k not in _GENERIC_KEYS}


def common_context(user=None):
    now = timezone.localtime()
    return {
        "CompanyName": CompanyProfile.get_solo().name,
        "CurrentDate": now.strftime("%d-%m-%Y"),
        "CurrentTime": now.strftime("%H:%M"),
        "UserName": getattr(user, "username", "") or "",
    }


def _base_row(*, doc_id, date, party_type, party_id, party_name, mobile,
              doc_no, amount, context):
    return {
        "doc_id": doc_id, "date": date.isoformat(),
        "party_type": party_type, "party_id": party_id,
        "party_name": party_name, "mobile": mobile or "",
        "doc_no": doc_no, "amount": str(amount),
        "context": {**DEFAULT_CONTEXT, **context},
    }


def _chick_sale_rows(from_date, to_date, party_id):
    qs = ChickSale.objects.select_related("customer", "warehouse").prefetch_related("items__item")
    if from_date:
        qs = qs.filter(date__gte=from_date)
    if to_date:
        qs = qs.filter(date__lte=to_date)
    if party_id:
        qs = qs.filter(customer_id=party_id)
    rows = []
    for cs in qs.order_by("-date", "-id"):
        rows.append(_base_row(
            doc_id=cs.id, date=cs.date, party_type="customer",
            party_id=cs.customer_id, party_name=cs.customer.name,
            mobile=cs.customer.mobile, doc_no=cs.bill_no, amount=cs.final_amount,
            context={
                "CustomerName": cs.customer.name, "SupplierName": "",
                "InvoiceNo": cs.bill_no, "InvoiceDate": cs.date.strftime("%d-%m-%Y"),
                "Amount": f"{cs.final_amount:,.2f}", "Outstanding": "", "PaidAmount": "",
                "Balance": "", "VehicleNo": cs.vehicle or "", "DriverName": cs.driver or "",
                "LRNo": "", "Warehouse": cs.warehouse.name, "EmployeeName": "",
                "Quantity": '%g' % cs.total_net_qty(), "Rate": f"{cs.avg_amount:,.2f}",
            },
        ))
    return rows


def _delivery_challan_rows(from_date, to_date, party_id):
    qs = DeliveryChallan.objects.select_related("customer").prefetch_related("items")
    if from_date:
        qs = qs.filter(date__gte=from_date)
    if to_date:
        qs = qs.filter(date__lte=to_date)
    if party_id:
        qs = qs.filter(customer_id=party_id)
    rows = []
    for dc in qs.order_by("-date", "-id"):
        qty = dc.total_quantity()
        # Weighted average rate across items (single-item challans get that
        # item's effective rate).
        rate = (sum((i.amount or 0) for i in dc.items.all()) / qty) if qty else 0
        rows.append(_base_row(
            doc_id=dc.id, date=dc.date, party_type="customer",
            party_id=dc.customer_id, party_name=dc.customer.name,
            mobile=dc.customer.mobile, doc_no=dc.challan_no, amount=dc.grand_total(),
            context={
                "CustomerName": dc.customer.name, "SupplierName": "",
                "InvoiceNo": dc.challan_no, "InvoiceDate": dc.date.strftime("%d-%m-%Y"),
                "Amount": f"{dc.grand_total():,.2f}", "Outstanding": "", "PaidAmount": "",
                "Balance": "", "VehicleNo": dc.vehicle_no or "", "DriverName": dc.driver_name or "",
                "LRNo": dc.transport_document_no or "", "Warehouse": "", "EmployeeName": "",
                "Quantity": '%g' % qty, "Rate": f"{rate:,.2f}",
                "Place": dc.place_of_supply or "",
            },
        ))
    return rows


def _egg_purchase_rows(from_date, to_date, party_id):
    qs = EggPurchase.objects.select_related("supplier", "warehouse").prefetch_related("items")
    if from_date:
        qs = qs.filter(date__gte=from_date)
    if to_date:
        qs = qs.filter(date__lte=to_date)
    if party_id:
        qs = qs.filter(supplier_id=party_id)
    rows = []
    for ep in qs.order_by("-date", "-id"):
        rows.append(_base_row(
            doc_id=ep.id, date=ep.date, party_type="supplier",
            party_id=ep.supplier_id, party_name=ep.supplier.name,
            mobile=ep.supplier.mobile, doc_no=ep.transaction_no, amount=ep.net_amount(),
            context={
                "CustomerName": "", "SupplierName": ep.supplier.name,
                "InvoiceNo": ep.transaction_no, "InvoiceDate": ep.date.strftime("%d-%m-%Y"),
                "Amount": f"{ep.net_amount():,.2f}", "Outstanding": "", "PaidAmount": "",
                "Balance": "", "VehicleNo": ep.vehicle or "", "DriverName": ep.driver or "",
                "LRNo": ep.dc_no or "", "Warehouse": ep.warehouse.name, "EmployeeName": "",
                "Quantity": '%g' % ep.net_quantity(), "Rate": f"{ep.net_rate():,.2f}",
            },
        ))
    return rows


# Module key -> grid source. Party type drives which party filter applies;
# ``module``/``transaction`` are the SmsTemplate.module / SMS_MODULE_TRANSACTIONS
# codes used to offer only templates registered for this exact transaction (or
# generic/untagged-transaction templates within the same module) — NOTE the
# dict key here (e.g. "sales") is just this registry's own key and is
# unrelated to the SMS module code; all three sources below are hatchery
# transactions, so their SMS module is "hatchery".
# ``variables``: which SMS_VARIABLES this source actually fills with real data
# (generic ones — CompanyName/CurrentDate/CurrentTime/UserName — are implied).
# The template editor uses this to grey out variables that would render blank.
DOC_SOURCES = {
    "sales": {"label": "Chick Sale", "party_type": "customer",
              "model": ChickSale, "rows": _chick_sale_rows,
              "module": "hatchery", "transaction": "chick_sale",
              "variables": ("CustomerName", "InvoiceNo", "InvoiceDate", "Amount",
                            "Quantity", "Rate", "VehicleNo", "DriverName", "Warehouse")},
    "dispatch": {"label": "Delivery Challan", "party_type": "customer",
                 "model": DeliveryChallan, "rows": _delivery_challan_rows,
                 "module": "hatchery", "transaction": "delivery_challan",
                 "variables": ("CustomerName", "InvoiceNo", "InvoiceDate", "Amount",
                               "Quantity", "Rate", "Place", "VehicleNo", "DriverName",
                               "LRNo")},
    "purchase": {"label": "Egg Purchase", "party_type": "supplier",
                 "model": EggPurchase, "rows": _egg_purchase_rows,
                 "module": "hatchery", "transaction": "egg_purchase",
                 "variables": ("SupplierName", "InvoiceNo", "InvoiceDate", "Amount",
                               "Quantity", "Rate", "VehicleNo", "DriverName", "LRNo",
                               "Warehouse")},
}

# Always-available variables, filled from company profile / clock / session.
GENERIC_VARIABLE_KEYS = list(_GENERIC_KEYS)

# Transaction code -> variables its document source fills. Transactions with
# no registered source are absent, meaning "unknown — allow everything".
TRANSACTION_VARIABLES = {
    src["transaction"]: list(src["variables"])
    for src in DOC_SOURCES.values() if src.get("transaction")
}


# --- message metrics ------------------------------------------------------

GSM7_BASIC = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞ ÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑܧ¿abcdefghijklmnopqrstuvwxyzäöñüà"
    "^{}\\[~]|€"
)


def sms_metrics(message):
    """Return (char_count, sms_parts, is_unicode) using GSM-7/UCS-2 rules."""
    text = message or ""
    is_unicode = any(ch not in GSM7_BASIC for ch in text)
    length = len(text)
    if is_unicode:
        parts = 1 if length <= 70 else -(-length // 67)
    else:
        parts = 1 if length <= 160 else -(-length // 153)
    return length, max(parts, 1), is_unicode
