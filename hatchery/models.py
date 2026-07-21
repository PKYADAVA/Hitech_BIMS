import re

from django.db import models
from django.core.validators import MinValueValidator
from django.utils.translation import gettext_lazy as _

from account.models import ChartOfAccount
from inventory.models import Item, Warehouse
from purchase.models import Supplier
from sales.models import Customer


class HatchSetting(models.Model):
    """
    Header record for a hatch register & sales sheet. `setting_no` is the
    batch id this whole record (egg intake, hatch output, sales) is keyed on.
    """
    PAYMENT_STATUS_CHOICES = [
        ('unpaid', _('Unpaid')),
        ('partial', _('Partial')),
        ('paid', _('Paid')),
    ]

    setting_no = models.CharField(
        max_length=50,
        unique=True,
        help_text=_("Batch id for this hatch setting (e.g. 44)")
    )
    batch_flock_no = models.CharField(
        max_length=50,
        editable=False,
        blank=True,
        help_text=_("Auto-generated batch/flock number: DDMM of today, plus today's sequence (e.g. 0806/01)")
    )
    supplier_name = models.CharField(
        max_length=150,
        help_text=_("Supplier of the eggs for this setting")
    )
    primary_machine_nos = models.CharField(
        max_length=100,
        blank=True,
        help_text=_("Primary setter machine numbers (e.g. 39,40,41,42)")
    )
    avg_egg_weight = models.CharField(
        max_length=50, blank=True, help_text=_("e.g. EGG WT 55-58 GM")
    )
    received_date = models.DateField(help_text=_("Date eggs were received"))
    received_time = models.TimeField(blank=True, null=True, help_text=_("Time eggs were received"))
    setting_date = models.DateField(help_text=_("Date eggs were set"))
    transfer_date = models.DateField(blank=True, null=True, help_text=_("Date of hatcher transfer"))
    hatch_date = models.DateField(blank=True, null=True, help_text=_("Date of hatch"))
    push_time = models.TimeField(blank=True, null=True, help_text=_("Chick pull/push time"))

    received_qty = models.PositiveIntegerField(
        default=0, help_text=_("Total eggs received for this lot")
    )
    breakage_qty = models.PositiveIntegerField(
        default=0, help_text=_("Total broken eggs for this lot")
    )
    crack_qty = models.PositiveIntegerField(
        default=0, help_text=_("Total cracked eggs for this lot")
    )
    setting_qty = models.PositiveIntegerField(
        default=0, help_text=_("Net eggs actually set (received minus breakage/crack)")
    )

    setter_temperature = models.CharField(max_length=20, blank=True, help_text=_("e.g. 99F"))
    setter_humidity = models.CharField(max_length=20, blank=True, help_text=_("e.g. 60%"))
    hatcher_temperature = models.CharField(max_length=20, blank=True, help_text=_("e.g. 98.5F"))
    hatcher_humidity = models.CharField(max_length=20, blank=True, help_text=_("e.g. 70%"))
    avg_chick_weight = models.CharField(
        max_length=50, blank=True, help_text=_("Avg Chicks Weight, e.g. CHICKS WT 38-40 GM")
    )
    medicine_vaccine = models.CharField(max_length=150, blank=True)
    packing_boxes_used = models.PositiveIntegerField(blank=True, null=True)
    remarks = models.TextField(blank=True)

    prepared_by = models.CharField(max_length=100, blank=True, help_text=_("Operator name"))
    verified_by = models.CharField(max_length=100, blank=True, help_text=_("Hatchery Manager name"))

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Hatch Setting")
        verbose_name_plural = _("Hatch Settings")
        ordering = ['-setting_date', '-id']

    def __str__(self):
        return f"Setting {self.setting_no} ({self.supplier_name})"

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.batch_flock_no:
            self.batch_flock_no = self._next_batch_flock_no()
            super().save(update_fields=['batch_flock_no'])

    @classmethod
    def _next_batch_flock_no(cls, on_date=None):
        from django.utils import timezone
        today = on_date or timezone.localdate()
        prefix = f"{today.day:02d}{today.month:02d}/"
        max_num = 0
        for existing in cls.objects.filter(batch_flock_no__startswith=prefix).values_list('batch_flock_no', flat=True):
            match = re.match(re.escape(prefix) + r'(\d+)$', existing or '')
            if match:
                max_num = max(max_num, int(match.group(1)))
        return f"{prefix}{max_num + 1:02d}"

    def breakage_percent(self):
        if not self.received_qty:
            return 0
        return round(self.breakage_qty / self.received_qty * 100, 2)

    def crack_percent(self):
        if not self.received_qty:
            return 0
        return round(self.crack_qty / self.received_qty * 100, 2)

    def total_setting_qty(self):
        return self.setting_qty

    def total_saleable_chicks(self):
        return self.hatcher_outputs.aggregate(total=models.Sum('saleable_chicks'))['total'] or 0

    def hatch_percent(self):
        if not self.setting_qty:
            return 0
        return round(self.total_saleable_chicks() / self.setting_qty * 100, 2)

    def total_chicks_sold(self):
        return self.sales_lines.aggregate(total=models.Sum('chicks_sold'))['total'] or 0

    def unsold_chicks(self):
        return self.total_saleable_chicks() - self.total_chicks_sold()

    def total_sales_amount(self):
        return self.sales_lines.aggregate(total=models.Sum('total_amount'))['total'] or 0


class HatchEggIntake(models.Model):
    """
    A single setter row within the egg intake section of a hatch setting.
    """
    hatch_setting = models.ForeignKey(
        HatchSetting,
        on_delete=models.CASCADE,
        related_name='egg_intakes',
        help_text=_("Hatch setting this egg intake row belongs to")
    )
    sub_lot_flock = models.CharField(max_length=50, blank=True)
    setter_no = models.CharField(max_length=50)
    no_trays = models.PositiveIntegerField(blank=True, null=True)
    tray_size = models.PositiveIntegerField(blank=True, null=True)
    total_eggs = models.PositiveIntegerField(blank=True, null=True)

    class Meta:
        verbose_name = _("Egg Intake Row")
        verbose_name_plural = _("Egg Intake Rows")
        ordering = ['id']

    def __str__(self):
        return f"Setter {self.setter_no} ({self.hatch_setting.setting_no})"


class HatchHatcherOutput(models.Model):
    """
    A single hatcher row within the candling/output grading section.
    """
    hatch_setting = models.ForeignKey(
        HatchSetting,
        on_delete=models.CASCADE,
        related_name='hatcher_outputs',
        help_text=_("Hatch setting this hatcher output row belongs to")
    )
    hatcher_no = models.CharField(max_length=50)
    infertile_qty = models.PositiveIntegerField(default=0)
    early_dead_qty = models.PositiveIntegerField(default=0)
    blasting_qty = models.PositiveIntegerField(default=0)
    transfer_qty = models.PositiveIntegerField(default=0)
    dead_in_shell_qty = models.PositiveIntegerField(default=0)
    culls_malf_qty = models.PositiveIntegerField(default=0)
    saleable_chicks = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _("Hatcher Output Row")
        verbose_name_plural = _("Hatcher Output Rows")
        ordering = ['id']

    def __str__(self):
        return f"Hatcher {self.hatcher_no} ({self.hatch_setting.setting_no})"


class HatchSalesLine(models.Model):
    """
    A single customer sale row within the hatchery sale section.
    """
    hatch_setting = models.ForeignKey(
        HatchSetting,
        on_delete=models.CASCADE,
        related_name='sales_lines',
        help_text=_("Hatch setting this sale row belongs to")
    )
    trader_customer_name = models.CharField(max_length=150)
    chicks_sold = models.PositiveIntegerField(
        default=0, help_text=_("Total chicks dispatched, inclusive of the free-chick bonus (e.g. 102 = 100 + 2%)")
    )
    discount_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=0, help_text=_("Free-chick bonus % baked into Chicks Sold")
    )
    free_chicks = models.PositiveIntegerField(default=0)
    billed_chicks = models.PositiveIntegerField(default=0)
    rate = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    payment_status = models.CharField(
        max_length=20, choices=HatchSetting.PAYMENT_STATUS_CHOICES, default='unpaid'
    )
    delivery_notes = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = _("Hatch Sales Line")
        verbose_name_plural = _("Hatch Sales Lines")
        ordering = ['id']

    def __str__(self):
        return f"{self.trader_customer_name} ({self.hatch_setting.setting_no})"


class EggPurchase(models.Model):
    """
    Header record for a hatchery egg purchase transaction (Hatchery
    Transaction section) - a supplier invoice for eggs bought in, with one
    or more item rows plus freight/TCS/payment terms.
    """
    FREIGHT_TYPE_CHOICES = [
        ('Include', _('Include')),
        ('Exclude', _('Exclude')),
    ]
    PAYMENT_MODE_CHOICES = [
        ('pay_later', _('Pay Later')),
        ('pay_in_bill', _('Pay In Bill')),
    ]

    transaction_no = models.CharField(
        max_length=30,
        unique=True,
        editable=False,
        blank=True,
        help_text=_("Auto-generated transaction number for this egg purchase")
    )
    date = models.DateField(help_text=_("Date of purchase"))
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name='egg_purchases',
        help_text=_("Supplier the eggs were purchased from")
    )
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name='egg_purchases',
        help_text=_("Farm/Warehouse the eggs were received at")
    )
    dc_no = models.CharField(max_length=50, blank=True, help_text=_("Delivery challan number"))
    vehicle = models.CharField(max_length=50, blank=True)
    driver = models.CharField(max_length=100, blank=True)

    freight_type = models.CharField(max_length=10, choices=FREIGHT_TYPE_CHOICES, default='Exclude')
    payment_mode = models.CharField(max_length=15, choices=PAYMENT_MODE_CHOICES, default='pay_later')
    pay_account = models.ForeignKey(
        ChartOfAccount, on_delete=models.PROTECT, related_name='egg_purchase_pay_accounts',
        help_text=_("Account this purchase is paid from")
    )
    freight_account = models.ForeignKey(
        ChartOfAccount, on_delete=models.PROTECT, related_name='egg_purchase_freight_accounts',
        null=True, blank=True, help_text=_("Account freight is booked against")
    )
    freight_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    tcs_applicable = models.BooleanField(default=False, help_text=_("Whether TCS applies to this purchase"))
    tcs_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    remarks = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Egg Purchase")
        verbose_name_plural = _("Egg Purchases")
        ordering = ['-date', '-id']

    def __str__(self):
        return f"{self.transaction_no} ({self.supplier})"

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.transaction_no:
            self.transaction_no = self._next_transaction_no()
            super().save(update_fields=['transaction_no'])

    @classmethod
    def _next_transaction_no(cls):
        max_num = 0
        for existing in cls.objects.values_list('transaction_no', flat=True):
            match = re.match(r'EGGP-(\d+)$', existing or '')
            if match:
                max_num = max(max_num, int(match.group(1)))
        return f"EGGP-{max_num + 1:04d}"

    def gross_amount(self):
        return self.items.aggregate(total=models.Sum('total_amount'))['total'] or 0

    def net_quantity(self):
        """Received + Free — the actual eggs that arrived, bonus stock included."""
        return self.items.aggregate(
            total=models.Sum(models.F('rcv_qty') + models.F('free_qty'))
        )['total'] or 0

    def freight_included_amount(self):
        return self.gross_amount() + (self.freight_amount if self.freight_type == 'Include' else 0)

    def tcs_amount(self):
        if not self.tcs_applicable:
            return 0
        return round(self.freight_included_amount() * self.tcs_percent / 100, 2)

    def net_amount(self):
        return self.freight_included_amount() + self.tcs_amount()

    def net_rate(self):
        # Free qty has no cost basis, so the per-unit rate is still spread
        # over Received Qty only — net_quantity() (which does include Free
        # Qty) is a display figure, not this rate's denominator.
        qty = self.items.aggregate(total=models.Sum('rcv_qty'))['total'] or 0
        return round(self.net_amount() / qty, 2) if qty else 0

    def supplier_amount(self):
        return self.gross_amount()


class EggPurchaseItem(models.Model):
    """A single item row (e.g. Hatching Eggs) within an egg purchase."""
    egg_purchase = models.ForeignKey(
        EggPurchase, on_delete=models.CASCADE, related_name='items',
        help_text=_("Egg purchase this item row belongs to")
    )
    item = models.ForeignKey(
        Item, on_delete=models.PROTECT, related_name='egg_purchase_items'
    )
    sent_qty = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    rcv_qty = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    free_qty = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    no_of_boxes = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    rate = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text=_("Rate per unit (Rcv Qty, or Sent Qty if none received) — Amount is derived from this"))
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False, validators=[MinValueValidator(0)])
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)

    class Meta:
        verbose_name = _("Egg Purchase Item")
        verbose_name_plural = _("Egg Purchase Items")
        ordering = ['id']

    def __str__(self):
        return f"{self.item} ({self.egg_purchase.transaction_no})"

    def save(self, *args, **kwargs):
        qty_basis = self.rcv_qty or self.sent_qty
        self.amount = round((self.rate or 0) * qty_basis, 2)
        discount_from_percent = (self.amount * self.discount_percent / 100) if self.discount_percent else 0
        self.total_amount = self.amount - discount_from_percent - (self.discount_amount or 0)
        super().save(*args, **kwargs)


class EggGrading(models.Model):
    """
    Header record for grading/receiving eggs from a specific egg purchase
    invoice into hatch-ready stock, tracking rejections along the way.
    """
    transaction_no = models.CharField(
        max_length=30,
        unique=True,
        editable=False,
        blank=True,
        help_text=_("Auto-generated transaction number for this egg grading")
    )
    date = models.DateField(help_text=_("Date of grading/receiving"))
    storage_location = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name='egg_gradings',
        help_text=_("Storage location the graded eggs are received into")
    )
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name='egg_gradings',
        help_text=_("Supplier of the eggs being graded")
    )
    purchase_invoice = models.ForeignKey(
        EggPurchase, on_delete=models.PROTECT, related_name='gradings',
        help_text=_("Egg purchase invoice these eggs are being graded from")
    )
    item = models.ForeignKey(
        Item, on_delete=models.PROTECT, related_name='egg_gradings',
        help_text=_("Item being graded")
    )
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text=_("Quantity taken for grading"))

    broken_eggs = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    damage_eggs = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    misshapped_eggs = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    dirty_eggs = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Egg Grading")
        verbose_name_plural = _("Egg Gradings")
        ordering = ['-date', '-id']

    def __str__(self):
        return f"{self.transaction_no} ({self.item})"

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.transaction_no:
            self.transaction_no = self._next_transaction_no()
            super().save(update_fields=['transaction_no'])

    @classmethod
    def _next_transaction_no(cls):
        max_num = 0
        for existing in cls.objects.values_list('transaction_no', flat=True):
            match = re.match(r'GRAD-(\d+)$', existing or '')
            if match:
                max_num = max(max_num, int(match.group(1)))
        return f"GRAD-{max_num + 1:04d}"

    def total_rejections(self):
        return self.broken_eggs + self.damage_eggs + self.misshapped_eggs + self.dirty_eggs

    def eggs_to_stock(self):
        remaining = self.quantity - self.total_rejections()
        return remaining if remaining > 0 else 0

    def total_hatch_qty(self):
        return self.hatch_items.aggregate(total=models.Sum('quantity'))['total'] or 0

    @classmethod
    def available_stock(cls, purchase_invoice_id, item_id, exclude_id=None):
        """Rcv qty on the purchase invoice's matching item line, minus what's already been graded against it."""
        try:
            purchase_line = EggPurchaseItem.objects.get(egg_purchase_id=purchase_invoice_id, item_id=item_id)
        except EggPurchaseItem.DoesNotExist:
            return 0
        already_graded_qs = cls.objects.filter(purchase_invoice_id=purchase_invoice_id, item_id=item_id)
        if exclude_id:
            already_graded_qs = already_graded_qs.exclude(id=exclude_id)
        already_graded = already_graded_qs.aggregate(total=models.Sum('quantity'))['total'] or 0
        remaining = purchase_line.rcv_qty - already_graded
        return remaining if remaining > 0 else 0


class EggGradingHatchItem(models.Model):
    """A hatch-item output row (e.g. Grade A / Grade B) within an egg grading."""
    egg_grading = models.ForeignKey(
        EggGrading, on_delete=models.CASCADE, related_name='hatch_items',
        help_text=_("Egg grading this hatch item row belongs to")
    )
    hatch_item = models.ForeignKey(
        Item, on_delete=models.PROTECT, related_name='egg_grading_hatch_items'
    )
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        verbose_name = _("Egg Grading Hatch Item")
        verbose_name_plural = _("Egg Grading Hatch Items")
        ordering = ['id']

    def __str__(self):
        return f"{self.hatch_item} ({self.egg_grading.transaction_no})"


class DeliveryChallan(models.Model):
    """Dispatch document raised by the hatchery transaction team."""
    challan_no = models.CharField(max_length=30, unique=True, editable=False, blank=True)
    date = models.DateField()
    place_of_supply = models.CharField(max_length=50, blank=True)
    overall_discount = models.DecimalField(max_digits=12, decimal_places=2, default=0, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="hatchery_challans")
    shipping_address = models.TextField(blank=True)
    transport_mode = models.CharField(max_length=20, default="Road")
    vehicle_no = models.CharField(max_length=50, blank=True)
    driver_name = models.CharField(max_length=100, blank=True)
    driver_mobile = models.CharField(max_length=20, blank=True)
    transporter_name = models.CharField(max_length=150, blank=True)
    transport_document_no = models.CharField(max_length=50, blank=True)
    transport_document_date = models.DateField(null=True, blank=True)
    eway_bill_no = models.CharField(max_length=50, blank=True)
    eway_bill_date = models.DateField(null=True, blank=True)
    print_price_details = models.BooleanField(default=True)
    terms = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return self.challan_no

    @classmethod
    def next_challan_no(cls, on_date=None):
        from django.utils import timezone
        current_date = on_date or timezone.localdate()
        start_year = current_date.year if current_date.month >= 4 else current_date.year - 1
        financial_year = f"{start_year % 100:02d}-{(start_year + 1) % 100:02d}"
        prefix = f"HF/DC/{financial_year}/"
        serials = []
        for number in cls.objects.filter(challan_no__startswith=prefix).values_list("challan_no", flat=True):
            match = re.match(r"^HF/DC/\d{2}-\d{2}/(\d+)$", number or "")
            if match:
                serials.append(int(match.group(1)))
        return f"{prefix}{max(serials, default=0) + 1:04d}"

    def save(self, *args, **kwargs):
        if self._state.adding and not self.challan_no:
            self.challan_no = self.next_challan_no(self.date)
        super().save(*args, **kwargs)

    def total_quantity(self):
        return self.items.aggregate(total=models.Sum("quantity"))["total"] or 0

    def total_units(self):
        return self.items.aggregate(total=models.Sum("units"))["total"] or 0

    def total_amount(self):
        return self.items.aggregate(total=models.Sum("amount"))["total"] or 0

    def total_tax(self):
        total = 0
        for row in self.items.all():
            subtotal = row.quantity * row.price * (1 - row.discount_percent / 100)
            total += subtotal * row.tax_percent / 100
        return total

    def grand_total(self):
        return self.total_amount() - (self.overall_discount or 0)


class DeliveryChallanItem(models.Model):
    challan = models.ForeignKey(DeliveryChallan, on_delete=models.CASCADE, related_name="items")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="delivery_challan_items")
    packing_size = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    units = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unit = models.CharField(max_length=30, blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    tax_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        ordering = ["id"]

    def save(self, *args, **kwargs):
        if not self.quantity:
            self.quantity = self.packing_size * self.units
        subtotal = self.quantity * self.price * (1 - self.discount_percent / 100)
        self.amount = subtotal * (1 + self.tax_percent / 100)
        super().save(*args, **kwargs)


class TraySetting(models.Model):
    """Tray-set transaction: graded eggs loaded into setter machines for incubation."""
    setting_no = models.CharField(max_length=30, unique=True, editable=False, blank=True)
    hatchery = models.ForeignKey('hatchery_master.Hatchery', on_delete=models.PROTECT, related_name='tray_settings')
    setting_date = models.DateField()
    transfer_date = models.DateField(null=True, blank=True, help_text=_("Hatcher transfer date, typically setting date + 18 days"))
    hatch_date = models.DateField(help_text=_("Expected hatch date, typically setting date + 21 days"))
    setting_time = models.TimeField(null=True, blank=True)
    loaded_by = models.CharField(max_length=100, blank=True, default='', help_text=_("Who loaded the trays; pick an employee or type any name"))
    grading = models.ForeignKey(EggGrading, on_delete=models.PROTECT, related_name='tray_settings')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-setting_date', '-id']

    def __str__(self):
        return self.setting_no

    @classmethod
    def next_setting_no(cls):
        max_num = 0
        for existing in cls.objects.values_list('setting_no', flat=True):
            match = re.match(r'TS-(\d+)$', existing or '')
            if match:
                max_num = max(max_num, int(match.group(1)))
        return f"TS-{max_num + 1:04d}"

    def save(self, *args, **kwargs):
        if self._state.adding and not self.setting_no:
            self.setting_no = self.next_setting_no()
        super().save(*args, **kwargs)

    def total_eggs_set(self):
        return self.lines.aggregate(total=models.Sum('eggs_set'))['total'] or 0

    def total_eggs(self):
        return self.lines.aggregate(total=models.Sum('total_eggs'))['total'] or 0

    def total_broken(self):
        return self.lines.aggregate(total=models.Sum('broken'))['total'] or 0

    def total_damaged(self):
        return self.lines.aggregate(total=models.Sum('damaged'))['total'] or 0

    def total_expected_chicks(self):
        return self.lines.aggregate(total=models.Sum('expected_chicks'))['total'] or 0

    def supplier_names(self):
        return ", ".join(sorted({line.supplier.name for line in self.lines.all() if line.supplier}))


class TraySettingLine(models.Model):
    """One setter-machine load within a tray setting."""
    tray_setting = models.ForeignKey(TraySetting, on_delete=models.CASCADE, related_name='lines')
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, null=True, blank=True, related_name='tray_setting_lines')
    setter = models.ForeignKey('hatchery_master.Setter', on_delete=models.PROTECT, related_name='tray_setting_lines')
    item = models.ForeignKey(Item, on_delete=models.PROTECT, null=True, blank=True, related_name='tray_setting_lines')
    no_trays = models.PositiveIntegerField(null=True, blank=True)
    tray_size = models.PositiveIntegerField(null=True, blank=True)
    total_eggs = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    broken = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text=_("Legacy field — broken/damaged eggs are tracked in Egg Grading, not re-entered per tray-set line"),
    )
    damaged = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    eggs_set = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    avg_weight = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text=_("Average egg weight"))
    expected_chicks = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['id']

    def save(self, *args, **kwargs):
        if not self.eggs_set:
            self.eggs_set = (self.total_eggs or 0) - (self.broken or 0) - (self.damaged or 0)
        super().save(*args, **kwargs)


class HatchEntry(models.Model):
    """Hatch outcome recorded against a tray setting: chicks hatched, egg cost and vaccine consumption."""
    transaction_no = models.CharField(max_length=30, unique=True, editable=False, blank=True)
    tray_setting = models.OneToOneField(TraySetting, on_delete=models.PROTECT, related_name='hatch_entry')
    hatch_date = models.DateField(null=True, blank=True, help_text=_("Actual hatch date; may differ from the tray setting's expected date"))
    eggs_total = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text=_("No. of eggs set (snapshot from tray setting)"))
    egg_rate = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    eggs_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    chicks_total = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text=_("Saleable chicks hatched"))
    chick_rate = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    chicks_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    net_rate = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text=_("Net cost per chick"))
    net_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0, help_text=_("Eggs amount + vaccine consumption"))
    remarks = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-id']
        verbose_name_plural = _("Hatch entries")

    def __str__(self):
        return self.transaction_no

    @classmethod
    def next_transaction_no(cls):
        max_num = 0
        for existing in cls.objects.values_list('transaction_no', flat=True):
            match = re.match(r'HE-(\d+)$', existing or '')
            if match:
                max_num = max(max_num, int(match.group(1)))
        return f"HE-{max_num + 1:04d}"

    def save(self, *args, **kwargs):
        if self._state.adding and not self.transaction_no:
            self.transaction_no = self.next_transaction_no()
        super().save(*args, **kwargs)

    def apply_purchase_snapshot(self):
        """Fill the eggs row from the egg purchase behind this entry's grading (procurement cost)."""
        purchase = self.tray_setting.grading.purchase_invoice
        self.eggs_total = purchase.net_quantity()
        self.egg_rate = purchase.net_rate()
        self.eggs_amount = purchase.net_amount()

    def vaccine_total(self):
        return self.vaccines.aggregate(total=models.Sum('amount'))['total'] or 0

    def recalculate_net(self):
        """Net cost = egg procurement + vaccine expenses; per-chick rate = net / saleable chicks.
        The chicks row carries the same computed rate/amount."""
        self.net_amount = (self.eggs_amount or 0) + self.vaccine_total()
        self.net_rate = round(self.net_amount / self.chicks_total, 2) if self.chicks_total else 0
        self.chick_rate = self.net_rate
        self.chicks_amount = self.net_amount
        super(HatchEntry, self).save(update_fields=['net_amount', 'net_rate', 'chick_rate', 'chicks_amount'])


class HatchEntryHatcherOutput(models.Model):
    """One hatcher machine's candling/transfer/final-grading breakdown within
    a hatch entry — same shape as HatchHatcherOutput (Hatch Register), but
    against the newer TraySetting -> HatchEntry pipeline. ``hatcher`` is a
    real FK to hatchery_master.Hatcher (Hatchery > Master > Hatcher), the
    same way TraySettingLine.setter picks from hatchery_master.Setter."""
    hatch_entry = models.ForeignKey(HatchEntry, on_delete=models.CASCADE, related_name='hatcher_outputs')
    hatcher = models.ForeignKey('hatchery_master.Hatcher', on_delete=models.PROTECT, related_name='hatch_entry_outputs')
    infertile_qty = models.PositiveIntegerField(default=0)
    early_dead_qty = models.PositiveIntegerField(default=0)
    blasting_qty = models.PositiveIntegerField(default=0)
    transfer_qty = models.PositiveIntegerField(default=0)
    dead_in_shell_qty = models.PositiveIntegerField(default=0)
    culls_malf_qty = models.PositiveIntegerField(default=0)
    saleable_chicks = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"Hatcher {self.hatcher.hatcher_no} ({self.hatch_entry.transaction_no})"


class HatchEntryVaccine(models.Model):
    """One vaccine/medicine consumption line within a hatch entry."""
    hatch_entry = models.ForeignKey(HatchEntry, on_delete=models.CASCADE, related_name='vaccines')
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name='hatch_entry_vaccines')
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    rate = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        ordering = ['id']

    def save(self, *args, **kwargs):
        self.amount = (self.quantity or 0) * (self.rate or 0)
        super().save(*args, **kwargs)


class ChickSale(models.Model):
    """Chick sale invoice; can be created fresh or converted from a delivery challan."""
    FREIGHT_TYPE_CHOICES = [
        ('Paid by Customer', _('Paid by Customer')),
        ('Include in Bill', _('Include in Bill')),
    ]
    PAYMENT_MODE_CHOICES = [
        ('pay_later', _('Pay Later')),
        ('pay_in_bill', _('Pay In Bill')),
    ]

    bill_no = models.CharField(max_length=30, unique=True, editable=False, blank=True)
    date = models.DateField()
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='chick_sales')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='chick_sales',
                                  help_text=_("Stock point / feed mill the chicks are sold from"))
    delivery_challan = models.ForeignKey(DeliveryChallan, on_delete=models.SET_NULL, null=True, blank=True,
                                         related_name='chick_sales',
                                         help_text=_("Delivery challan this sale was converted from"))
    shipping_address = models.TextField(blank=True)
    vehicle = models.CharField(max_length=50, blank=True)
    driver = models.CharField(max_length=100, blank=True)
    freight_type = models.CharField(max_length=20, choices=FREIGHT_TYPE_CHOICES, default='Paid by Customer')
    payment_mode = models.CharField(max_length=15, choices=PAYMENT_MODE_CHOICES, default='pay_later')
    pay_account = models.ForeignKey(ChartOfAccount, on_delete=models.PROTECT, null=True, blank=True,
                                    related_name='chick_sale_pay_accounts')
    freight_account = models.ForeignKey(ChartOfAccount, on_delete=models.PROTECT, null=True, blank=True,
                                        related_name='chick_sale_freight_accounts')
    freight_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    final_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    avg_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0,
                                     help_text=_("Average realised rate per bird"))
    profit_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0,
                                        help_text=_("Sale value minus chick cost (latest hatch entry net rate)"))
    terms = models.TextField(blank=True)
    remarks = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', '-id']

    def __str__(self):
        return self.bill_no

    @classmethod
    def next_bill_no(cls):
        max_num = 0
        for existing in cls.objects.values_list('bill_no', flat=True):
            match = re.match(r'CS-(\d+)$', existing or '')
            if match:
                max_num = max(max_num, int(match.group(1)))
        return f"CS-{max_num + 1:04d}"

    def save(self, *args, **kwargs):
        if self._state.adding and not self.bill_no:
            self.bill_no = self.next_bill_no()
        super().save(*args, **kwargs)

    def total_birds(self):
        return self.items.aggregate(total=models.Sum('total_qty'))['total'] or 0

    def total_net_qty(self):
        return self.items.aggregate(total=models.Sum('net_qty'))['total'] or 0

    def total_free_qty(self):
        return self.items.aggregate(total=models.Sum('free_qty'))['total'] or 0

    def items_amount(self):
        return self.items.aggregate(total=models.Sum('amount'))['total'] or 0

    def item_names(self):
        return ", ".join(sorted({row.item.item_code for row in self.items.all()}))

    def recalculate(self):
        """final = items + freight (when billed); avg = final / net qty;
        profit = items amount - chick cost at the latest hatch entry's net rate."""
        items_amount = self.items_amount()
        net_qty = self.total_net_qty()
        self.final_amount = items_amount + (self.freight_amount if self.freight_type == 'Include in Bill' else 0)
        self.avg_amount = round(self.final_amount / net_qty, 2) if net_qty else 0
        latest_entry = HatchEntry.objects.order_by('-id').first()
        cost_rate = latest_entry.net_rate if latest_entry else 0
        self.profit_amount = items_amount - (net_qty * cost_rate)
        super(ChickSale, self).save(update_fields=['final_amount', 'avg_amount', 'profit_amount'])


class ChickSaleItem(models.Model):
    """One item line within a chick sale.

    Sale Qty = Total - Mortality - Culls (inclusive of free chicks).
    With a discount %, Billed Qty = Sale Qty / (1 + disc%/100) and the
    balance becomes Free Qty; Amount = Billed Qty x Rate - Disc Amount.
    """
    sale = models.ForeignKey(ChickSale, on_delete=models.CASCADE, related_name='items')
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name='chick_sale_items')
    farm = models.CharField(max_length=150, blank=True)
    total_qty = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    mortality = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    culls = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sale_qty = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    free_qty = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    net_qty = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text=_("Billed quantity"))
    sale_rate = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        ordering = ['id']

    def save(self, *args, **kwargs):
        if not self.sale_qty:
            self.sale_qty = max((self.total_qty or 0) - (self.mortality or 0) - (self.culls or 0), 0)
        if self.discount_percent:
            self.net_qty = round(self.sale_qty / (1 + self.discount_percent / 100))
            self.free_qty = self.sale_qty - self.net_qty
        elif not self.net_qty:
            self.net_qty = max(self.sale_qty - (self.free_qty or 0), 0)
        self.amount = (self.net_qty or 0) * (self.sale_rate or 0) - (self.discount_amount or 0)
        super().save(*args, **kwargs)


class ChangeRequest(models.Model):
    """A pending modification/deletion of a transaction, raised by a user who
    lacks the edit/delete right and reviewed by a user who holds it."""
    ACTION_CHOICES = [('edit', _('Modification')), ('delete', _('Deletion'))]
    STATUS_CHOICES = [('pending', _('Pending')), ('approved', _('Approved')), ('rejected', _('Rejected'))]

    module = models.CharField(max_length=40, help_text=_("Handler key, e.g. delivery_challan"))
    object_id = models.PositiveIntegerField()
    object_label = models.CharField(max_length=100, blank=True, help_text=_("Human label, e.g. the transaction number"))
    action = models.CharField(max_length=10, choices=ACTION_CHOICES)
    payload = models.JSONField(null=True, blank=True, help_text=_("Proposed new values (edit requests)"))
    note = models.TextField(blank=True, help_text=_("Requester's reason/remarks"))
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    requested_by = models.ForeignKey('auth.User', on_delete=models.PROTECT, related_name='change_requests')
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey('auth.User', on_delete=models.PROTECT, null=True, blank=True, related_name='reviewed_change_requests')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)

    class Meta:
        ordering = ['-id']

    def __str__(self):
        return f"{self.get_action_display()} of {self.module} #{self.object_id} ({self.status})"
