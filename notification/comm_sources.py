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


def _parse_date(value):
    """A YYYY-MM-DD string as a date, or None. The grid hands dates around as
    strings, and two sources need to compare rather than filter on them."""
    from django.utils.dateparse import parse_date

    return parse_date(value) if value else None


def _between(qs, from_date, to_date, field="date"):
    """The standard date-window narrowing every source does.

    Named because the field is not always ``date``: a batch is dated by its
    placement and a payment line by its voucher's day, and writing the filter
    out longhand in each source is how one of them ends up filtering nothing.
    """
    if from_date:
        qs = qs.filter(**{f"{field}__gte": from_date})
    if to_date:
        qs = qs.filter(**{f"{field}__lte": to_date})
    return qs


def _mobile(*candidates):
    """The first contact number that is actually there.

    Parties carry their number under several names — a customer has ``mobile``,
    a farmer ``mobile_no`` with ``mobile_2`` and a landline behind it, an
    employee a bare integer — and a row with no number is still worth showing
    so the sender can see who they cannot reach.
    """
    for c in candidates:
        text = str(c or "").strip()
        if text and text.lower() != "none":
            return text
    return ""


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


# --- broiler ---------------------------------------------------------------


def _bird_sale_rows(from_date, to_date, party_id):
    """Broiler liftings sold to a customer.

    Farmer-side liftings are a settlement rather than a sale to a party with a
    bill, so only the customer ones carry a document anybody would text about.
    """
    from broiler.models import BirdSale

    qs = (BirdSale.objects.filter(sale_type="customer", customer__isnull=False)
          .select_related("customer", "farm", "batch"))
    qs = _between(qs, from_date, to_date)
    if party_id:
        qs = qs.filter(customer_id=party_id)
    rows = []
    for bs in qs.order_by("-date", "-id"):
        weight = bs.net_weight or 0
        doc_no = bs.sale_no or bs.doc_no or ""
        rows.append(_base_row(
            doc_id=bs.id, date=bs.date, party_type="customer",
            party_id=bs.customer_id, party_name=bs.customer.name,
            mobile=_mobile(bs.customer.mobile, bs.customer.mobile_2),
            doc_no=doc_no, amount=bs.amount or 0,
            context={
                "CustomerName": bs.customer.name,
                "InvoiceNo": doc_no,
                "InvoiceDate": bs.date.strftime("%d-%m-%Y"),
                "Amount": f"{bs.amount or 0:,.2f}",
                "Quantity": "%g" % (bs.birds or 0),
                "Rate": f"{bs.rate or 0:,.2f}",
                "Weight": f"{weight:,.2f}",
                "VehicleNo": bs.vehicle or "", "DriverName": bs.driver or "",
                "Place": bs.lift_place or "",
            },
        ))
    return rows


def _bird_receipt_rows(from_date, to_date, party_id):
    """Money received against a bird sale.

    "Receipt" here is the payment, not the birds - the template registered for
    this transaction reads "Amount Rcvd Rs ... via ... Receipt No ...", which
    settles what the code was always meant to mean. Chicks arriving on a farm
    are a stock movement and appear under Stock Transfer.
    """
    from broiler.models import BirdSaleReceipt

    qs = (BirdSaleReceipt.objects
          .filter(sale_type="customer", customer__isnull=False)
          .select_related("customer"))
    qs = _between(qs, from_date, to_date)
    if party_id:
        qs = qs.filter(customer_id=party_id)
    rows = []
    for r in qs.order_by("-date", "-id"):
        amount = r.amount or 0
        rows.append(_base_row(
            doc_id=r.id, date=r.date, party_type="customer",
            party_id=r.customer_id, party_name=r.customer.name,
            mobile=_mobile(r.customer.mobile, r.customer.mobile_2),
            doc_no=r.receipt_no, amount=amount,
            context={
                "CustomerName": r.customer.name, "InvoiceNo": r.receipt_no,
                "ReceiptNo": r.receipt_no,
                "InvoiceDate": r.date.strftime("%d-%m-%Y"),
                "Amount": f"{amount:,.2f}", "PaidAmount": f"{amount:,.2f}",
                "PaymentMode": r.mode or "",
            },
        ))
    return rows


def _broiler_batch_rows(from_date, to_date, party_id):
    """A flock's placement, addressed to the farmer growing it."""
    from broiler.models import BroilerBatch

    qs = BroilerBatch.objects.select_related("broiler_farm__farmer",
                                             "broiler_farm__supervisor")
    qs = _between(qs, from_date, to_date, field="start_date")
    if party_id:
        qs = qs.filter(broiler_farm__farmer_id=party_id)
    rows = []
    for b in qs.order_by("-start_date", "-id"):
        farm = b.broiler_farm
        farmer = getattr(farm, "farmer", None)
        if farmer is None or b.start_date is None:
            continue
        doc_no = b.batch_name or b.lot_no or ""
        rows.append(_base_row(
            doc_id=b.id, date=b.start_date, party_type="farmer",
            party_id=farmer.id, party_name=farmer.farmer_name,
            mobile=_mobile(farmer.mobile_no, farmer.mobile_2, farmer.phone_no),
            doc_no=doc_no, amount=0,
            context={
                "InvoiceNo": doc_no,
                "InvoiceDate": b.start_date.strftime("%d-%m-%Y"),
                "Warehouse": farm.farm_name,
                "EmployeeName": getattr(farm.supervisor, "name", "") or "",
            },
        ))
    return rows


# --- sales -----------------------------------------------------------------


def _sales_invoice_rows(from_date, to_date, party_id):
    from sales.models import SalesInvoice

    qs = (SalesInvoice.objects.filter(is_active=True)
          .select_related("customer").prefetch_related("items"))
    qs = _between(qs, from_date, to_date)
    if party_id:
        qs = qs.filter(customer_id=party_id)
    rows = []
    for inv in qs.order_by("-date", "-id"):
        qty = inv.total_quantity() or 0
        net = inv.net_amount or 0
        rows.append(_base_row(
            doc_id=inv.id, date=inv.date, party_type="customer",
            party_id=inv.customer_id, party_name=inv.customer.name,
            mobile=_mobile(inv.customer.mobile, inv.customer.mobile_2),
            doc_no=inv.invoice_no, amount=net,
            context={
                "CustomerName": inv.customer.name, "InvoiceNo": inv.invoice_no,
                "InvoiceDate": inv.date.strftime("%d-%m-%Y"),
                "Amount": f"{net:,.2f}",
                "Quantity": "%g" % qty,
                "Rate": f"{net / qty:,.2f}" if qty else "",
                "VehicleNo": inv.vehicle_no or "",
                "Place": inv.place_of_supply or "",
                "LRNo": inv.eway_bill_no or "",
            },
        ))
    return rows


def _sales_receipt_rows(from_date, to_date, party_id):
    from sales.models import SalesReceipt

    qs = SalesReceipt.objects.select_related("customer")
    qs = _between(qs, from_date, to_date)
    if party_id:
        qs = qs.filter(customer_id=party_id)
    rows = []
    for r in qs.order_by("-date", "-id"):
        amount = r.amount or 0
        rows.append(_base_row(
            doc_id=r.id, date=r.date, party_type="customer",
            party_id=r.customer_id, party_name=r.customer.name,
            mobile=_mobile(r.customer.mobile, r.customer.mobile_2),
            doc_no=r.receipt_no, amount=amount,
            context={
                "CustomerName": r.customer.name, "InvoiceNo": r.receipt_no,
                "ReceiptNo": r.receipt_no,
                "InvoiceDate": r.date.strftime("%d-%m-%Y"),
                "Amount": f"{amount:,.2f}", "PaidAmount": f"{amount:,.2f}",
                "PaymentMode": r.mode or "",
            },
        ))
    return rows


def _customer_due_rows(from_date, to_date, party_id):
    """Customers who owe money, as at the "to" date.

    Not a document but a position, which is what a payment reminder is about.
    It calls the Customer Balance report's own row builder rather than
    re-deriving a balance, so a reminder and the report cannot hold two
    opinions about what somebody owes. The dates narrow the *as-on* date
    rather than a set of documents, so ``from_date`` has nothing to do here.
    """
    from sales.models import Customer
    from sales.views import _customer_balance_row

    # The report's builder works in dates, not the strings the grid passes
    # around, and silently comparing the two raises rather than misreporting.
    as_on = _parse_date(to_date)
    ref = as_on or timezone.localdate()
    qs = Customer.objects.order_by("name")
    if party_id:
        qs = qs.filter(id=party_id)
    rows = []
    for cust in qs:
        due = _customer_balance_row(cust, None, as_on, ref)["debit"]
        if not due:
            continue
        rows.append(_base_row(
            doc_id=cust.id, date=ref, party_type="customer",
            party_id=cust.id, party_name=cust.name,
            mobile=_mobile(cust.mobile, cust.mobile_2),
            doc_no=f"DUE-{cust.id}", amount=due,
            context={
                "CustomerName": cust.name,
                "InvoiceDate": ref.strftime("%d-%m-%Y"),
                "Amount": f"{due:,.2f}", "Outstanding": f"{due:,.2f}",
                "Balance": f"{due:,.2f}", "TotalDues": f"{due:,.2f}",
            },
        ))
    return rows


# --- purchase --------------------------------------------------------------


def _general_purchase_rows(from_date, to_date, party_id):
    from purchase.models import GeneralPurchase

    qs = GeneralPurchase.objects.select_related("supplier")
    qs = _between(qs, from_date, to_date)
    if party_id:
        qs = qs.filter(supplier_id=party_id)
    rows = []
    for gp in qs.order_by("-date", "-id"):
        net = gp.net_amount or 0
        rows.append(_base_row(
            doc_id=gp.id, date=gp.date, party_type="supplier",
            party_id=gp.supplier_id, party_name=gp.supplier.name,
            mobile=_mobile(gp.supplier.mobile, gp.supplier.mobile_2),
            doc_no=gp.purchase_no, amount=net,
            context={
                "SupplierName": gp.supplier.name, "InvoiceNo": gp.purchase_no,
                "InvoiceDate": gp.date.strftime("%d-%m-%Y"),
                "Amount": f"{net:,.2f}",
                "VehicleNo": gp.vehicle_no or "", "DriverName": gp.driver_name or "",
                "LRNo": gp.dc_no or "",
            },
        ))
    return rows


def _chicks_purchase_rows(from_date, to_date, party_id):
    from purchase.models import ChicksPurchase

    qs = ChicksPurchase.objects.select_related("supplier")
    qs = _between(qs, from_date, to_date)
    if party_id:
        qs = qs.filter(supplier_id=party_id)
    rows = []
    for cp in qs.order_by("-date", "-id"):
        net = cp.net_amount or 0
        rows.append(_base_row(
            doc_id=cp.id, date=cp.date, party_type="supplier",
            party_id=cp.supplier_id, party_name=cp.supplier.name,
            mobile=_mobile(cp.supplier.mobile, cp.supplier.mobile_2),
            doc_no=cp.purchase_no, amount=net,
            context={
                "SupplierName": cp.supplier.name, "InvoiceNo": cp.purchase_no,
                "InvoiceDate": cp.date.strftime("%d-%m-%Y"),
                "Amount": f"{net:,.2f}",
                "VehicleNo": cp.vehicle_no or "", "DriverName": cp.driver_name or "",
                "LRNo": cp.dc_no or "",
            },
        ))
    return rows


# --- account ---------------------------------------------------------------


def _supplier_payment_rows(from_date, to_date, party_id):
    """What was paid to a supplier, one row per payment line.

    The line and not the voucher: one voucher can pay several suppliers at
    once, and each of them is owed their own message about their own amount.
    """
    from purchase.models import SupplierPaymentLine

    qs = SupplierPaymentLine.objects.select_related("payment", "supplier")
    qs = _between(qs, from_date, to_date, field="payment__date")
    if party_id:
        qs = qs.filter(supplier_id=party_id)
    rows = []
    for line in qs.order_by("-payment__date", "-id"):
        pay, amount = line.payment, line.amount or 0
        rows.append(_base_row(
            doc_id=line.id, date=pay.date, party_type="supplier",
            party_id=line.supplier_id, party_name=line.supplier.name,
            mobile=_mobile(line.supplier.mobile, line.supplier.mobile_2),
            doc_no=pay.payment_no, amount=amount,
            context={
                "SupplierName": line.supplier.name, "InvoiceNo": pay.payment_no,
                "ReceiptNo": line.reference_no or pay.payment_no,
                "InvoiceDate": pay.date.strftime("%d-%m-%Y"),
                "Amount": f"{amount:,.2f}", "PaidAmount": f"{amount:,.2f}",
                "PaymentMode": line.mode or "",
            },
        ))
    return rows


def _supplier_due_rows(from_date, to_date, party_id):
    """Suppliers we owe, as at the "to" date - the payables mirror of
    ``_customer_due_rows``, and likewise the balance report's own arithmetic."""
    from purchase.models import Supplier
    from purchase.views import _supplier_balance_row

    as_on = _parse_date(to_date)
    ref = as_on or timezone.localdate()
    qs = Supplier.objects.order_by("name")
    if party_id:
        qs = qs.filter(id=party_id)
    rows = []
    for sup in qs:
        due = _supplier_balance_row(sup, None, as_on, ref)["credit"]
        if not due:
            continue
        rows.append(_base_row(
            doc_id=sup.id, date=ref, party_type="supplier",
            party_id=sup.id, party_name=sup.name,
            mobile=_mobile(sup.mobile, sup.mobile_2),
            doc_no=f"DUE-{sup.id}", amount=due,
            context={
                "SupplierName": sup.name,
                "InvoiceDate": ref.strftime("%d-%m-%Y"),
                "Amount": f"{due:,.2f}", "Outstanding": f"{due:,.2f}",
                "Balance": f"{due:,.2f}", "TotalDues": f"{due:,.2f}",
            },
        ))
    return rows


# --- inventory -------------------------------------------------------------


def _stock_transfer_rows(from_date, to_date, party_id):
    """Stock sent out to a farm - chicks, feed, medicine alike.

    The party is the farmer taking delivery, because a warehouse-to-warehouse
    move has nobody outside the company to tell. This is the only source that
    carries a chick placement: "Bird Receipt" is the money against a bird
    sale, not the birds arriving.
    """
    from inventory.models import StockTransfer

    qs = (StockTransfer.objects
          .filter(to_location_type="farm", to_farm__isnull=False)
          .select_related("to_farm__farmer", "item", "from_warehouse"))
    qs = _between(qs, from_date, to_date)
    if party_id:
        qs = qs.filter(to_farm__farmer_id=party_id)
    rows = []
    for st in qs.order_by("-date", "-id"):
        farmer = getattr(st.to_farm, "farmer", None)
        if farmer is None:
            continue
        qty = st.quantity or 0
        rate = st.rate or st.purchase_rate or 0
        doc_no = st.trnum or st.dc_no or ""
        rows.append(_base_row(
            doc_id=st.id, date=st.date, party_type="farmer",
            party_id=farmer.id, party_name=farmer.farmer_name,
            mobile=_mobile(farmer.mobile_no, farmer.mobile_2, farmer.phone_no),
            doc_no=doc_no, amount=qty * rate,
            context={
                "InvoiceNo": doc_no,
                "InvoiceDate": st.date.strftime("%d-%m-%Y"),
                "Amount": f"{qty * rate:,.2f}",
                "Quantity": "%g" % qty, "Rate": f"{rate:,.2f}",
                "VehicleNo": st.vehicle_no or "", "DriverName": st.driver_name or "",
                "LRNo": st.dc_no or "",
                "Warehouse": getattr(st.from_warehouse, "name", "") or "",
                "Place": st.to_farm.farm_name,
            },
        ))
    return rows


# --- HR --------------------------------------------------------------------


def _employee_row(*, doc_id, date, employee, doc_no, amount, extra=None):
    """One row addressed to a member of staff rather than a trading party."""
    name = employee.full_name or str(employee)
    return _base_row(
        doc_id=doc_id, date=date, party_type="employee",
        party_id=employee.id, party_name=name,
        mobile=_mobile(employee.personal_contact, employee.emergency_contact),
        doc_no=doc_no, amount=amount,
        context={
            "EmployeeName": name, "InvoiceNo": doc_no,
            "InvoiceDate": date.strftime("%d-%m-%Y"),
            "Amount": f"{amount:,.2f}" if amount else "",
            **(extra or {}),
        },
    )


def _attendance_rows(from_date, to_date, party_id):
    from hr.models import Attendance

    qs = Attendance.objects.select_related("employee")
    qs = _between(qs, from_date, to_date)
    if party_id:
        qs = qs.filter(employee_id=party_id)
    return [_employee_row(doc_id=a.id, date=a.date, employee=a.employee,
                          doc_no=f"ATT-{a.id}", amount=0,
                          extra={"Place": a.status or ""})
            for a in qs.order_by("-date", "-id") if a.employee_id]


def _leave_rows(from_date, to_date, party_id):
    from hr.models import EmployeeLeave

    qs = EmployeeLeave.objects.select_related("employee").prefetch_related("dates")
    qs = _between(qs, from_date, to_date, field="created_date__date")
    if party_id:
        qs = qs.filter(employee_id=party_id)
    rows = []
    for lv in qs.order_by("-created_date", "-id"):
        if not lv.employee_id:
            continue
        day = timezone.localtime(lv.created_date).date()
        rows.append(_employee_row(doc_id=lv.id, date=day, employee=lv.employee,
                                  doc_no=f"LV-{lv.id}", amount=0,
                                  extra={"Place": lv.status or "",
                                         "Quantity": str(lv.dates.count())}))
    return rows


def _payroll_rows(from_date, to_date, party_id):
    """A month's pay, dated to the month it is for rather than the day it ran."""
    from datetime import date as _date

    from hr.models import Payroll

    qs = Payroll.objects.select_related("employee")
    if party_id:
        qs = qs.filter(employee_id=party_id)
    lo, hi = _parse_date(from_date), _parse_date(to_date)
    rows = []
    for pr in qs.order_by("-year", "-month", "-id"):
        if not pr.employee_id or not pr.month or not pr.year:
            continue
        day = _date(int(pr.year), int(pr.month), 1)
        if (lo and day < lo.replace(day=1)) or (hi and day > hi):
            continue
        pay = pr.payable_salary or pr.net_salary or 0
        rows.append(_employee_row(
            doc_id=pr.id, date=day, employee=pr.employee,
            doc_no=f"PAY-{pr.year}-{int(pr.month):02d}-{pr.employee_id}",
            amount=pay,
            extra={"PaidAmount": f"{pay:,.2f}",
                   "Quantity": str(pr.total_working_days or "")}))
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
    # --- broiler ---
    "bird_sale": {"label": "Bird Sale", "party_type": "customer",
                  "model": None, "rows": _bird_sale_rows,
                  "module": "broiler", "transaction": "broiler_sale",
                  "variables": ("CustomerName", "InvoiceNo", "InvoiceDate", "Amount",
                                "Quantity", "Rate", "Weight", "VehicleNo", "DriverName",
                                "Place")},
    "bird_receipt": {"label": "Bird Receipt", "party_type": "customer",
                     "model": None, "rows": _bird_receipt_rows,
                     "module": "broiler", "transaction": "bird_receipt",
                     "variables": ("CustomerName", "InvoiceNo", "InvoiceDate", "Amount",
                                   "PaidAmount", "ReceiptNo", "PaymentMode")},
    "broiler_batch": {"label": "Broiler Batch", "party_type": "farmer",
                      "model": None, "rows": _broiler_batch_rows,
                      "module": "broiler", "transaction": "broiler_batch",
                      "variables": ("InvoiceNo", "InvoiceDate", "Warehouse",
                                    "EmployeeName")},
    # --- sales ---
    "sale_invoice": {"label": "Sale Invoice", "party_type": "customer",
                     "model": None, "rows": _sales_invoice_rows,
                     "module": "sales", "transaction": "sale_invoice",
                     "variables": ("CustomerName", "InvoiceNo", "InvoiceDate", "Amount",
                                   "Quantity", "Rate", "VehicleNo", "Place", "LRNo")},
    "sales_receipt": {"label": "Sales Receipt", "party_type": "customer",
                      "model": None, "rows": _sales_receipt_rows,
                      "module": "sales", "transaction": "payment_receipt",
                      "variables": ("CustomerName", "InvoiceNo", "InvoiceDate", "Amount",
                                    "PaidAmount", "ReceiptNo", "PaymentMode")},
    "customer_due": {"label": "Payment Due Reminder", "party_type": "customer",
                     "model": None, "rows": _customer_due_rows,
                     "module": "sales", "transaction": "payment_reminder",
                     "variables": ("CustomerName", "InvoiceDate", "Amount",
                                   "Outstanding", "Balance", "TotalDues")},
    # --- purchase ---
    "purchase_invoice": {"label": "Purchase Invoice", "party_type": "supplier",
                         "model": None, "rows": _general_purchase_rows,
                         "module": "purchase", "transaction": "purchase_invoice",
                         "variables": ("SupplierName", "InvoiceNo", "InvoiceDate",
                                       "Amount", "VehicleNo", "DriverName", "LRNo")},
    "chicks_purchase": {"label": "Chicks Purchase", "party_type": "supplier",
                        "model": None, "rows": _chicks_purchase_rows,
                        "module": "purchase", "transaction": "purchase_invoice",
                        "variables": ("SupplierName", "InvoiceNo", "InvoiceDate",
                                      "Amount", "VehicleNo", "DriverName", "LRNo")},
    # --- account ---
    "supplier_payment": {"label": "Supplier Payment", "party_type": "supplier",
                         "model": None, "rows": _supplier_payment_rows,
                         "module": "account", "transaction": "payment_receipt",
                         "variables": ("SupplierName", "InvoiceNo", "InvoiceDate",
                                       "Amount", "PaidAmount", "ReceiptNo",
                                       "PaymentMode")},
    "supplier_due": {"label": "Payment Due", "party_type": "supplier",
                     "model": None, "rows": _supplier_due_rows,
                     "module": "account", "transaction": "payment_due",
                     "variables": ("SupplierName", "InvoiceDate", "Amount",
                                   "Outstanding", "Balance", "TotalDues")},
    # --- inventory ---
    "stock_transfer": {"label": "Stock Transfer", "party_type": "farmer",
                       "model": None, "rows": _stock_transfer_rows,
                       "module": "inventory", "transaction": "stock_transfer",
                       "variables": ("InvoiceNo", "InvoiceDate", "Amount", "Quantity",
                                     "Rate", "VehicleNo", "DriverName", "LRNo",
                                     "Warehouse", "Place")},
    # --- HR ---
    "hr_attendance": {"label": "Attendance", "party_type": "employee",
                      "model": None, "rows": _attendance_rows,
                      "module": "hr", "transaction": "attendance",
                      "variables": ("EmployeeName", "InvoiceNo", "InvoiceDate",
                                    "Place")},
    "hr_leave": {"label": "Leave", "party_type": "employee",
                 "model": None, "rows": _leave_rows,
                 "module": "hr", "transaction": "leave",
                 "variables": ("EmployeeName", "InvoiceNo", "InvoiceDate", "Place",
                               "Quantity")},
    "hr_payroll": {"label": "Payroll", "party_type": "employee",
                   "model": None, "rows": _payroll_rows,
                   "module": "hr", "transaction": "payroll",
                   "variables": ("EmployeeName", "InvoiceNo", "InvoiceDate", "Amount",
                                 "PaidAmount", "Quantity")},
}

#: Party type -> (label, how to list them for the filter bar). The grid used to
#: know only customers and suppliers, because only hatchery documents fed it;
#: a farmer takes delivery of chicks and feed and a member of staff is paid,
#: and both are people the ERP has a number for. Each entry yields
#: (id, name) pairs, so the template renders one <select> per type and the
#: page shows whichever the chosen module asks for.
PARTY_TYPES = {
    "customer": "Customer",
    "supplier": "Supplier",
    "farmer": "Farmer",
    "employee": "Employee",
}


def party_choices(user=None):
    """(id, name) pairs per party type, scoped to what the user may see."""
    from broiler.models import Farmer
    from hr.models import Employee
    from purchase.models import Supplier
    from sales.models import Customer
    from user.services.scoping import customers_for, suppliers_for

    return {
        "customer": list(customers_for(user, Customer.objects.order_by("name"))
                         .values_list("id", "name")),
        "supplier": list(suppliers_for(user, Supplier.objects.order_by("name"))
                         .values_list("id", "name")),
        "farmer": list(Farmer.objects.order_by("farmer_name")
                       .values_list("id", "farmer_name")),
        "employee": [(e.id, e.full_name or f"Employee {e.employee_id}")
                     for e in Employee.objects.order_by("full_name")],
    }


# Always-available variables, filled from company profile / clock / session.
GENERIC_VARIABLE_KEYS = list(_GENERIC_KEYS)

# Transaction code -> variables its document source fills. Transactions with
# no registered source are absent, meaning "unknown — allow everything".
def _transaction_variables():
    """Transaction code -> every variable some source for it can fill.

    The union, not the last one registered. A transaction code is unique only
    within its module — "payment_receipt" is a customer receipt under Sales and
    a supplier payment under Account, and "purchase_invoice" has two documents
    behind it — so keying a plain comprehension by code alone quietly kept
    whichever source happened to be declared last and greyed out perfectly
    good variables in the template editor.
    """
    out = {}
    for src in DOC_SOURCES.values():
        code = src.get("transaction")
        if not code:
            continue
        known = out.setdefault(code, [])
        known.extend(v for v in src["variables"] if v not in known)
    return out


TRANSACTION_VARIABLES = _transaction_variables()


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
