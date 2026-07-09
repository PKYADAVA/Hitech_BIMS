from django.db import models
from django.core.validators import MinValueValidator
from django.utils.translation import gettext_lazy as _


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
        blank=True,
        help_text=_("Batch / Flock number (e.g. 0806/01)")
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
        max_length=50, blank=True, help_text=_("e.g. CHICKS WT 38-40 GM")
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
    chicks_sold = models.PositiveIntegerField(default=0)
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
