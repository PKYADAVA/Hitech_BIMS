from django.db import models

from inventory.models import Warehouse

# Create your models here.
class FinancialYear(models.Model):
    """
    Model to manage financial years.
    """
    start_date = models.DateField(help_text="Start date of the financial year")
    end_date = models.DateField(help_text="End date of the financial year")
    is_active = models.BooleanField(default=False, help_text="Is this the active financial year?")
    created_at = models.DateTimeField(auto_now_add=True, help_text="Record created at")
    updated_at = models.DateTimeField(auto_now=True, help_text="Last record update time")

    def __str__(self):
        return f"FY {self.start_date.year}-{self.end_date.year}"

    def clean(self):
        """
        Ensure that end_date is later than start_date and only one active financial year exists.
        """
        from django.core.exceptions import ValidationError

        if self.end_date <= self.start_date:
            raise ValidationError("End date must be after the start date.")

        if self.is_active:
            if FinancialYear.objects.filter(is_active=True).exclude(pk=self.pk).exists():
                raise ValidationError("There can only be one active financial year.")

    def save(self, *args, **kwargs):
        # Enforce business logic
        if self.is_active:
            FinancialYear.objects.exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['-start_date']
        verbose_name = "Financial Year"
        verbose_name_plural = "Financial Years"


class Schedule(models.Model):
    """
    Model to define the schedule used in the chart of accounts.
    """

    code = models.CharField(max_length=20, unique=True, help_text="Unique code for the account")
    name = models.CharField(max_length=100, unique=True, help_text="Name of the schedule")
    description = models.TextField(blank=True, null=True, help_text="Details about the schedule")
    created_at = models.DateTimeField(auto_now_add=True, help_text="Record created at")
    updated_at = models.DateTimeField(auto_now=True, help_text="Last updated at")

    def __str__(self):
        return self.name


class ChartOfAccount(models.Model):
    """
    Model to manage the Chart of Accounts.
    """
    TYPE_CHOICES = [
        ('Asset', 'Asset'),
        ('Liability', 'Liability'),
        ('Equity', 'Equity'),
        ('Revenue', 'Revenue'),
        ('Expense', 'Expense'),
    ]
    STATUS_CHOICES = [
        ('Active', 'Active'),
        ('Inactive', 'Inactive'),
    ]

    code = models.CharField(max_length=20, unique=True, help_text="Unique code for the account")
    description = models.CharField(max_length=255, help_text="Description of the account")
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, help_text="Type of the account")
    control_type = models.CharField(max_length=100, blank=True, null=True, help_text="Control type for the account")
    schedule = models.ForeignKey(Schedule, on_delete=models.SET_NULL, null=True, blank=True, help_text="Associated schedule")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='Active', help_text="Status of the account")
    created_at = models.DateTimeField(auto_now_add=True, help_text="Record created at")
    updated_at = models.DateTimeField(auto_now=True, help_text="Last updated at")

    def __str__(self):
        return f"{self.code} - {self.description}"

    class Meta:
        ordering = ['code']
        verbose_name = "Chart of Account"
        verbose_name_plural = "Chart of Accounts"        

class BankCode(models.Model):
    """
    Model to manage bank and cash codes.
    """

    bank_code = models.CharField(max_length=20, unique=True, help_text="Unique code for the bank")
    bank_name = models.CharField(max_length=255, help_text="Name of the bank")
    sector = models.ForeignKey( Warehouse, max_length=20, on_delete=models.SET_NULL, null=True, blank=True, help_text="Sector of the bank")
    micr = models.CharField(max_length=15, blank=True, null=True, help_text="MICR code of the bank")
    address = models.TextField(help_text="Address of the bank")
    email = models.EmailField(blank=True, null=True, help_text="Email address of the bank")
    phone = models.CharField(max_length=20, blank=True, null=True, help_text="Phone number of the bank")
    fax = models.CharField(max_length=20, blank=True, null=True, help_text="Fax number of the bank")
    contact_person = models.CharField(max_length=100, blank=True, null=True, help_text="Contact person at the bank")
    created_at = models.DateTimeField(auto_now_add=True, help_text="Record created at")
    updated_at = models.DateTimeField(auto_now=True, help_text="Last updated at")

    def __str__(self):
        return f"{self.bank_code} - {self.bank_name}"

    class Meta:
        ordering = ['bank_name']
        verbose_name = "Bank Code"
        verbose_name_plural = "Bank Codes"        