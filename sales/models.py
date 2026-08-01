import re

from django.db import models
from purchase.models import VendorGroup, CreditTerm
from inventory.models import Item, ItemCategory
from Hitech_BIMS.storage_backends import private_media_storage





class CustomerGroup(models.Model):
    code = models.CharField(max_length=50, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    currency = models.CharField(max_length=50, null=True, blank=True)
    control_account = models.ForeignKey(
        'account.ChartOfAccount', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='customer_group_control_accounts',
        help_text="Control account from the chart of accounts",
    )
    advance_account = models.ForeignKey(
        'account.ChartOfAccount', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='customer_group_advance_accounts',
        help_text="Advance account from the chart of accounts",
    )


class SalesPriceMaster(models.Model):
    item_category = models.ForeignKey(
    'inventory.ItemCategory', on_delete=models.SET_NULL, blank=True, null=True, help_text="Item category"
)
    item = models.ForeignKey(
        'inventory.Item', on_delete=models.SET_NULL, blank=True, null=True, help_text="Item"
    )
    price = models.DecimalField(
        max_digits=10, decimal_places=2, help_text="Sales price of the item"
    )
    date = models.DateField(
        auto_now_add=True, help_text="Date of price entry"
    )

    def __str__(self):
        return f"{self.item} - {self.price}"



# Create your models here.
class Customer(models.Model):

    class ContactType(models.TextChoices):
        SUPPLIER = "Supplier", "Supplier"
        CUSTOMER = "Customer", "Customer"
        BOTH = "Supplier & Customer", "Supplier & Customer"

    class PartyCategory(models.TextChoices):
        RETAILER = "Retailer", "Retailer"
        WHOLESALER = "Wholesaler", "Wholesaler"
        DISTRIBUTOR = "Distributor", "Distributor"
        FARMER = "Farmer", "Farmer"
        OTHER = "Other", "Other"

    class ToPayToReceive(models.TextChoices):
        TO_PAY = "To Pay", "To Pay"
        TO_RECEIVE = "To Receive", "To Receive"

    code = models.CharField(max_length=50, blank=True, null=True, help_text="Short customer code")
    name = models.CharField(max_length=255, help_text="Full name of the contact")
    address = models.TextField(help_text="Billing address of the contact")
    place = models.CharField(max_length=255, blank=True, null=True, help_text="Place information")
    phone = models.CharField(max_length=15, unique=True, blank=True, null=True, help_text="Primary phone number")
    mobile = models.CharField(max_length=15, unique=True, help_text="SMS/WhatsApp number")
    mobile_2 = models.CharField(max_length=15, blank=True, null=True, help_text="Secondary mobile number")
    email = models.EmailField(blank=True, null=True, help_text="Email address")
    aadhar = models.CharField(max_length=20, blank=True, null=True, help_text="Aadhar number")
    # Managed through Picklist Master — see the note on party_category below.
    contact_type = models.CharField(
        max_length=50, default=ContactType.BOTH, help_text="Party type"
    )
    # Values are managed through Picklist Master (Users > Picklists), so no
    # hardcoded choices here — they would reject any list entry an admin adds.
    # PartyCategory/ContactType are kept as the seed for those picklists.
    party_category = models.CharField(
        max_length=50, blank=True, null=True, help_text="Party category"
    )
    pan_tin = models.CharField(max_length=50, blank=True, null=True, help_text="PAN/TIN number")
    customer_group = models.ForeignKey(
        CustomerGroup, on_delete=models.SET_NULL, blank=True, null=True, help_text="Customer group"
    )
    supplier_group = models.ForeignKey(
        VendorGroup, on_delete=models.SET_NULL, blank=True, null=True, help_text="Supplier group"
    )
    credit_limit = models.DecimalField(
        max_digits=10, decimal_places=2, default=0.00, help_text="Credit limit in currency"
    )
    credit_term = models.ForeignKey(
       CreditTerm, on_delete=models.SET_NULL, blank=True, null=True, help_text="Credit term"
    )
    credit_period = models.PositiveIntegerField(blank=True, null=True, help_text="Credit period in days")
    gstin = models.CharField(max_length=15, blank=True, null=True, help_text="GSTIN number")
    state = models.CharField(
        max_length=50,  blank=True, null=True, help_text="State of supply"
    )
    note = models.TextField(blank=True, null=True, help_text="Remarks")
    supplier_address = models.TextField(blank=True, null=True, help_text="Supplier address")
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True, help_text="Opening balance")
    to_pay_to_receive = models.CharField(max_length=20, choices=ToPayToReceive.choices, blank=True, null=True)
    as_on_date = models.DateField(blank=True, null=True, help_text="Opening balance as-on date")
    country = models.CharField(max_length=100, blank=True, null=True)
    currency = models.CharField(max_length=10, blank=True, null=True)
    account_no = models.CharField(max_length=50, blank=True, null=True, help_text="Bank account number")
    ifsc_code = models.CharField(max_length=20, blank=True, null=True)
    bank_details = models.TextField(blank=True, null=True)
    terms = models.TextField(blank=True, null=True, help_text="Terms and conditions")
    agreement_start_date = models.DateField(blank=True, null=True)
    agreement_months = models.PositiveIntegerField(blank=True, null=True)
    agreement_copy = models.FileField(upload_to="customer_documents/agreements/", storage=private_media_storage, blank=True, null=True)
    other_documents = models.FileField(upload_to="customer_documents/other/", storage=private_media_storage, blank=True, null=True)

    @classmethod
    def next_code(cls):
        prefix = "CUST-"
        serials = []
        for code in cls.objects.filter(code__startswith=prefix).values_list("code", flat=True):
            match = re.match(r"^CUST-(\d+)$", code or "")
            if match:
                serials.append(int(match.group(1)))
        return f"{prefix}{max(serials, default=0) + 1:04d}"

    def save(self, *args, **kwargs):
        if self._state.adding and not self.code:
            self.code = self.next_code()
        if not self.phone:
            self.phone = self.mobile
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class CustomerShippingAddress(models.Model):
    """Reusable delivery address belonging to a customer."""
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="shipping_addresses")
    label = models.CharField(max_length=100)
    address = models.TextField()
    contact_person = models.CharField(max_length=100, blank=True)
    mobile = models.CharField(max_length=15, blank=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_default", "label", "id"]
        constraints = [
            models.UniqueConstraint(fields=["customer", "label"], name="unique_customer_shipping_address_label"),
        ]

    def __str__(self):
        return f"{self.customer} - {self.label}"


# ---------------------------------------------------------------------------
# Sales Invoice (Sales > Transactions)
# ---------------------------------------------------------------------------
from django.utils.timezone import now as _now


class SalesInvoice(models.Model):
    """A Sales Invoice header with GST item lines (Sales > Transactions)."""

    TRANSACTION_TYPE_CHOICES = [
        ("Sales Invoice", "Sales Invoice"),
        ("Delivery Challan", "Delivery Challan"),
        ("Quotation", "Quotation"),
    ]

    invoice_no = models.CharField(max_length=30, unique=True, editable=False, blank=True,
                                  help_text="Auto-generated, e.g. INV-2627-0001")
    transaction_type = models.CharField(max_length=30, choices=TRANSACTION_TYPE_CHOICES,
                                        default="Sales Invoice")
    date = models.DateField(default=_now)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="sales_invoices")
    billing_address = models.TextField(blank=True)
    shipping_address = models.TextField(blank=True)
    gstin = models.CharField(max_length=20, blank=True)

    reference_no = models.CharField(max_length=100, blank=True)
    reference_date = models.DateField(null=True, blank=True)
    transportation = models.CharField(max_length=100, blank=True)
    vehicle_no = models.CharField(max_length=50, blank=True)
    place_of_supply = models.CharField(max_length=100, blank=True)
    eway_bill_no = models.CharField(max_length=50, blank=True)

    branch = models.ForeignKey("inventory.Warehouse", on_delete=models.SET_NULL, null=True, blank=True,
                               related_name="sales_invoices")
    organization_centre = models.ForeignKey("account.OrganizationCentre", on_delete=models.SET_NULL,
                                            null=True, blank=True, related_name="sales_invoices")
    sales_person = models.CharField(max_length=100, blank=True)
    payment_terms = models.CharField(max_length=50, blank=True)
    due_date = models.DateField(null=True, blank=True)
    remarks = models.TextField(blank=True)
    terms_conditions = models.ForeignKey("account.TermsConditions", on_delete=models.SET_NULL,
                                         null=True, blank=True, related_name="sales_invoices")
    bank_account = models.ForeignKey("account.BankCashMaster", on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name="sales_invoices")

    other_charges_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    round_off = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    net_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    print_bank_details = models.BooleanField(default=True, help_text="Print the company bank details on the invoice")

    created_by = models.ForeignKey("auth.User", on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="sales_invoices")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return self.invoice_no

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.invoice_no:
            self.invoice_no = self._next_no(self.date)
            super().save(update_fields=["invoice_no"])

    @classmethod
    def _next_no(cls, on_date=None):
        current = on_date or _now().date()
        start_year = current.year if current.month >= 4 else current.year - 1
        fy = f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"
        prefix = f"INV-{fy}-"
        max_num = 0
        for existing in cls.objects.filter(invoice_no__startswith=prefix).values_list("invoice_no", flat=True):
            m = re.match(rf"^{re.escape(prefix)}(\d+)$", existing or "")
            if m:
                max_num = max(max_num, int(m.group(1)))
        return f"{prefix}{max_num + 1:04d}"

    def _sum(self, field):
        return self.items.aggregate(t=models.Sum(field))["t"] or 0

    def total_items(self):
        return self.items.count()

    def total_quantity(self):
        return self._sum("quantity")

    def total_before_tax(self):
        return self._sum("taxable_amount")

    def total_gst(self):
        return self._sum("gst_amount")

    def compute_net_amount(self):
        from decimal import Decimal
        base = Decimal(str(self.total_before_tax())) + Decimal(str(self.total_gst()))
        base += Decimal(str(self.other_charges_amount or 0)) + Decimal(str(self.round_off or 0))
        return base


class SalesInvoiceItem(models.Model):
    """One GST line on a Sales Invoice."""
    invoice = models.ForeignKey(SalesInvoice, on_delete=models.CASCADE, related_name="items")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="sales_invoice_items")
    batch_no = models.CharField(max_length=100, blank=True)
    hsn_sac = models.CharField(max_length=20, blank=True)
    uom = models.CharField(max_length=50, blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    free_qty = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    rate = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    taxable_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    gst_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    gst_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.item.item_code} ({self.invoice.invoice_no})"


class SalesReceipt(models.Model):
    """A payment received from a customer against sales (Sales > Transactions >
    Receipt). Reduces that customer's outstanding balance — not tied to one
    specific Sales Invoice, mirroring the broiler Bird Sale / hatchery Chick
    Sale receipts."""

    MODE_CHOICES = [
        ('Cash', 'Cash'), ('Bank Transfer', 'Bank Transfer'),
        ('Cheque', 'Cheque'), ('UPI', 'UPI'), ('Card', 'Card'),
    ]

    receipt_no = models.CharField(max_length=30, unique=True, editable=False, blank=True,
                                  help_text="Auto-generated transaction number, e.g. SR-2627-0001")
    date = models.DateField(default=_now)
    location = models.ForeignKey('inventory.Warehouse', on_delete=models.PROTECT,
                                 related_name='sales_receipts', null=True, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='sales_receipts')

    mode = models.CharField(max_length=20, choices=MODE_CHOICES, default='Cash')
    receipt_account = models.ForeignKey('account.ChartOfAccount', on_delete=models.PROTECT,
                                        related_name='sales_receipts')
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    reference_no = models.CharField(max_length=100, blank=True)
    remarks = models.CharField(max_length=255, blank=True)

    created_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='sales_receipts')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Sales Receipt"
        verbose_name_plural = "Sales Receipts"
        ordering = ['-date', '-id']

    def __str__(self):
        return self.receipt_no

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.receipt_no:
            self.receipt_no = self._next_no(self.date)
            super().save(update_fields=["receipt_no"])

    @classmethod
    def _next_no(cls, on_date=None):
        current = on_date or _now().date()
        start_year = current.year if current.month >= 4 else current.year - 1
        fy = f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"
        prefix = f"SR-{fy}-"
        max_num = 0
        for existing in cls.objects.filter(receipt_no__startswith=prefix).values_list("receipt_no", flat=True):
            m = re.match(rf"^{re.escape(prefix)}(\d+)$", existing or "")
            if m:
                max_num = max(max_num, int(m.group(1)))
        return f"{prefix}{max_num + 1:04d}"

    @staticmethod
    def balance_due(customer_id, exclude_id=None):
        """Total sales-invoiced to this customer minus total sales receipts."""
        if not customer_id:
            return 0
        total_sold = (SalesInvoice.objects.filter(customer_id=customer_id, is_active=True)
                      .aggregate(t=models.Sum('net_amount'))['t'] or 0)
        rcpts = SalesReceipt.objects.filter(customer_id=customer_id)
        if exclude_id:
            rcpts = rcpts.exclude(id=exclude_id)
        total_received = rcpts.aggregate(t=models.Sum('amount'))['t'] or 0
        return total_sold - total_received


class CustomerNoteBase(models.Model):
    """Shared base for customer Debit / Credit Notes — a single-customer note
    with an amount, account and sector (Sales > Transactions). Entered a row at
    a time on a grid, so one screen can record several notes. Subclasses set
    NOTE_PREFIX for the auto number series.

    Mirrors purchase.SupplierNoteBase; the two are deliberately parallel so the
    sales and purchase sides of the same idea behave identically.
    """

    NOTE_PREFIX = "XN"

    note_no = models.CharField(max_length=30, unique=True, editable=False, blank=True,
                              help_text="Auto-generated, e.g. CDN-2627-0001 / CCN-2627-0001")
    date = models.DateField(default=_now)
    customer = models.ForeignKey("Customer", on_delete=models.PROTECT, related_name="%(class)ss")
    against_bill = models.CharField(max_length=50, blank=True,
                                    help_text="Related sales invoice / DC no.")
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    account = models.ForeignKey("account.ChartOfAccount", on_delete=models.SET_NULL, null=True,
                                blank=True, related_name="+")
    # "Sector" is the office/branch, the same meaning (and model) as
    # account.Voucher.sector, which the Journal screen labels
    # "Sector (Office / Branch)".
    sector = models.ForeignKey("inventory.Warehouse", on_delete=models.SET_NULL, null=True,
                               blank=True, related_name="+",
                               help_text="Office / branch this note belongs to")
    remarks = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["-date", "-id"]

    def __str__(self):
        return self.note_no or f"(unsaved {self.NOTE_PREFIX})"

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.note_no:
            self.note_no = self._next_no(self.date)
            super().save(update_fields=["note_no"])

    @classmethod
    def _next_no(cls, on_date=None):
        current_date = on_date or _now().date()
        start_year = current_date.year if current_date.month >= 4 else current_date.year - 1
        fy = f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"
        prefix = f"{cls.NOTE_PREFIX}-{fy}-"
        max_num = 0
        for existing in cls.objects.filter(note_no__startswith=prefix).values_list("note_no", flat=True):
            m = re.match(rf"^{re.escape(prefix)}(\d+)$", existing or "")
            if m:
                max_num = max(max_num, int(m.group(1)))
        return f"{prefix}{max_num + 1:04d}"


class CustomerDebitNote(CustomerNoteBase):
    """Debit note raised on a customer (rate difference, extra charge, etc.) —
    raises the receivable (Debit side) in the customer ledger."""
    NOTE_PREFIX = "CDN"


class CustomerCreditNote(CustomerNoteBase):
    """Credit note issued to a customer (sales return, discount allowed, etc.)
    — reduces the receivable (Credit side) in the customer ledger."""
    NOTE_PREFIX = "CCN"
