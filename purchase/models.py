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

class GeneralPurchase(models.Model):
    """Header record for a general (non-egg) supplier purchase transaction —
    feed, medicine, consumables etc. — with GST/discount line items, freight,
    TDS, other charges and bag/batch tracking (Purchase > Transactions)."""

    PAYMENT_TERMS_CHOICES = [
        ("Cash", "Cash"), ("Credit", "Credit"),
        ("Cheque", "Cheque"), ("Bank Transfer", "Bank Transfer"),
    ]
    CALC_BASIS_CHOICES = [
        ("Sent Quantity", "Sent Quantity"), ("Received Quantity", "Received Quantity"),
    ]
    FREIGHT_TYPE_CHOICES = [("Included in Bill", "Included in Bill"), ("Extra", "Extra")]
    PAYMENT_MODE_CHOICES = [("pay_later", "Pay Later"), ("pay_in_bill", "Pay In Bill")]
    OTHER_CHARGES_TYPE_CHOICES = [("Add", "Add"), ("Deduct", "Deduct")]
    ROUND_OFF_TYPE_CHOICES = [("Add", "Add"), ("Deduct", "Deduct")]
    BAG_TYPE_CHOICES = [("Jute Bag", "Jute Bag"), ("HDPE Bag", "HDPE Bag"), ("Loose", "Loose")]

    purchase_no = models.CharField(max_length=30, unique=True, editable=False, blank=True,
                                   help_text="Auto-generated transaction number, e.g. PIN-2627-0001")
    date = models.DateField(default=now)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="general_purchases")
    bill_no = models.CharField(max_length=100, blank=True)
    dc_no = models.CharField(max_length=100, blank=True)
    vehicle_no = models.CharField(max_length=50, blank=True)
    driver_name = models.CharField(max_length=100, blank=True)
    driver_mobile = models.CharField(max_length=20, blank=True)
    calculation_based_on = models.CharField(max_length=20, choices=CALC_BASIS_CHOICES, default="Sent Quantity")
    payment_terms = models.CharField(max_length=20, choices=PAYMENT_TERMS_CHOICES, default="Cash")

    freight_type = models.CharField(max_length=20, choices=FREIGHT_TYPE_CHOICES, default="Extra")
    payment_mode = models.CharField(max_length=15, choices=PAYMENT_MODE_CHOICES, default="pay_later")
    pay_account = models.ForeignKey("account.ChartOfAccount", on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="general_purchase_pay_accounts")
    freight_account = models.ForeignKey("account.ChartOfAccount", on_delete=models.SET_NULL, null=True, blank=True,
                                        related_name="general_purchase_freight_accounts")
    freight_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    bag_type = models.CharField(max_length=20, choices=BAG_TYPE_CHOICES, blank=True)
    no_of_bags = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    batch_no = models.CharField(max_length=100, blank=True)
    expiry_date = models.DateField(null=True, blank=True)

    tds_code = models.CharField(max_length=50, blank=True)
    tds_applicable = models.BooleanField(default=False)
    tds_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    other_charges_account = models.ForeignKey("account.ChartOfAccount", on_delete=models.SET_NULL, null=True, blank=True,
                                               related_name="general_purchase_other_charges_accounts")
    other_charges_type = models.CharField(max_length=10, choices=OTHER_CHARGES_TYPE_CHOICES, default="Add")
    other_charges_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    round_off_type = models.CharField(max_length=10, choices=ROUND_OFF_TYPE_CHOICES, default="Add")
    round_off = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    net_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    remarks = models.TextField(blank=True)
    reference_document_1 = models.FileField(upload_to="purchase/references/%Y/%m/", blank=True, null=True)
    reference_document_2 = models.FileField(upload_to="purchase/references/%Y/%m/", blank=True, null=True)
    reference_document_3 = models.FileField(upload_to="purchase/references/%Y/%m/", blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return self.purchase_no

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.purchase_no:
            self.purchase_no = self._next_purchase_no(self.date)
            super().save(update_fields=["purchase_no"])

    @classmethod
    def _next_purchase_no(cls, on_date=None):
        current_date = on_date or now().date()
        start_year = current_date.year if current_date.month >= 4 else current_date.year - 1
        fy = f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"
        prefix = f"PIN-{fy}-"
        max_num = 0
        for existing in cls.objects.filter(purchase_no__startswith=prefix).values_list("purchase_no", flat=True):
            match = re.match(rf"^{re.escape(prefix)}(\d+)$", existing or "")
            if match:
                max_num = max(max_num, int(match.group(1)))
        return f"{prefix}{max_num + 1:04d}"

    def gross_amount(self):
        return self.items.aggregate(total=models.Sum("amount"))["total"] or 0

    def total_quantity(self):
        field = "rcv_qty" if self.calculation_based_on == "Received Quantity" else "sent_qty"
        return self.items.aggregate(total=models.Sum(field))["total"] or 0

    def avg_rate(self):
        qty = self.total_quantity()
        return round(self.gross_amount() / qty, 2) if qty else 0

    def freight_included_amount(self):
        base = self.gross_amount()
        return base + (self.freight_amount if self.freight_type == "Included in Bill" else 0)

    def other_charges_signed(self):
        return -self.other_charges_amount if self.other_charges_type == "Deduct" else self.other_charges_amount

    def round_off_signed(self):
        return -self.round_off if self.round_off_type == "Deduct" else self.round_off

    def compute_net_amount(self):
        """Sets ``round_off``/``round_off_type`` to whatever nudges the
        pre-round total to the nearest whole rupee, then returns that total
        as the net amount — round off is auto, never user-entered."""
        tds = self.tds_amount if self.tds_applicable else 0
        pre_round = self.freight_included_amount() + self.other_charges_signed() - tds
        rounded = round(pre_round)
        diff = rounded - pre_round
        if diff < 0:
            self.round_off_type, self.round_off = "Deduct", -diff
        else:
            self.round_off_type, self.round_off = "Add", diff
        return rounded

    def item_names(self):
        return ", ".join(self.items.values_list("item__item_code", flat=True))


class GeneralPurchaseItem(models.Model):
    """One item row within a General Purchase."""
    purchase = models.ForeignKey(GeneralPurchase, on_delete=models.CASCADE, related_name="items")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="general_purchase_items")
    unit = models.CharField(max_length=50, blank=True)
    sent_qty = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    rcv_qty = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    free_qty = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    rate = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gst_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    farm_warehouse = models.ForeignKey("inventory.Warehouse", on_delete=models.PROTECT,
                                       related_name="general_purchase_items")

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.item} ({self.purchase.purchase_no})"

    def effective_qty(self):
        basis = self.purchase.calculation_based_on if self.purchase_id else "Sent Quantity"
        return self.rcv_qty if basis == "Received Quantity" else self.sent_qty

    def save(self, *args, **kwargs):
        qty = self.effective_qty()
        subtotal = (qty * self.rate) * (1 - self.discount_percent / 100) - self.discount_amount
        self.amount = subtotal * (1 + self.gst_percent / 100)
        super().save(*args, **kwargs)




class ChicksPurchase(models.Model):
    """Header for a day-old chicks purchase from a hatchery — one item per
    transaction, received in one or more batch rows with their own
    mortality/shortage/weak-chick reconciliation (Purchase > Transactions)."""

    FREIGHT_TYPE_CHOICES = [("Included in Bill", "Included in Bill"), ("Extra", "Extra")]
    PAYMENT_MODE_CHOICES = [("pay_later", "Pay Later"), ("pay_in_bill", "Pay In Bill")]
    OTHER_CHARGES_TYPE_CHOICES = [("Add", "Add"), ("Deduct", "Deduct")]
    ROUND_OFF_TYPE_CHOICES = [("Add", "Add"), ("Deduct", "Deduct")]
    BAG_TYPE_CHOICES = [("Jute Bag", "Jute Bag"), ("HDPE Bag", "HDPE Bag"), ("Loose", "Loose")]

    purchase_no = models.CharField(max_length=30, unique=True, editable=False, blank=True,
                                   help_text="Auto-generated transaction number, e.g. CPR-2627-0001")
    date = models.DateField(default=now)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="chicks_purchases")
    hatchery = models.ForeignKey("hatchery_master.Hatchery", on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="chicks_purchases")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="chicks_purchases")
    bill_no = models.CharField(max_length=100, blank=True)
    dc_no = models.CharField(max_length=100, blank=True)
    vehicle_no = models.CharField(max_length=50, blank=True)
    driver_name = models.CharField(max_length=100, blank=True)

    freight_type = models.CharField(max_length=20, choices=FREIGHT_TYPE_CHOICES, default="Extra")
    payment_mode = models.CharField(max_length=15, choices=PAYMENT_MODE_CHOICES, default="pay_later")
    pay_account = models.ForeignKey("account.ChartOfAccount", on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="chicks_purchase_pay_accounts")
    freight_account = models.ForeignKey("account.ChartOfAccount", on_delete=models.SET_NULL, null=True, blank=True,
                                        related_name="chicks_purchase_freight_accounts")
    freight_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    bag_type = models.CharField(max_length=20, choices=BAG_TYPE_CHOICES, blank=True)
    no_of_bags = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    batch_no = models.CharField(max_length=100, blank=True)
    expiry_date = models.DateField(null=True, blank=True)

    tds_code = models.CharField(max_length=50, blank=True)
    tds_applicable = models.BooleanField(default=False)
    tds_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    other_charges_account = models.ForeignKey("account.ChartOfAccount", on_delete=models.SET_NULL, null=True, blank=True,
                                               related_name="chicks_purchase_other_charges_accounts")
    other_charges_type = models.CharField(max_length=10, choices=OTHER_CHARGES_TYPE_CHOICES, default="Add")
    other_charges_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    round_off_type = models.CharField(max_length=10, choices=ROUND_OFF_TYPE_CHOICES, default="Add")
    round_off = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    net_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    remarks = models.TextField(blank=True)
    reference_document_1 = models.FileField(upload_to="purchase/references/%Y/%m/", blank=True, null=True)
    reference_document_2 = models.FileField(upload_to="purchase/references/%Y/%m/", blank=True, null=True)
    reference_document_3 = models.FileField(upload_to="purchase/references/%Y/%m/", blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return self.purchase_no

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.purchase_no:
            self.purchase_no = self._next_purchase_no(self.date)
            super().save(update_fields=["purchase_no"])

    @classmethod
    def _next_purchase_no(cls, on_date=None):
        current_date = on_date or now().date()
        start_year = current_date.year if current_date.month >= 4 else current_date.year - 1
        fy = f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"
        prefix = f"CPR-{fy}-"
        max_num = 0
        for existing in cls.objects.filter(purchase_no__startswith=prefix).values_list("purchase_no", flat=True):
            match = re.match(rf"^{re.escape(prefix)}(\d+)$", existing or "")
            if match:
                max_num = max(max_num, int(match.group(1)))
        return f"{prefix}{max_num + 1:04d}"

    def gross_amount(self):
        return self.items.aggregate(total=models.Sum("amount"))["total"] or 0

    def total_quantity(self):
        return self.items.aggregate(total=models.Sum("total_qty"))["total"] or 0

    def avg_rate(self):
        qty = self.total_quantity()
        return round(self.gross_amount() / qty, 2) if qty else 0

    def freight_included_amount(self):
        base = self.gross_amount()
        return base + (self.freight_amount if self.freight_type == "Included in Bill" else 0)

    def other_charges_signed(self):
        return -self.other_charges_amount if self.other_charges_type == "Deduct" else self.other_charges_amount

    def round_off_signed(self):
        return -self.round_off if self.round_off_type == "Deduct" else self.round_off

    def compute_net_amount(self):
        """Sets ``round_off``/``round_off_type`` to whatever nudges the
        pre-round total to the nearest whole rupee, then returns that total
        as the net amount — round off is auto, never user-entered."""
        tds = self.tds_amount if self.tds_applicable else 0
        pre_round = self.freight_included_amount() + self.other_charges_signed() - tds
        rounded = round(pre_round)
        diff = rounded - pre_round
        if diff < 0:
            self.round_off_type, self.round_off = "Deduct", -diff
        else:
            self.round_off_type, self.round_off = "Add", diff
        return rounded


class ChicksPurchaseItem(models.Model):
    """One batch/lot row within a Chicks Purchase — the header carries a
    single Item; each row reconciles that batch's sent vs received chicks.

    Rcv Qty = Sent Qty + (Sent Free% of Sent Qty) - Mortality - Shortage
    - Weaks + Excess Qty — the physically received count, which already
    includes the free chicks. Total Qty (the chargeable/billable quantity
    Amount is based on) is then Rcv Qty backed out by the Received Free% —
    Rcv Qty / (1 + Rcv Free%) — mirroring how Chick Sale derives its billed
    qty from a discount-inclusive sale qty. Free Qty is the remainder:
    Rcv Qty - Total Qty. Sent Free% and Rcv Free% are independent — the form
    defaults Rcv Free% from Sent Free% as it's typed, but either can be
    edited on its own (e.g. a different confirmed free% on arrival).
    """
    purchase = models.ForeignKey(ChicksPurchase, on_delete=models.CASCADE, related_name="items")
    sent_qty = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sent_free_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0,
                                            help_text="Free % applied to Sent Qty when deriving Rcv Qty")
    rcv_free_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0,
                                           help_text="Free % backed out of Rcv Qty to get the chargeable Total Qty")
    mortality = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    shortage = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    weaks = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    excess_qty = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    rcv_qty = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    free_qty = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    total_qty = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    rate = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    farm_warehouse = models.ForeignKey("inventory.Warehouse", on_delete=models.PROTECT,
                                       related_name="chicks_purchase_items")
    batch = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"Batch {self.batch or self.id} ({self.purchase.purchase_no})"

    def save(self, *args, **kwargs):
        free_from_sent = round(self.sent_qty * self.sent_free_percent / 100)
        self.rcv_qty = (self.sent_qty + free_from_sent - self.mortality
                        - self.shortage - self.weaks + self.excess_qty)
        if self.rcv_free_percent:
            self.total_qty = round(self.rcv_qty / (1 + self.rcv_free_percent / 100))
        else:
            self.total_qty = self.rcv_qty
        self.free_qty = self.rcv_qty - self.total_qty
        self.amount = self.total_qty * self.rate
        super().save(*args, **kwargs)



class SupplierPayment(models.Model):
    """Header for a multi-supplier payment voucher — one or more allocation
    lines (supplier/mode/account/amount), each line free to pay a different
    supplier, against a single date/location (Purchase > Transactions)."""

    payment_no = models.CharField(max_length=30, unique=True, editable=False, blank=True,
                                  help_text="Auto-generated transaction number, e.g. PAY-2627-0001")
    date = models.DateField(default=now)
    location = models.ForeignKey("inventory.Warehouse", on_delete=models.PROTECT,
                                 related_name="supplier_payments")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return self.payment_no

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.payment_no:
            self.payment_no = self._next_payment_no(self.date)
            super().save(update_fields=["payment_no"])

    @classmethod
    def _next_payment_no(cls, on_date=None):
        current_date = on_date or now().date()
        start_year = current_date.year if current_date.month >= 4 else current_date.year - 1
        fy = f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"
        prefix = f"PAY-{fy}-"
        max_num = 0
        for existing in cls.objects.filter(payment_no__startswith=prefix).values_list("payment_no", flat=True):
            match = re.match(rf"^{re.escape(prefix)}(\d+)$", existing or "")
            if match:
                max_num = max(max_num, int(match.group(1)))
        return f"{prefix}{max_num + 1:04d}"

    def total_amount(self):
        return self.lines.aggregate(total=models.Sum("amount"))["total"] or 0

    def total_bank_charges(self):
        return self.lines.aggregate(total=models.Sum("bank_charges"))["total"] or 0

    def _line_summary(self, field):
        values = list(self.lines.values_list(field, flat=True))
        distinct = list(dict.fromkeys(v for v in values if v))
        if not distinct:
            return ""
        return distinct[0] if len(distinct) == 1 else "Multiple"

    def mode_summary(self):
        return self._line_summary("mode")

    def supplier_summary(self):
        names = list(dict.fromkeys(self.lines.values_list("supplier__name", flat=True)))
        names = [n for n in names if n]
        if not names:
            return ""
        return names[0] if len(names) == 1 else "Multiple"

    def method_summary(self):
        names = list(dict.fromkeys(self.lines.values_list("pay_account__description", flat=True)))
        names = [n for n in names if n]
        if not names:
            return ""
        return names[0] if len(names) == 1 else "Multiple"


class SupplierPaymentLine(models.Model):
    """One allocation line within a supplier payment voucher."""
    MODE_CHOICES = [
        ("Cash", "Cash"), ("Bank Transfer", "Bank Transfer"),
        ("Cheque", "Cheque"), ("UPI", "UPI"), ("Card", "Card"),
    ]

    payment = models.ForeignKey(SupplierPayment, on_delete=models.CASCADE, related_name="lines")
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="payment_lines")
    mode = models.CharField(max_length=20, choices=MODE_CHOICES, default="Cash")
    pay_account = models.ForeignKey("account.ChartOfAccount", on_delete=models.PROTECT,
                                    related_name="supplier_payment_lines")
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    bank_charges = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    reference_no = models.CharField(max_length=100, blank=True)
    remarks = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.mode} {self.amount} ({self.payment.payment_no})"
