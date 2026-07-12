import re

from django.db import models
from django.core.validators import MinValueValidator
from django.utils.translation import gettext_lazy as _

from account.models import ChartOfAccount
from inventory.models import Item, Warehouse
from purchase.models import Supplier


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
        return self.items.aggregate(total=models.Sum('rcv_qty'))['total'] or 0

    def freight_included_amount(self):
        return self.gross_amount() + (self.freight_amount if self.freight_type == 'Include' else 0)

    def tcs_amount(self):
        if not self.tcs_applicable:
            return 0
        return round(self.freight_included_amount() * self.tcs_percent / 100, 2)

    def net_amount(self):
        return self.freight_included_amount() + self.tcs_amount()

    def net_rate(self):
        qty = self.net_quantity()
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
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    rate = models.DecimalField(max_digits=10, decimal_places=2, default=0, editable=False)

    class Meta:
        verbose_name = _("Egg Purchase Item")
        verbose_name_plural = _("Egg Purchase Items")
        ordering = ['id']

    def __str__(self):
        return f"{self.item} ({self.egg_purchase.transaction_no})"

    def save(self, *args, **kwargs):
        discount_from_percent = (self.amount * self.discount_percent / 100) if self.discount_percent else 0
        self.total_amount = self.amount - discount_from_percent - (self.discount_amount or 0)
        qty_basis = self.rcv_qty or self.sent_qty
        self.rate = round(self.total_amount / qty_basis, 2) if qty_basis else 0
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
