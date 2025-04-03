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