from django.contrib import admin
from .models import Supplier, TaxMaster, VendorGroup, TermsConditions, CreditTerm, PurchaseOrder,PurchaseOrderLineItem


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

# Register the CreditTerm model
@admin.register(CreditTerm)
class CreditTermAdmin(admin.ModelAdmin):
    list_display = [field.name for field in CreditTerm._meta.fields]  # Display all fields
    search_fields = ('term',)  # Add search field for credit term


# Register the PurchaseOrder model
@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = [field.name for field in PurchaseOrder._meta.fields]
    list_filter = ('date', 'vendor', 'credit_term')
    search_fields = ('invoice', 'vendor__code')
    date_hierarchy = 'date'
    autocomplete_fields = ['vendor', 'credit_term']

@admin.register(PurchaseOrderLineItem)
class PurchaseOrderLineItemAdmin(admin.ModelAdmin):
    list_display = ['id', 'purchase_order', 'category', 'code', 'qty_sent', 'qty_received', 'price_per_unit']
    list_filter = ('purchase_order', 'category', 'warehouse')
    search_fields = ('code', 'purchase_order__invoice', 'category')
    autocomplete_fields = ['purchase_order']