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
from hatchery.models import ChickSale, ChickSaleReceipt, DeliveryChallan, EggGrading, EggPurchase, TraySettingLine
from Hitech_BIMS.entry_dates import date_from_query


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
    # Broiler documents carry more than the first set could name.
    "FarmName": "Farm name",
    "BatchName": "Batch / flock name",
    "FarmerName": "Farmer who grew the birds",
    "SupervisorName": "Supervisor on the document",
    "BranchName": "Branch name",
    "Birds": "Number of birds",
    "NetWeight": "Net weight (Kg)",
    "AvgWeight": "Average weight per bird (Kg)",
    "DocNo": "Document number entered on the sale",
    "SaleNo": "Sale number",
    "Remarks": "Remarks on the document",
    "ReferenceNo": "Payment reference (cheque / UPI / transaction id)",
    "PaymentAccount": "Bank / cash account the payment went into",
    "BreedName": "Breed",
    "LotNo": "Lot number",
    "BookNumber": "Book number",
    "BillNo": "Supplier's bill number",
    "DcNo": "Delivery challan number on the document",
    "DriverMobile": "Driver mobile number",
    "TransporterName": "Transporter name",
    "EwayBillNo": "E-way bill number",
    "FreightAmount": "Freight amount",
    "ItemName": "Item name",
    "BatchNo": "Batch number (stock)",
    "DueDate": "Payment due date",
    "AttendanceStatus": "Attendance status (Present / Absent / ...)",
    "CheckInTime": "Check-in time",
    "CheckOutTime": "Check-out time",
    "LeaveType": "Leave type",
    "LeaveStatus": "Leave status",
    "Month": "Month the pay is for (MM-YYYY)",
    "GrossSalary": "Gross salary",
    "NetSalary": "Net salary",
    "Deductions": "Salary deductions",
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
    strings, and two sources need to compare rather than filter on them.

    Shares the ERP's one reading of a date out of a query string, which also
    answers None for a string shaped like a date that cannot exist —
    "2026-02-30" — rather than raising ValueError into a report page.
    """
    from Hitech_BIMS.entry_dates import date_from_query

    return date_from_query(value)


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
              doc_no, amount, context, location_id=None):
    """One row of the transaction grid.

    ``location_id`` is where the document belongs, as a typed key -- "w:16"
    for a Warehouse, "b:2" for a Branch, "h:2" for a Hatchery. It is carried
    on the row rather than filtered inside each builder because the twenty
    sources spell their location eight different ways, and three of them
    file against a master that is not a Warehouse at all.

    The type prefix is what lets those three join the same filter. Branch,
    Hatchery and Warehouse are separate masters with no keys between them --
    they overlap only by name, and not completely -- so a bare integer would
    make Branch 2 and Warehouse 2 indistinguishable and quietly mis-file
    rows. Prefixing keeps each master's ids in their own namespace, and the
    dropdown offers them as separate labelled groups.

    A source with no location at all passes None, which ``LOCATION_SOURCES``
    below is what actually decides on.
    """
    return {
        "doc_id": doc_id, "date": date.isoformat(),
        "party_type": party_type, "party_id": party_id,
        "party_name": party_name, "mobile": mobile or "",
        "doc_no": doc_no, "amount": str(amount),
        "location_id": location_id,
        "context": {**DEFAULT_CONTEXT, **context},
    }


def _wh(pk):
    """Typed key for a Warehouse id, or None."""
    return f"w:{pk}" if pk else None


def _branch(pk):
    """Typed key for a Branch id, or None."""
    return f"b:{pk}" if pk else None


def _hatchery(pk):
    """Typed key for a Hatchery id, or None."""
    return f"h:{pk}" if pk else None


def _chick_sale_rows(from_date, to_date, party_id, doc_id=None, doc_ids=None):
    qs = (ChickSale.objects.select_related("customer", "warehouse", "delivery_challan")
          .prefetch_related("items__item"))
    if from_date:
        qs = qs.filter(date__gte=date_from_query(from_date))
    if to_date:
        qs = qs.filter(date__lte=date_from_query(to_date))
    if party_id:
        qs = qs.filter(customer_id=party_id)
    # One or several documents, for a button on the sale itself.
    if doc_id is not None:
        qs = qs.filter(pk=doc_id)
    if doc_ids is not None:
        qs = qs.filter(pk__in=list(doc_ids))
    rows = []
    for cs in qs.order_by("-date", "-id"):
        rows.append(_base_row(
            location_id=_wh(cs.warehouse_id),
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
                "PaymentMode": cs.payment_mode or "",
                "FreightAmount": f"{cs.freight_amount or 0:,.2f}",
                "Remarks": cs.remarks or "",
                "DcNo": cs.delivery_challan.challan_no if cs.delivery_challan_id else "",
            },
        ))
    return rows


def _chick_sale_receipt_rows(from_date, to_date, party_id, doc_id=None, doc_ids=None):
    """Money received against a chick sale — the hatchery counterpart of
    Bird Receipt. "Receipt" here is the payment, not the chicks; the chicks
    leaving is the Chick Sale row itself."""
    from sales.views import customer_balance_timelines, customer_balance_as_of

    qs = ChickSaleReceipt.objects.select_related("customer", "location", "receipt_account")
    qs = _between(qs, from_date, to_date)
    if party_id:
        qs = qs.filter(customer_id=party_id)
    # One or several documents, for a button on the receipt itself.
    if doc_id is not None:
        qs = qs.filter(pk=doc_id)
    if doc_ids is not None:
        qs = qs.filter(pk__in=list(doc_ids))
    receipts = list(qs.order_by("-date", "-id"))
    timelines = customer_balance_timelines({r.customer_id for r in receipts})

    rows = []
    for r in receipts:
        amount = r.amount or 0
        due = customer_balance_as_of(timelines[r.customer_id], r.date)["debit"]
        rows.append(_base_row(
            location_id=_wh(r.location_id),
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
                "Outstanding": f"{due:,.2f}", "Balance": f"{due:,.2f}",
                "TotalDues": f"{due:,.2f}",
                "ReferenceNo": r.reference_no or "",
                "PaymentAccount": (f"{r.receipt_account.code} - {r.receipt_account.description}"
                                   if r.receipt_account_id else ""),
                "Warehouse": r.location.name if r.location_id else "",
                "Remarks": r.remarks or "",
            },
        ))
    return rows


def _delivery_challan_rows(from_date, to_date, party_id, doc_id=None, doc_ids=None):
    qs = DeliveryChallan.objects.select_related("customer", "warehouse").prefetch_related("items")
    if from_date:
        qs = qs.filter(date__gte=date_from_query(from_date))
    if to_date:
        qs = qs.filter(date__lte=date_from_query(to_date))
    if party_id:
        qs = qs.filter(customer_id=party_id)
    # One or several documents, for a button on the challan itself.
    if doc_id is not None:
        qs = qs.filter(pk=doc_id)
    if doc_ids is not None:
        qs = qs.filter(pk__in=list(doc_ids))
    rows = []
    for dc in qs.order_by("-date", "-id"):
        qty = dc.total_quantity()
        # Weighted average rate across items (single-item challans get that
        # item's effective rate).
        rate = (sum((i.amount or 0) for i in dc.items.all()) / qty) if qty else 0
        rows.append(_base_row(
            location_id=_wh(dc.warehouse_id),
            doc_id=dc.id, date=dc.date, party_type="customer",
            party_id=dc.customer_id, party_name=dc.customer.name,
            mobile=dc.customer.mobile, doc_no=dc.challan_no, amount=dc.grand_total(),
            context={
                "CustomerName": dc.customer.name, "SupplierName": "",
                "InvoiceNo": dc.challan_no, "InvoiceDate": dc.date.strftime("%d-%m-%Y"),
                "Amount": f"{dc.grand_total():,.2f}", "Outstanding": "", "PaidAmount": "",
                "Balance": "", "VehicleNo": dc.vehicle_no or "", "DriverName": dc.driver_name or "",
                "LRNo": dc.transport_document_no or "",
                "Warehouse": dc.warehouse.name if dc.warehouse_id else "", "EmployeeName": "",
                "DriverMobile": dc.driver_mobile or "",
                "TransporterName": dc.transporter_name or "",
                "EwayBillNo": dc.eway_bill_no or "",
                "Quantity": '%g' % qty, "Rate": f"{rate:,.2f}",
                "Place": dc.place_of_supply or "",
            },
        ))
    return rows


def _egg_purchase_rows(from_date, to_date, party_id):
    qs = EggPurchase.objects.select_related("supplier", "warehouse").prefetch_related("items")
    if from_date:
        qs = qs.filter(date__gte=date_from_query(from_date))
    if to_date:
        qs = qs.filter(date__lte=date_from_query(to_date))
    if party_id:
        qs = qs.filter(supplier_id=party_id)
    rows = []
    for ep in qs.order_by("-date", "-id"):
        rows.append(_base_row(
            location_id=_wh(ep.warehouse_id),
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
                "DcNo": ep.dc_no or "", "PaymentMode": ep.payment_mode or "",
                "FreightAmount": f"{ep.freight_amount or 0:,.2f}",
                "Remarks": ep.remarks or "",
            },
        ))
    return rows


def _egg_grading_rows(from_date, to_date, party_id):
    qs = EggGrading.objects.select_related("supplier", "storage_location", "item")
    qs = _between(qs, from_date, to_date)
    if party_id:
        qs = qs.filter(supplier_id=party_id)
    rows = []
    for eg in qs.order_by("-date", "-id"):
        rows.append(_base_row(
            location_id=_wh(eg.storage_location_id),
            doc_id=eg.id, date=eg.date, party_type="supplier",
            party_id=eg.supplier_id, party_name=eg.supplier.name,
            mobile=_mobile(eg.supplier.mobile, eg.supplier.mobile_2),
            doc_no=eg.transaction_no, amount=0,
            context={
                "SupplierName": eg.supplier.name, "InvoiceNo": eg.transaction_no,
                "InvoiceDate": eg.date.strftime("%d-%m-%Y"),
                "Quantity": '%g' % eg.eggs_to_stock(),
                "Warehouse": eg.storage_location.name,
                "ItemName": eg.item.description if eg.item_id else "",
            },
        ))
    return rows


def _tray_setting_rows(from_date, to_date, party_id):
    """One row per setter-machine load, addressed to the supplier whose eggs
    went into it — a tray setting header can span several suppliers (each
    line picks its own, and the field is optional), so the line and not the
    header is what carries one party's own message, the same shape
    ``_supplier_payment_rows`` already uses for a multi-party voucher."""
    qs = (TraySettingLine.objects.filter(supplier__isnull=False)
          .select_related("tray_setting__grading", "supplier"))
    qs = _between(qs, from_date, to_date, field="tray_setting__setting_date")
    if party_id:
        qs = qs.filter(supplier_id=party_id)
    rows = []
    for line in qs.order_by("-tray_setting__setting_date", "-id"):
        ts = line.tray_setting
        rows.append(_base_row(
            # A tray setting has no warehouse of its own; it takes the one
            # the eggs were graded into, which is where the trays are.
            location_id=_wh(ts.grading.storage_location_id if ts.grading_id else None),
            doc_id=line.id, date=ts.setting_date, party_type="supplier",
            party_id=line.supplier_id, party_name=line.supplier.name,
            mobile=_mobile(line.supplier.mobile, line.supplier.mobile_2),
            doc_no=ts.setting_no, amount=0,
            context={
                "SupplierName": line.supplier.name, "InvoiceNo": ts.setting_no,
                "InvoiceDate": ts.setting_date.strftime("%d-%m-%Y"),
                "Quantity": '%g' % (line.eggs_set or 0),
            },
        ))
    return rows


# --- broiler ---------------------------------------------------------------


def _bird_sale_rows(from_date, to_date, party_id, doc_id=None, doc_ids=None):
    """Broiler liftings sold to a customer.

    Farmer-side liftings are a settlement rather than a sale to a party with a
    bill, so only the customer ones carry a document anybody would text about.
    """
    from broiler.models import BirdSale

    qs = (BirdSale.objects.filter(sale_type="customer", customer__isnull=False)
          .select_related("customer", "farm__branch", "farm__farmer", "batch",
                          "lifting_supervisor"))
    qs = _between(qs, from_date, to_date)
    if party_id:
        qs = qs.filter(customer_id=party_id)
    # One document, for a button on the sale itself: a single lookup rather
    # than building every sale in the register to pick one out.
    if doc_id is not None:
        qs = qs.filter(pk=doc_id)
    if doc_ids is not None:
        qs = qs.filter(pk__in=list(doc_ids))
    from sales.views import customer_balance_timelines, customer_balance_as_of

    sales = list(qs.order_by("-date", "-id"))
    timelines = customer_balance_timelines({b.customer_id for b in sales})
    rows = []
    for bs in sales:
        weight = bs.net_weight or 0
        doc_no = bs.sale_no or bs.doc_no or ""
        due = customer_balance_as_of(timelines[bs.customer_id], bs.date)["debit"]
        farm = bs.farm if bs.farm_id else None
        rows.append(_base_row(
            # A bird sale happens at a farm, and a farm belongs to a Branch
            # rather than to a Warehouse -- so it filters by its Branch, in
            # the dropdown's Branches group.
            location_id=_branch(bs.farm.branch_id if bs.farm_id else None),
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
                "FarmName": farm.farm_name if farm else "",
                "BatchName": bs.batch.batch_name if bs.batch_id else "",
                "FarmerName": (farm.farmer.farmer_name
                               if farm and farm.farmer_id else ""),
                # The lifting supervisor is an HR employee, or a name typed in by
                # hand when the person is not on the register -- as the register
                # itself shows it.
                "SupervisorName": (str(bs.lifting_supervisor) if bs.lifting_supervisor_id
                                   else (bs.lifting_supervisor_other or "")),
                "BranchName": (farm.branch.branch_name
                               if farm and farm.branch_id else ""),
                "Birds": "%g" % (bs.birds or 0),
                "NetWeight": f"{weight:,.2f}",
                "AvgWeight": f"{bs.avg_weight or 0:,.2f}",
                "DocNo": bs.doc_no or "", "SaleNo": bs.sale_no or "",
                "Remarks": bs.remarks or "",
                "Outstanding": f"{due:,.2f}", "Balance": f"{due:,.2f}",
                "TotalDues": f"{due:,.2f}",
            },
        ))
    return rows


def _bird_receipt_rows(from_date, to_date, party_id, doc_id=None, doc_ids=None):
    """Money received against a bird sale.

    "Receipt" here is the payment, not the birds - the template registered for
    this transaction reads "Amount Rcvd Rs ... via ... Receipt No ...", which
    settles what the code was always meant to mean. Chicks arriving on a farm
    are a stock movement and appear under Stock Transfer.
    """
    from broiler.models import BirdSaleReceipt
    from sales.views import customer_balance_timelines, customer_balance_as_of

    qs = (BirdSaleReceipt.objects
          .filter(sale_type="customer", customer__isnull=False)
          .select_related("customer", "location", "receipt_account"))
    qs = _between(qs, from_date, to_date)
    if party_id:
        qs = qs.filter(customer_id=party_id)
    # One or several documents, for a button on the receipt itself.
    if doc_id is not None:
        qs = qs.filter(pk=doc_id)
    if doc_ids is not None:
        qs = qs.filter(pk__in=list(doc_ids))
    receipts = list(qs.order_by("-date", "-id"))
    timelines = customer_balance_timelines({r.customer_id for r in receipts})

    rows = []
    for r in receipts:
        amount = r.amount or 0
        due = customer_balance_as_of(timelines[r.customer_id], r.date)["debit"]
        rows.append(_base_row(
            location_id=_wh(r.location_id),
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
                "Outstanding": f"{due:,.2f}", "Balance": f"{due:,.2f}",
                "TotalDues": f"{due:,.2f}",
                "ReferenceNo": r.reference_no or "",
                "PaymentAccount": (f"{r.receipt_account.code} - {r.receipt_account.description}"
                                   if r.receipt_account_id else ""),
                "Warehouse": r.location.name if r.location_id else "",
                "Remarks": r.remarks or "",
            },
        ))
    return rows


def _broiler_batch_rows(from_date, to_date, party_id):
    """A flock's placement, addressed to the farmer growing it."""
    from broiler.models import BroilerBatch

    qs = BroilerBatch.objects.select_related("broiler_farm__farmer",
                                             "broiler_farm__supervisor",
                                             "broiler_farm__branch", "breed")
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
            location_id=_branch(farm.branch_id if farm else None),
            doc_id=b.id, date=b.start_date, party_type="farmer",
            party_id=farmer.id, party_name=farmer.farmer_name,
            mobile=_mobile(farmer.mobile_no, farmer.mobile_2, farmer.phone_no),
            doc_no=doc_no, amount=0,
            context={
                "InvoiceNo": doc_no,
                "InvoiceDate": b.start_date.strftime("%d-%m-%Y"),
                "Warehouse": farm.farm_name,
                "EmployeeName": getattr(farm.supervisor, "name", "") or "",
                "FarmName": farm.farm_name,
                "BatchName": b.batch_name or "",
                "FarmerName": farmer.farmer_name,
                "SupervisorName": getattr(farm.supervisor, "name", "") or "",
                "BranchName": getattr(farm.branch, "branch_name", "") or "",
                "BreedName": getattr(b.breed, "description", "") or "",
                "LotNo": b.lot_no or "",
                "BookNumber": str(b.book_number or ""),
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
            location_id=_wh(inv.branch_id),
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
                "ReferenceNo": inv.reference_no or "",
                "EwayBillNo": inv.eway_bill_no or "",
                "DueDate": inv.due_date.strftime("%d-%m-%Y") if inv.due_date else "",
                "Remarks": inv.remarks or "",
            },
        ))
    return rows


def _sales_receipt_rows(from_date, to_date, party_id):
    from sales.models import SalesReceipt
    from sales.views import customer_balance_timelines, customer_balance_as_of

    qs = SalesReceipt.objects.select_related("customer", "location", "receipt_account")
    qs = _between(qs, from_date, to_date)
    if party_id:
        qs = qs.filter(customer_id=party_id)
    receipts = list(qs.order_by("-date", "-id"))
    timelines = customer_balance_timelines({r.customer_id for r in receipts})

    rows = []
    for r in receipts:
        amount = r.amount or 0
        due = customer_balance_as_of(timelines[r.customer_id], r.date)["debit"]
        rows.append(_base_row(
            location_id=_wh(r.location_id),
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
                "Outstanding": f"{due:,.2f}", "Balance": f"{due:,.2f}",
                "TotalDues": f"{due:,.2f}",
                "ReferenceNo": r.reference_no or "",
                "PaymentAccount": (f"{r.receipt_account.code} - {r.receipt_account.description}"
                                   if r.receipt_account_id else ""),
                "Warehouse": r.location.name if r.location_id else "",
                "Remarks": r.remarks or "",
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

    qs = GeneralPurchase.objects.select_related("supplier").prefetch_related("items")
    qs = _between(qs, from_date, to_date)
    if party_id:
        qs = qs.filter(supplier_id=party_id)
    rows = []
    for gp in qs.order_by("-date", "-id"):
        net = gp.net_amount or 0
        # The warehouse lives on the lines, not the header. A purchase whose
        # lines land in more than one takes none: a single branch value
        # cannot honestly stand for a document that went to two, and the
        # filter would otherwise claim it belongs to whichever line came
        # first. Prefetched above, so this reads no extra query per row.
        line_warehouses = {i.farm_warehouse_id for i in gp.items.all()
                           if i.farm_warehouse_id}
        rows.append(_base_row(
            location_id=_wh(line_warehouses.pop() if len(line_warehouses) == 1 else None),
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
                "BillNo": gp.bill_no or "", "DcNo": gp.dc_no or "",
                "DriverMobile": gp.driver_mobile or "",
                "PaymentMode": gp.payment_mode or "",
                "FreightAmount": f"{gp.freight_amount or 0:,.2f}",
                "BatchNo": gp.batch_no or "", "Remarks": gp.remarks or "",
            },
        ))
    return rows


def _chicks_purchase_rows(from_date, to_date, party_id):
    from purchase.models import ChicksPurchase

    qs = ChicksPurchase.objects.select_related("supplier", "hatchery", "item")
    qs = _between(qs, from_date, to_date)
    if party_id:
        qs = qs.filter(supplier_id=party_id)
    rows = []
    for cp in qs.order_by("-date", "-id"):
        net = cp.net_amount or 0
        rows.append(_base_row(
            # Chicks are bought into a hatchery, its own master again.
            location_id=_hatchery(cp.hatchery_id),
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
                "BillNo": cp.bill_no or "", "DcNo": cp.dc_no or "",
                "PaymentMode": cp.payment_mode or "",
                "FreightAmount": f"{cp.freight_amount or 0:,.2f}",
                "BatchNo": cp.batch_no or "", "Remarks": cp.remarks or "",
                "ItemName": cp.item.description if cp.item_id else "",
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

    qs = SupplierPaymentLine.objects.select_related("payment__location", "supplier", "pay_account")
    qs = _between(qs, from_date, to_date, field="payment__date")
    if party_id:
        qs = qs.filter(supplier_id=party_id)
    rows = []
    for line in qs.order_by("-payment__date", "-id"):
        pay, amount = line.payment, line.amount or 0
        rows.append(_base_row(
            location_id=_wh(pay.location_id),
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
                "ReferenceNo": line.reference_no or "",
                "PaymentAccount": (f"{line.pay_account.code} - {line.pay_account.description}"
                                   if line.pay_account_id else ""),
                "Remarks": line.remarks or "",
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
          .select_related("to_farm__farmer", "item", "from_warehouse", "to_batch"))
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
            # These rows are warehouse-to-farm by definition (the queryset
            # filters to_location_type="farm"), so the warehouse end is the
            # only one a branch filter can match on -- "either end" has just
            # the one end here.
            location_id=_wh(st.from_warehouse_id),
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
                "DcNo": st.dc_no or "", "Remarks": st.remarks or "",
                "ItemName": st.item.description if st.item_id else "",
                "FarmName": st.to_farm.farm_name,
                "BatchName": st.to_batch.batch_name if st.to_batch_id else "",
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
        # Attendance, Leave and Payroll have no branch of their own; the
        # person does. Set once here, since all three go through this helper.
        location_id=_wh(employee.warehouse_id),
        context={
            "EmployeeName": name, "InvoiceNo": doc_no,
            "InvoiceDate": date.strftime("%d-%m-%Y"),
            "Amount": f"{amount:,.2f}" if amount else "",
            **(extra or {}),
        },
    )


def _hm(value):
    """A time of day as HH:MM, whether the column holds a time or a datetime."""
    if not value:
        return ""
    if hasattr(value, "tzinfo") and getattr(value, "tzinfo", None) is not None:
        value = timezone.localtime(value)
    return value.strftime("%H:%M") if hasattr(value, "strftime") else str(value)


def _attendance_rows(from_date, to_date, party_id):
    from hr.models import Attendance

    qs = Attendance.objects.select_related("employee__warehouse")
    qs = _between(qs, from_date, to_date)
    if party_id:
        qs = qs.filter(employee_id=party_id)
    return [_employee_row(doc_id=a.id, date=a.date, employee=a.employee,
                          doc_no=f"ATT-{a.id}", amount=0,
                          extra={"Place": a.status or "",
                                 "AttendanceStatus": a.status or "",
                                 "CheckInTime": _hm(a.check_in_time),
                                 "CheckOutTime": _hm(a.check_out_time),
                                 "Remarks": a.remarks or ""})
            for a in qs.order_by("-date", "-id") if a.employee_id]


def _leave_rows(from_date, to_date, party_id):
    from hr.models import EmployeeLeave

    qs = EmployeeLeave.objects.select_related("employee__warehouse").prefetch_related("selected_dates")
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
                                         "Quantity": str(len(lv.selected_dates.all())),
                                         "LeaveType": str(lv.leave_type or ""),
                                         "LeaveStatus": lv.status or ""}))
    return rows


def _payroll_rows(from_date, to_date, party_id):
    """A month's pay, dated to the month it is for rather than the day it ran."""
    from datetime import date as _date

    from hr.models import Payroll

    qs = Payroll.objects.select_related("employee__warehouse")
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
                   "Quantity": str(pr.total_working_days or ""),
                   "Month": f"{int(pr.month):02d}-{pr.year}",
                   "GrossSalary": f"{pr.gross_salary or 0:,.2f}",
                   "NetSalary": f"{pr.net_salary or 0:,.2f}",
                   "Deductions": f"{pr.deductions or 0:,.2f}"}))
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
              # Offers a Send button on the sale itself (see document_row).
              "by_id": True,
              "module": "hatchery", "transaction": "chick_sale",
              "variables": ("CustomerName", "InvoiceNo", "InvoiceDate", "Amount",
                            "Quantity", "Rate", "VehicleNo", "DriverName", "Warehouse",
                            "PaymentMode", "FreightAmount", "Remarks", "DcNo")},
    "chick_receipt": {"label": "Chick Receipt", "party_type": "customer",
                      "model": ChickSaleReceipt, "rows": _chick_sale_receipt_rows,
                      # Offers a Send button on the receipt itself.
                      "by_id": True,
                      "module": "hatchery", "transaction": "chick_receipt",
                      "variables": ("CustomerName", "InvoiceNo", "InvoiceDate", "Amount",
                                    "PaidAmount", "ReceiptNo", "PaymentMode",
                                    "Outstanding", "Balance", "TotalDues",
                                    "ReferenceNo", "PaymentAccount", "Warehouse",
                                    "Remarks")},
    "dispatch": {"label": "Delivery Challan", "party_type": "customer",
                 "model": DeliveryChallan, "rows": _delivery_challan_rows,
                 # Offers a Send button on the challan itself.
                 "by_id": True,
                 "module": "hatchery", "transaction": "delivery_challan",
                 "variables": ("CustomerName", "InvoiceNo", "InvoiceDate", "Amount",
                               "Quantity", "Rate", "Place", "VehicleNo", "DriverName",
                               "LRNo", "Warehouse", "DriverMobile", "TransporterName",
                               "EwayBillNo")},
    "purchase": {"label": "Egg Purchase", "party_type": "supplier",
                 "model": EggPurchase, "rows": _egg_purchase_rows,
                 "module": "hatchery", "transaction": "egg_purchase",
                 "variables": ("SupplierName", "InvoiceNo", "InvoiceDate", "Amount",
                               "Quantity", "Rate", "VehicleNo", "DriverName", "LRNo",
                               "Warehouse", "DcNo", "PaymentMode", "FreightAmount",
                               "Remarks")},
    "egg_grading": {"label": "Egg Grading", "party_type": "supplier",
                    "model": EggGrading, "rows": _egg_grading_rows,
                    "module": "hatchery", "transaction": "egg_grading",
                    "variables": ("SupplierName", "InvoiceNo", "InvoiceDate",
                                  "Quantity", "Warehouse", "ItemName")},
    "tray_set": {"label": "Tray Set", "party_type": "supplier",
                "model": TraySettingLine, "rows": _tray_setting_rows,
                "module": "hatchery", "transaction": "tray_set",
                "variables": ("SupplierName", "InvoiceNo", "InvoiceDate", "Quantity")},
    # --- broiler ---
    "bird_sale": {"label": "Bird Sale", "party_type": "customer",
                  "model": None, "rows": _bird_sale_rows,
                  # Offers a Send button on the sale itself: see document_row
                  # and document_visible_to below.
                  "by_id": True,
                  "module": "broiler", "transaction": "broiler_sale",
                  "variables": ("CustomerName", "InvoiceNo", "InvoiceDate", "Amount",
                                "Quantity", "Rate", "Weight", "VehicleNo", "DriverName",
                                "Place", "FarmName", "BatchName", "FarmerName",
                                "SupervisorName", "BranchName", "Birds", "NetWeight",
                                "AvgWeight", "DocNo", "SaleNo", "Remarks",
                                "Outstanding", "Balance", "TotalDues")},
    "bird_receipt": {"label": "Bird Receipt", "party_type": "customer",
                     "model": None, "rows": _bird_receipt_rows,
                     # Offers a Send button on the receipt itself.
                     "by_id": True,
                     "module": "broiler", "transaction": "bird_receipt",
                     "variables": ("CustomerName", "InvoiceNo", "InvoiceDate", "Amount",
                                   "PaidAmount", "ReceiptNo", "PaymentMode",
                                   "Outstanding", "Balance", "TotalDues",
                                   "ReferenceNo", "PaymentAccount", "Warehouse",
                                   "Remarks")},
    "broiler_batch": {"label": "Broiler Batch", "party_type": "farmer",
                      "model": None, "rows": _broiler_batch_rows,
                      "module": "broiler", "transaction": "broiler_batch",
                      "variables": ("InvoiceNo", "InvoiceDate", "Warehouse",
                                    "EmployeeName", "FarmName", "BatchName",
                                    "FarmerName", "SupervisorName", "BranchName",
                                    "BreedName", "LotNo", "BookNumber")},
    # --- sales ---
    "sale_invoice": {"label": "Sale Invoice", "party_type": "customer",
                     "model": None, "rows": _sales_invoice_rows,
                     "module": "sales", "transaction": "sale_invoice",
                     "variables": ("CustomerName", "InvoiceNo", "InvoiceDate", "Amount",
                                   "Quantity", "Rate", "VehicleNo", "Place", "LRNo",
                                   "ReferenceNo", "EwayBillNo", "DueDate", "Remarks")},
    "sales_receipt": {"label": "Sales Receipt", "party_type": "customer",
                      "model": None, "rows": _sales_receipt_rows,
                      "module": "sales", "transaction": "payment_receipt",
                      "variables": ("CustomerName", "InvoiceNo", "InvoiceDate", "Amount",
                                    "PaidAmount", "ReceiptNo", "PaymentMode",
                                    "Outstanding", "Balance", "TotalDues",
                                    "ReferenceNo", "PaymentAccount", "Warehouse",
                                    "Remarks")},
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
                                       "Amount", "VehicleNo", "DriverName", "LRNo",
                                       "BillNo", "DcNo", "DriverMobile", "PaymentMode",
                                       "FreightAmount", "BatchNo", "Remarks")},
    "chicks_purchase": {"label": "Chicks Purchase", "party_type": "supplier",
                        "model": None, "rows": _chicks_purchase_rows,
                        "module": "purchase", "transaction": "purchase_invoice",
                        "variables": ("SupplierName", "InvoiceNo", "InvoiceDate",
                                      "Amount", "VehicleNo", "DriverName", "LRNo",
                                      "BillNo", "DcNo", "PaymentMode", "FreightAmount",
                                      "BatchNo", "Remarks", "ItemName")},
    # --- account ---
    "supplier_payment": {"label": "Supplier Payment", "party_type": "supplier",
                         "model": None, "rows": _supplier_payment_rows,
                         "module": "account", "transaction": "payment_receipt",
                         "variables": ("SupplierName", "InvoiceNo", "InvoiceDate",
                                       "Amount", "PaidAmount", "ReceiptNo",
                                       "PaymentMode", "ReferenceNo", "PaymentAccount",
                                       "Remarks")},
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
                                     "Warehouse", "Place", "DcNo", "Remarks",
                                     "ItemName", "FarmName", "BatchName")},
    # --- HR ---
    "hr_attendance": {"label": "Attendance", "party_type": "employee",
                      "model": None, "rows": _attendance_rows,
                      "module": "hr", "transaction": "attendance",
                      "variables": ("EmployeeName", "InvoiceNo", "InvoiceDate",
                                    "Place", "AttendanceStatus", "CheckInTime",
                                    "CheckOutTime", "Remarks")},
    "hr_leave": {"label": "Leave", "party_type": "employee",
                 "model": None, "rows": _leave_rows,
                 "module": "hr", "transaction": "leave",
                 "variables": ("EmployeeName", "InvoiceNo", "InvoiceDate", "Place",
                               "Quantity", "LeaveType", "LeaveStatus")},
    "hr_payroll": {"label": "Payroll", "party_type": "employee",
                   "model": None, "rows": _payroll_rows,
                   "module": "hr", "transaction": "payroll",
                   "variables": ("EmployeeName", "InvoiceNo", "InvoiceDate", "Amount",
                                 "PaidAmount", "Quantity", "Month", "GrossSalary",
                                 "NetSalary", "Deductions")},
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


# The sources that can answer a Branch/Location filter, i.e. whose rows
# resolve to a Warehouse. The field is spelled five different ways across
# them, which is why the resolution happens in each builder and lands on the
# row as ``location_id`` rather than being derived here.
#
# The page greys the filter out for anything not named here, rather than
# offering a control that quietly changes nothing: a filter that appears to
# work and does not is worse than one that is plainly unavailable.
#
# Not here, and why: customer_due and supplier_due are a balance as at a
# date rather than a document, so there is no one place they happened.
# Everything else resolves, including the three that file against a master
# other than Warehouse -- they take their own master's ids under a different
# type prefix instead of being translated into a warehouse they have no key
# to.
LOCATION_SOURCES = frozenset({
    "sales",            # Chick Sale       -> warehouse
    "chick_receipt",    # Chick Receipt    -> location
    "dispatch",         # Delivery Challan -> warehouse
    "purchase",         # Egg Purchase     -> warehouse
    "bird_receipt",     # Bird Receipt     -> location
    "sale_invoice",     # Sale Invoice     -> branch
    "sales_receipt",    # Sales Receipt    -> location
    "egg_grading",      # Egg Grading      -> storage_location
    "stock_transfer",   # Stock Transfer   -> from_warehouse (always farm-bound)
    "hr_attendance",    # Attendance       -> employee.warehouse
    "hr_leave",         # Leave            -> employee.warehouse
    "hr_payroll",       # Payroll          -> employee.warehouse
    "tray_set",         # Tray Set         -> grading.storage_location
    "purchase_invoice", # General Purchase -> items.farm_warehouse (if one)
    "supplier_payment", # Supplier Payment -> payment.location
    "bird_sale",        # Bird Sale        -> farm.branch        (Branch)
    "broiler_batch",    # Broiler Batch    -> farm.branch        (Branch)
    "chicks_purchase",  # Chicks Purchase  -> hatchery           (Hatchery)
})


def document_row(module, doc_id):
    """The one grid row for a single document, or None.

    A source that can look a document up by id says so (``by_id``) and is asked
    for just that one; the rest build their whole register and have the
    document picked out, as the bulk screen always has.
    """
    source = DOC_SOURCES.get(module)
    if not source:
        return None
    if source.get("by_id"):
        rows = source["rows"](None, None, None, doc_id=doc_id)
    else:
        rows = source["rows"](None, None, None)
    return next((r for r in rows if str(r["doc_id"]) == str(doc_id)), None)


def document_visible_to(module, doc_id, user):
    """May this user see this document at all?

    The register a person reads is narrowed to their own branches and farms; a
    button that messaged a customer about a sale outside that narrowing would
    be a way round it. Sources with no such narrowing answer True.
    """
    if module == "bird_sale":
        from broiler.models import BirdSale
        from broiler.views import _scope_rows

        return _scope_rows(user, BirdSale.objects.filter(pk=doc_id)).exists()
    return True


def document_rows(module, doc_ids):
    """The grid rows for several documents at once (sources that look up by id)."""
    source = DOC_SOURCES.get(module)
    if not source or not source.get("by_id"):
        return []
    return source["rows"](None, None, None, doc_ids=list(doc_ids))


def visible_document_ids(module, doc_ids, user):
    """Of these documents, the ids this user may see -- the several-at-once form
    of document_visible_to."""
    if module == "bird_sale":
        from broiler.models import BirdSale
        from broiler.views import _scope_rows

        return set(_scope_rows(user, BirdSale.objects.filter(pk__in=list(doc_ids)))
                   .values_list("pk", flat=True))
    return {int(i) for i in doc_ids}


def location_choices():
    """The Branch/Location filter's options, as [(group label, [(key, name)])].

    Three masters, kept apart rather than merged: Warehouse, Branch (what a
    broiler farm belongs to) and Hatchery. They carry no keys to each other
    and overlap only by name -- "AKBARPUR BRANCH" exists as both a Branch and
    a Warehouse as separate records, while VARANASI BRANCH has no warehouse
    at all -- so translating between them would mis-file rows the first time
    one is renamed. The keys are typed ("w:16", "b:2", "h:2") so each
    master's ids stay in their own namespace.
    """
    from broiler.models import Branch, BroilerFarm
    from hatchery_master.models import Hatchery
    from inventory.models import Warehouse

    groups = [("Warehouses", [(f"w:{i}", n) for i, n in
                              Warehouse.objects.order_by("name")
                              .values_list("id", "name")])]

    # Only the branches that actually have a farm: a branch with none can
    # never match a row, and an option that always returns nothing reads as
    # a broken filter.
    farm_branches = set(BroilerFarm.objects.filter(branch__isnull=False)
                        .values_list("branch_id", flat=True))
    branches = [(f"b:{b.pk}", str(b)) for b in Branch.objects.order_by("branch_name")
                if b.pk in farm_branches]
    if branches:
        groups.append(("Branches (farms)", branches))

    hatcheries = [(f"h:{h.pk}", str(h))
                  for h in Hatchery.objects.order_by("hatchery_name")]
    if hatcheries:
        groups.append(("Hatcheries", hatcheries))
    return groups


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


def resolve_party_by_mobile(mobile):
    """Best-effort (party_type, name) for a bare mobile number, by matching
    against Customer/Supplier/Farmer -- for display contexts (e.g. the
    WhatsApp Conversations contact list) where a message log row was
    created without a party already attached (a free-text service-message
    reply logs only the phone number, not who it belongs to). Matches on
    the last 10 digits so a stored +91-prefixed MSISDN still matches a
    bare 10-digit number in the party tables, or the other way round.
    Returns (None, "") if no party table has this number."""
    from broiler.models import Farmer
    from purchase.models import Supplier
    from sales.models import Customer

    digits = "".join(ch for ch in str(mobile) if ch.isdigit())[-10:]
    if not digits:
        return None, ""

    customer = Customer.objects.filter(mobile__endswith=digits).values_list("name", flat=True).first()
    if customer:
        return "customer", customer
    supplier = Supplier.objects.filter(mobile__endswith=digits).values_list("name", flat=True).first()
    if supplier:
        return "supplier", supplier
    farmer = Farmer.objects.filter(phone_no__endswith=digits).values_list("farmer_name", flat=True).first()
    if farmer:
        return "farmer", farmer
    return None, ""


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
