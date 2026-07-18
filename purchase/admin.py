from django.contrib import admin
from import_export import resources
from import_export.admin import ImportExportModelAdmin
from import_export.fields import Field
from import_export.widgets import ForeignKeyWidget
from inventory.models import Item, Warehouse
from .models import Supplier, TaxMaster, VendorGroup, CreditTerm, GeneralPurchase, GeneralPurchaseItem


class GeneralPurchaseResource(resources.ModelResource):
    supplier = Field(
        attribute='supplier', column_name='supplier',
        widget=ForeignKeyWidget(Supplier, field='name'),
    )

    class Meta:
        model = GeneralPurchase


class GeneralPurchaseItemResource(resources.ModelResource):
    purchase = Field(
        attribute='purchase', column_name='purchase',
        widget=ForeignKeyWidget(GeneralPurchase, field='purchase_no'),
    )
    item = Field(
        attribute='item', column_name='item',
        widget=ForeignKeyWidget(Item, field='item_code'),
    )
    farm_warehouse = Field(
        attribute='farm_warehouse', column_name='farm_warehouse',
        widget=ForeignKeyWidget(Warehouse, field='name'),
    )

    class Meta:
        model = GeneralPurchaseItem


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

# Register the CreditTerm model
@admin.register(CreditTerm)
class CreditTermAdmin(ImportExportModelAdmin):
    list_display = [field.name for field in CreditTerm._meta.fields]  # Display all fields
    search_fields = ('term',)  # Add search field for credit term


# Register the GeneralPurchase model
@admin.register(GeneralPurchase)
class GeneralPurchaseAdmin(ImportExportModelAdmin):
    resource_classes = [GeneralPurchaseResource]
    list_display = [field.name for field in GeneralPurchase._meta.fields]
    list_filter = ('date', 'supplier')
    search_fields = ('purchase_no', 'bill_no', 'supplier__name')
    date_hierarchy = 'date'
    autocomplete_fields = ['supplier']

@admin.register(GeneralPurchaseItem)
class GeneralPurchaseItemAdmin(ImportExportModelAdmin):
    resource_classes = [GeneralPurchaseItemResource]
    list_display = ['id', 'purchase', 'item', 'sent_qty', 'rcv_qty', 'rate', 'amount']
    list_filter = ('farm_warehouse',)
    search_fields = ('purchase__purchase_no', 'item__item_code')
    autocomplete_fields = ['purchase', 'item']