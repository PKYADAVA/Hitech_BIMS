from django.contrib import admin
from import_export.admin import ImportExportModelAdmin
from .models import Supplier, TaxMaster, VendorGroup, TermsConditions, CreditTerm, PurchaseOrder,PurchaseOrderLineItem


@admin.register(Supplier)
class SupplierAdmin(ImportExportModelAdmin):
    list_display = ('name', 'place', 'mobile', 'gstin', 'state', 'credit_term')
    search_fields = ('name', 'place', 'mobile', 'gstin')
    list_filter = ('state', 'supplier_group')

@admin.register(TaxMaster)
class TaxMasterAdmin(ImportExportModelAdmin):
    list_display = ('tax_code', 'tax_percentage', 'rule', 'coa')
    search_fields = ('tax_code', 'description')
    list_filter = ('rule',)

@admin.register(VendorGroup)
class VendorGroupAdmin(ImportExportModelAdmin):
    list_display = ('code', 'currency', 'control_account', 'prepayment_account')
    search_fields = ('code', 'description')
    list_filter = ('currency',)

@admin.register(TermsConditions)
class TermsConditionsAdmin(ImportExportModelAdmin):
    list_display = ('type', 'condition')
    search_fields = ('type',)

# Register the CreditTerm model
@admin.register(CreditTerm)
class CreditTermAdmin(ImportExportModelAdmin):
    list_display = [field.name for field in CreditTerm._meta.fields]  # Display all fields
    search_fields = ('term',)  # Add search field for credit term


# Register the PurchaseOrder model
@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(ImportExportModelAdmin):
    list_display = [field.name for field in PurchaseOrder._meta.fields]
    list_filter = ('date', 'vendor', 'credit_term')
    search_fields = ('invoice', 'vendor__code')
    date_hierarchy = 'date'
    autocomplete_fields = ['vendor', 'credit_term']

@admin.register(PurchaseOrderLineItem)
class PurchaseOrderLineItemAdmin(ImportExportModelAdmin):
    list_display = ['id', 'purchase_order', 'qty_sent', 'qty_received', 'price_per_unit']
    list_filter = ('purchase_order', 'warehouse')
    search_fields = ('code', 'purchase_order__invoice', 'category')
    autocomplete_fields = ['purchase_order']