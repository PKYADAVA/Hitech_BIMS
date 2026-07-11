from django.core.validators import RegexValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

STATES_AND_TERRITORIES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
    "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka",
    "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram",
    "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu",
    "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
    "Andaman and Nicobar Islands", "Chandigarh",
    "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Jammu and Kashmir",
    "Ladakh", "Lakshadweep", "Puducherry",
]

phone_validator = RegexValidator(
    regex=r'^\+?1?\d{9,15}$',
    message=_("Phone number must be entered in the format: '+999999999'. Up to 15 digits allowed.")
)


class Hatchery(models.Model):
    """
    Master record for a hatchery facility/partner (name, ownership, contact
    and agreement details) - distinct from the hatch register (HatchSetting)
    which logs day-to-day egg intake/output/sales against a hatchery.
    """
    OPERATION_TYPES = [
        ('own', _('Own')),
        ('contract', _('Contract')),
        ('lease', _('Lease')),
    ]

    hatchery_name = models.CharField(
        max_length=150,
        unique=True,
        help_text=_("Name of the hatchery")
    )
    operation_type = models.CharField(
        max_length=20,
        choices=OPERATION_TYPES,
        help_text=_("Type of operation")
    )
    owner_name = models.CharField(
        max_length=150,
        blank=True,
        help_text=_("Owner's name")
    )
    contact = models.CharField(
        max_length=15,
        blank=True,
        validators=[phone_validator],
        help_text=_("Contact number")
    )
    email = models.EmailField(
        blank=True,
        help_text=_("Email address")
    )
    state = models.CharField(
        max_length=100,
        choices=[(state, state) for state in STATES_AND_TERRITORIES],
        blank=True,
        help_text=_("State where the hatchery is located")
    )
    agreement_months = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text=_("Duration of the agreement in months")
    )
    document = models.FileField(
        upload_to='hatchery_master/documents/',
        blank=True,
        null=True,
        help_text=_("Supporting document (agreement copy, etc.)")
    )
    is_active = models.BooleanField(
        default=True,
        help_text=_("Inactive hatcheries are hidden from selection elsewhere")
    )
    is_locked = models.BooleanField(
        default=False,
        help_text=_("Locked records can't be edited or deleted")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Hatchery")
        verbose_name_plural = _("Hatcheries")
        ordering = ['hatchery_name']

    def __str__(self):
        return self.hatchery_name


class Setter(models.Model):
    """
    A setter machine belonging to a hatchery, with its egg capacity.
    """
    hatchery = models.ForeignKey(
        Hatchery,
        on_delete=models.CASCADE,
        related_name='setters',
        help_text=_("Hatchery this setter belongs to")
    )
    setter_no = models.CharField(
        max_length=20,
        help_text=_("Setter machine number")
    )
    capacity = models.PositiveIntegerField(
        help_text=_("Egg capacity of this setter")
    )
    is_active = models.BooleanField(
        default=True,
        help_text=_("Inactive setters are hidden from selection elsewhere")
    )
    is_locked = models.BooleanField(
        default=False,
        help_text=_("Locked records can't be edited or deleted")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Setter")
        verbose_name_plural = _("Setters")
        ordering = ['hatchery__hatchery_name', 'setter_no']
        unique_together = [('hatchery', 'setter_no')]

    def __str__(self):
        return f"{self.setter_no} ({self.hatchery.hatchery_name})"


class Hatcher(models.Model):
    """
    A hatcher machine belonging to a hatchery, with its egg capacity.
    """
    hatchery = models.ForeignKey(
        Hatchery,
        on_delete=models.CASCADE,
        related_name='hatchers',
        help_text=_("Hatchery this hatcher belongs to")
    )
    hatcher_no = models.CharField(
        max_length=20,
        help_text=_("Hatcher machine number")
    )
    capacity = models.PositiveIntegerField(
        help_text=_("Egg capacity of this hatcher")
    )
    is_active = models.BooleanField(
        default=True,
        help_text=_("Inactive hatchers are hidden from selection elsewhere")
    )
    is_locked = models.BooleanField(
        default=False,
        help_text=_("Locked records can't be edited or deleted")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Hatcher")
        verbose_name_plural = _("Hatchers")
        ordering = ['hatchery__hatchery_name', 'hatcher_no']
        unique_together = [('hatchery', 'hatcher_no')]

    def __str__(self):
        return f"{self.hatcher_no} ({self.hatchery.hatchery_name})"


class ExpenseType(models.Model):
    """
    A user-managed category of hatchery expense (e.g. Feed, Medicine,
    Labor) - created/renamed as needed rather than hardcoded, so the
    Hatchery Expense form's category list stays in sync automatically.
    """
    name = models.CharField(
        max_length=100,
        unique=True,
        help_text=_("Name of the expense type")
    )
    is_active = models.BooleanField(
        default=True,
        help_text=_("Inactive expense types are hidden from selection elsewhere")
    )
    is_locked = models.BooleanField(
        default=False,
        help_text=_("Locked records can't be edited or deleted")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Expense Type")
        verbose_name_plural = _("Expense Types")
        ordering = ['name']

    def __str__(self):
        return self.name


class HatcheryExpense(models.Model):
    """
    A single expense-type line item recorded against a hatchery on a given
    date. Adding an expense entry in the UI creates one of these per
    expense type with a non-zero amount, all sharing the same date/
    hatchery/stage.
    """
    STAGE_CHOICES = [
        ('eggs', _('On Eggs')),
        ('chicks', _('On Chicks')),
    ]

    date = models.DateField(help_text=_("Date of the expense"))
    hatchery = models.ForeignKey(
        Hatchery,
        on_delete=models.CASCADE,
        related_name='expenses',
        help_text=_("Hatchery this expense belongs to")
    )
    stage = models.CharField(
        max_length=10,
        choices=STAGE_CHOICES,
        default='eggs',
        help_text=_("Whether this expense was incurred on eggs or chicks")
    )
    expense_type = models.ForeignKey(
        ExpenseType,
        on_delete=models.PROTECT,
        related_name='expenses',
        help_text=_("Category of this expense")
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text=_("Expense amount")
    )
    is_active = models.BooleanField(
        default=True,
        help_text=_("Inactive expenses are excluded from totals elsewhere")
    )
    is_locked = models.BooleanField(
        default=False,
        help_text=_("Locked records can't be edited or deleted")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Hatchery Expense")
        verbose_name_plural = _("Hatchery Expenses")
        ordering = ['-date', 'hatchery__hatchery_name']

    def __str__(self):
        return f"{self.expense_type} - {self.amount} ({self.hatchery.hatchery_name}, {self.date})"
