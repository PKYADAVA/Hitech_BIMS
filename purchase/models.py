from django.db import models

class Supplier(models.Model):
    name = models.CharField(max_length=255, null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    place = models.CharField(max_length=100, null=True, blank=True)
    mobile = models.CharField(max_length=15, null=True, blank=True)
    contact_type = models.CharField(max_length=50, null=True, blank=True)
    pan = models.CharField(max_length=20, null=True, blank=True)
    supplier_group = models.CharField(max_length=100, null=True, blank=True)
    gstin = models.CharField(max_length=15, null=True, blank=True)
    state = models.CharField(max_length=50, null=True, blank=True)
    credit_term = models.IntegerField(null=True, blank=True)
    note = models.TextField(null=True, blank=True)

    def __str__(self):
        return self.name or "Unnamed Supplier"

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
    control_account = models.CharField(max_length=100, null=True, blank=True)
    prepayment_account = models.CharField(max_length=100, null=True, blank=True)

    def __str__(self):
        return self.code or "Unnamed Vendor Group"

class TermsConditions(models.Model):
    type = models.CharField(max_length=100, null=True, blank=True)
    condition = models.TextField(null=True, blank=True)

    def __str__(self):
        return self.type or "Unnamed Terms and Condition"
