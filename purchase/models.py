import re

from django.db import models
from django.utils.timezone import now
from inventory.models import ItemCategory, Item


class Supplier(models.Model):

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

    code = models.CharField(max_length=50, null=True, blank=True, help_text="Short supplier code")
    name = models.CharField(max_length=255, null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    place = models.CharField(max_length=100, null=True, blank=True)
    mobile = models.CharField(max_length=15, null=True, blank=True)
    mobile_2 = models.CharField(max_length=15, blank=True, null=True, help_text="Secondary mobile number")
    email = models.EmailField(blank=True, null=True, help_text="Email address")
    aadhar = models.CharField(max_length=20, blank=True, null=True, help_text="Aadhar number")
    contact_type = models.CharField(max_length=50, null=True, blank=True)
    party_category = models.CharField(
        max_length=20, choices=PartyCategory.choices, blank=True, null=True, help_text="Party category"
    )
    pan = models.CharField(max_length=20, null=True, blank=True)
    supplier_group = models.CharField(max_length=100, null=True, blank=True)
    gstin = models.CharField(max_length=15, null=True, blank=True)
    state = models.CharField(max_length=50, null=True, blank=True)
    credit_term = models.IntegerField(null=True, blank=True)
    credit_limit = models.DecimalField(
        max_digits=10, decimal_places=2, default=0.00, help_text="Credit limit in currency"
    )
    note = models.TextField(null=True, blank=True)
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
    agreement_copy = models.FileField(upload_to="supplier_documents/agreements/", blank=True, null=True)
    other_documents = models.FileField(upload_to="supplier_documents/other/", blank=True, null=True)

    @classmethod
    def next_code(cls):
        prefix = "SUP-"
        serials = []
        for code in cls.objects.filter(code__startswith=prefix).values_list("code", flat=True):
            match = re.match(r"^SUP-(\d+)$", code or "")
            if match:
                serials.append(int(match.group(1)))
        return f"{prefix}{max(serials, default=0) + 1:04d}"

    def save(self, *args, **kwargs):
        if self._state.adding and not self.code:
            self.code = self.next_code()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name or "Unnamed Supplier"


class SupplierShippingAddress(models.Model):
    """Reusable delivery/dispatch address belonging to a supplier."""
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name="shipping_addresses")
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
            models.UniqueConstraint(fields=["supplier", "label"], name="unique_supplier_shipping_address_label"),
        ]

    def __str__(self):
        return f"{self.supplier} - {self.label}"

class TaxMaster(models.Model):
    tax_code = models.CharField(max_length=50, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    tax_percentage = models.FloatField(null=True, blank=True)
    rule = models.CharField(max_length=50, null=True, blank=True)
    coa = models.CharField(max_length=100, null=True, blank=True)

    def __str__(self):
        return self.tax_code or "Unnamed Tax Code"

class VendorGroup(models.Model):
    code = models.CharField(max_length=50, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    currency = models.CharField(max_length=50, null=True, blank=True)
    control_account = models.ForeignKey(
        'account.ChartOfAccount', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='vendor_group_control_accounts',
        help_text="Control account from the chart of accounts",
    )
    prepayment_account = models.ForeignKey(
        'account.ChartOfAccount', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='vendor_group_prepayment_accounts',
        help_text="Prepayment account from the chart of accounts",
    )

    def __str__(self):
        return self.code or "Unnamed Vendor Group"


class CreditTerm(models.Model):
    term = models.CharField(verbose_name="Credit Term", max_length=50, unique=True)

    def __str__(self):
        return self.term

class PurchaseOrder(models.Model):
    date = models.DateField(verbose_name="Date", default=now)
    vendor = models.ForeignKey(
        VendorGroup,
        verbose_name="Vendor Name",
        on_delete=models.CASCADE,
        related_name="purchase_orders"
    )
    invoice = models.CharField(verbose_name="Invoice", max_length=100)
    book_invoice = models.CharField(verbose_name="Book Invoice", max_length=255, blank=True, null=True)
    dc_no = models.CharField(verbose_name="Dc No", max_length=100, blank=True, null=True)
    credit_term = models.ForeignKey(
        CreditTerm,
        verbose_name="Credit Term",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchase_orders"
    )
    item_tax = models.DecimalField(verbose_name="Item Tax", max_digits=10, decimal_places=2, default=0)

    calculation_based_on = models.CharField(
        verbose_name="Calculation Based On",
        max_length=255,
        choices=[("Sent Quantity", "Sent Quantity"), ("Received Quantity", "Received Quantity")],
        default="Sent Quantity"
    )
    basic_amount = models.DecimalField(verbose_name="Basic Amount", max_digits=10, decimal_places=2, default=0)
    broker_name = models.CharField(verbose_name="Broker Name", max_length=255, blank=True,
                                    null=True)
    vehicle_no = models.CharField(verbose_name="Vehicle No.", max_length=50, blank=True, null=True)
    total_amount = models.DecimalField(verbose_name="Total Amount", max_digits=10, decimal_places=2, default=0)
    driver_name = models.CharField(verbose_name="Driver Name", max_length=255, blank=True, null=True)
    freight = models.BooleanField(verbose_name="Freight Include", default=False)
    freight_amount = models.DecimalField(verbose_name="Freight Amount", max_digits=10, decimal_places=2, default=0)
    pay_later_via = models.CharField(verbose_name="Pay Later Via", max_length=255)  # Dropdown list
    tcs = models.CharField(verbose_name="TCS", max_length=255)
    tcs_percent = models.DecimalField(verbose_name="TCS %", max_digits=5, decimal_places=2, default=0)
    tcs_amount = models.DecimalField(verbose_name="TCS Amount", max_digits=10, decimal_places=2, default=0)
    grand_total = models.DecimalField(verbose_name="Grand Total", max_digits=10, decimal_places=2, default=0)
    round_off = models.DecimalField(verbose_name="Round Off", max_digits=10, decimal_places=2, default=0)
    round_off_type = models.CharField(
        verbose_name="Round Off Type",
        max_length=10,
        choices=[("Add", "Add"), ("Deduct", "Deduct")],
        default="Add"
    )
    net_total = models.DecimalField(verbose_name="Net Total", max_digits=10, decimal_places=2, default=0)
    narration = models.TextField(verbose_name="Narration", max_length=225, blank=True, null=True)

    def __str__(self):
        return f"Purchase Order - {self.invoice}"

class PurchaseOrderLineItem(models.Model):
    purchase_order = models.ForeignKey(PurchaseOrder, verbose_name="Purchase Order", on_delete=models.CASCADE, related_name="line_items")
    item_category = models.ForeignKey(
    'inventory.ItemCategory', on_delete=models.SET_NULL, blank=True, null=True, help_text="Item category"
    )
    item = models.ForeignKey(
        'inventory.Item', on_delete=models.SET_NULL, blank=True, null=True, help_text="Item"
    )
    units = models.CharField(verbose_name="Units", max_length=100, blank=True, null=True)
    price_per_unit = models.DecimalField(verbose_name="Price / Unit", max_digits=10, decimal_places=2, default=0)
    qty_sent = models.DecimalField(verbose_name="Qty Sent", max_digits=10, decimal_places=2, default=0)
    qty_received = models.DecimalField(verbose_name="Qty Received", max_digits=10, decimal_places=2, default=0)
    qty_free = models.DecimalField(verbose_name="Qty Free", max_digits=10, decimal_places=2, default=0)
    type = models.CharField(verbose_name="Type", max_length=100, blank=True, null=True)
    bags_or_boxes = models.CharField(verbose_name="Bags / Boxes", max_length=100, blank=True, null=True)
    weight = models.DecimalField(verbose_name="Weight", max_digits=10, decimal_places=2, default=0)
    discount_type = [
        ('percentage', 'Percentage'),
        ('amount', 'Amount'),
    ]
    vat = models.DecimalField(verbose_name="VAT (%)", max_digits=5, decimal_places=2, default=0)
    warehouse = models.CharField(verbose_name="Warehouse", max_length=100)
    flock = models.CharField(verbose_name="Flock", max_length=100, blank=True, null=True)
    sqft = models.DecimalField(verbose_name="Sqft", max_digits=10, decimal_places=2, default=0)
    sqft_per_chick = models.DecimalField(verbose_name="Sqft / Chicks", max_digits=10, decimal_places=2, default=0)

    def __str__(self):
        return f"Line Item {self.code} for {self.purchase_order.invoice}"

