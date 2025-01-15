from django.contrib import admin
from .models import Supplier, TaxMaster, VendorGroup, TermsConditions

@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'place', 'mobile', 'gstin', 'state', 'credit_term')
    search_fields = ('name', 'place', 'mobile', 'gstin')
    list_filter = ('state', 'supplier_group')

@admin.register(TaxMaster)
class TaxMasterAdmin(admin.ModelAdmin):
    list_display = ('tax_code', 'tax_percentage', 'rule', 'coa')
    search_fields = ('tax_code', 'description')
    list_filter = ('rule',)

@admin.register(VendorGroup)
class VendorGroupAdmin(admin.ModelAdmin):
    list_display = ('code', 'currency', 'control_account', 'prepayment_account')
    search_fields = ('code', 'description')
    list_filter = ('currency',)

@admin.register(TermsConditions)
class TermsConditionsAdmin(admin.ModelAdmin):
    list_display = ('type', 'condition')
    search_fields = ('type',)
