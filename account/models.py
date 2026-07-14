from django.db import models
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from inventory.models import Warehouse


class FinancialYear(models.Model):
    """
    Model to manage financial years.
    
    This model represents a financial year with start and end dates.
    Only one financial year can be active at a time.
    """
    start_date = models.DateField(
        help_text=_("Start date of the financial year")
    )
    end_date = models.DateField(
        help_text=_("End date of the financial year")
    )
    is_active = models.BooleanField(
        default=False, 
        help_text=_("Is this the active financial year?")
    )
    created_at = models.DateTimeField(
        auto_now_add=True, 
        help_text=_("Record created at")
    )
    updated_at = models.DateTimeField(
        auto_now=True, 
        help_text=_("Last record update time")
    )

    def __str__(self):
        return f"FY {self.start_date.year}-{self.end_date.year}"

    def clean(self):
        """
        Ensure that end_date is later than start_date and only one active financial year exists.
        """
        if self.end_date <= self.start_date:
            raise ValidationError(_("End date must be after the start date."))

        if self.is_active:
            if FinancialYear.objects.filter(is_active=True).exclude(pk=self.pk).exists():
                raise ValidationError(_("There can only be one active financial year."))

    def save(self, *args, **kwargs):
        """
        Override save method to ensure only one active financial year exists.
        """
        if self.is_active:
            FinancialYear.objects.exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['-start_date']
        verbose_name = _("Financial Year")
        verbose_name_plural = _("Financial Years")
        indexes = [
            models.Index(fields=['is_active']),
            models.Index(fields=['start_date', 'end_date']),
        ]


class Schedule(models.Model):
    """
    Model to define the schedule used in the chart of accounts.
    
    Schedules are used to categorize accounts in the chart of accounts.
    """
    code = models.CharField(
        max_length=20, 
        unique=True, 
        help_text=_("Unique code for the account")
    )
    name = models.CharField(
        max_length=100, 
        unique=True, 
        help_text=_("Name of the schedule")
    )
    description = models.TextField(
        blank=True, 
        null=True, 
        help_text=_("Details about the schedule")
    )
    created_at = models.DateTimeField(
        auto_now_add=True, 
        help_text=_("Record created at")
    )
    updated_at = models.DateTimeField(
        auto_now=True, 
        help_text=_("Last updated at")
    )

    def __str__(self):
        return f"{self.code} - {self.name}"

    class Meta:
        ordering = ['code']
        verbose_name = _("Schedule")
        verbose_name_plural = _("Schedules")
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['name']),
        ]


class CoACategory(models.Model):
    """High-level sector grouping (Asset/Liability/etc.) used to organize the chart of accounts."""
    TYPE_CHOICES = [
        ('Asset', _('Asset')),
        ('Capital', _('Capital')),
        ('Expense', _('Expense')),
        ('Liability', _('Liability')),
        ('Revenue', _('Revenue')),
    ]

    code = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
        blank=True,
        help_text=_("Auto-generated code for this category")
    )
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, help_text=_("Sector this category belongs to"))
    description = models.CharField(max_length=150, help_text=_("Name of the category"))
    is_active = models.BooleanField(default=True, help_text=_("Inactive categories are hidden from selection elsewhere"))
    is_locked = models.BooleanField(default=False, help_text=_("Locked records can't be edited or deleted"))
    created_at = models.DateTimeField(auto_now_add=True, help_text=_("Record created at"))
    updated_at = models.DateTimeField(auto_now=True, help_text=_("Last updated at"))

    def __str__(self):
        return f"{self.code} - {self.description}"

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.code:
            self.code = self._next_code()
            super().save(update_fields=['code'])

    @classmethod
    def _next_code(cls):
        """CAT-<n+1>, where n is the highest numeric suffix already in use.

        Not simply based on this row's own pk: categories are also bulk
        imported from CSV/Excel with pre-assigned codes that have gaps, so a
        pk-based code would collide with an already-imported higher number.
        """
        import re
        max_num = 0
        for existing_code in cls.objects.values_list('code', flat=True):
            match = re.match(r'CAT-(\d+)$', existing_code or '')
            if match:
                max_num = max(max_num, int(match.group(1)))
        return f"CAT-{max_num + 1:04d}"

    class Meta:
        ordering = ['code']
        verbose_name = _("CoA Category")
        verbose_name_plural = _("CoA Categories")
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['type']),
        ]


class ChartOfAccount(models.Model):
    """
    Model to manage the Chart of Accounts.
    
    This model represents accounts in the accounting system.
    """
    TYPE_CHOICES = [
        ('Asset', _('Asset')),
        ('Liability', _('Liability')),
        ('Equity', _('Equity')),
        ('Revenue', _('Revenue')),
        ('Expense', _('Expense')),
    ]
    STATUS_CHOICES = [
        ('Active', _('Active')),
        ('Inactive', _('Inactive')),
    ]

    code = models.CharField(
        max_length=20, 
        unique=True, 
        help_text=_("Unique code for the account")
    )
    description = models.CharField(
        max_length=255, 
        help_text=_("Description of the account")
    )
    type = models.CharField(
        max_length=20, 
        choices=TYPE_CHOICES, 
        help_text=_("Type of the account")
    )
    control_type = models.CharField(
        max_length=100, 
        blank=True, 
        null=True, 
        help_text=_("Control type for the account")
    )
    schedule = models.ForeignKey(
        Schedule, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='accounts',
        help_text=_("Associated schedule")
    )
    status = models.CharField(
        max_length=10, 
        choices=STATUS_CHOICES, 
        default='Active', 
        help_text=_("Status of the account")
    )
    created_at = models.DateTimeField(
        auto_now_add=True, 
        help_text=_("Record created at")
    )
    updated_at = models.DateTimeField(
        auto_now=True, 
        help_text=_("Last updated at")
    )

    def __str__(self):
        return f"{self.code} - {self.description}"

    class Meta:
        ordering = ['code']
        verbose_name = _("Chart of Account")
        verbose_name_plural = _("Chart of Accounts")
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['type']),
            models.Index(fields=['status']),
        ]


class BankCode(models.Model):
    """
    Model to manage bank and cash codes.
    
    This model represents banks and their details.
    """
    bank_code = models.CharField(
        max_length=20, 
        unique=True, 
        help_text=_("Unique code for the bank")
    )
    bank_name = models.CharField(
        max_length=255, 
        help_text=_("Name of the bank")
    )
    sector = models.ForeignKey(
        Warehouse, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='banks',
        help_text=_("Sector of the bank")
    )
    micr = models.CharField(
        max_length=15, 
        blank=True, 
        null=True, 
        help_text=_("MICR code of the bank")
    )
    address = models.TextField(
        help_text=_("Address of the bank")
    )
    email = models.EmailField(
        blank=True, 
        null=True, 
        help_text=_("Email address of the bank")
    )
    phone = models.CharField(
        max_length=20, 
        blank=True, 
        null=True, 
        validators=[
            RegexValidator(
                regex=r'^\+?1?\d{9,15}$',
                message=_("Phone number must be entered in the format: '+999999999'. Up to 15 digits allowed.")
            )
        ],
        help_text=_("Phone number of the bank")
    )
    fax = models.CharField(
        max_length=20, 
        blank=True, 
        null=True, 
        help_text=_("Fax number of the bank")
    )
    contact_person = models.CharField(
        max_length=100, 
        blank=True, 
        null=True, 
        help_text=_("Contact person at the bank")
    )
    created_at = models.DateTimeField(
        auto_now_add=True, 
        help_text=_("Record created at")
    )
    updated_at = models.DateTimeField(
        auto_now=True, 
        help_text=_("Last updated at")
    )

    def __str__(self):
        return f"{self.bank_code} - {self.bank_name}"

    class Meta:
        ordering = ['bank_name']
        verbose_name = _("Bank Code")
        verbose_name_plural = _("Bank Codes")
        indexes = [
            models.Index(fields=['bank_code']),
            models.Index(fields=['bank_name']),
        ]


class CompanyProfile(models.Model):
    """Single record holding the company's own letterhead/bank details, used on printed documents."""
    name = models.CharField(max_length=255, default="Company Name")
    address = models.TextField(blank=True)
    state = models.CharField(max_length=50, blank=True, help_text=_("Company's own state, for GST place-of-supply comparisons"))
    mobile = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    gstin = models.CharField(max_length=15, blank=True)
    pan = models.CharField(max_length=10, blank=True)
    bank_name = models.CharField(max_length=100, blank=True)
    bank_account_no = models.CharField(max_length=50, blank=True)
    ifsc_code = models.CharField(max_length=20, blank=True)
    bank_branch = models.CharField(max_length=100, blank=True)

    class Meta:
        verbose_name = _("Company Profile")
        verbose_name_plural = _("Company Profile")

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj


class TermsConditions(models.Model):
    class PartyType(models.TextChoices):
        SUPPLIER = "Supplier", _("Supplier")
        CUSTOMER = "Customer", _("Customer")

    type = models.CharField(max_length=100, null=True, blank=True)
    party_type = models.CharField(max_length=20, choices=PartyType.choices, default=PartyType.CUSTOMER)
    condition = models.TextField(null=True, blank=True)

    def __str__(self):
        return self.type or "Unnamed Terms and Condition"