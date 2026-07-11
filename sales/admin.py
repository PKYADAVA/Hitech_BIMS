from django.contrib import admin
from import_export import resources
from import_export.admin import ImportExportModelAdmin
from import_export.fields import Field
from import_export.widgets import ForeignKeyWidget
from inventory.models import Item, ItemCategory
from purchase.models import CreditTerm, VendorGroup
from .models import CustomerGroup, SalesPriceMaster, Customer


class SalesPriceMasterResource(resources.ModelResource):
    item_category = Field(
        attribute='item_category', column_name='item_category',
        widget=ForeignKeyWidget(ItemCategory, field='name'),
    )
    item = Field(
        attribute='item', column_name='item',
        widget=ForeignKeyWidget(Item, field='item_code'),
    )

    class Meta:
        model = SalesPriceMaster


class CustomerResource(resources.ModelResource):
    customer_group = Field(
        attribute='customer_group', column_name='customer_group',
        widget=ForeignKeyWidget(CustomerGroup, field='code'),
    )
    supplier_group = Field(
        attribute='supplier_group', column_name='supplier_group',
        widget=ForeignKeyWidget(VendorGroup, field='code'),
    )
    credit_term = Field(
        attribute='credit_term', column_name='credit_term',
        widget=ForeignKeyWidget(CreditTerm, field='term'),
    )

    class Meta:
        model = Customer


@admin.register(CustomerGroup)
class CustomerGroupAdmin(ImportExportModelAdmin):
    list_display = ('code', 'description', 'currency', 'control_account', 'advance_account')
    search_fields = ('code', 'description', 'currency')
    list_filter = ('currency',)


@admin.register(SalesPriceMaster)
class SalesPriceMasterAdmin(ImportExportModelAdmin):
    resource_classes = [SalesPriceMasterResource]
    list_display = ('item_category', 'item', 'price', 'date')
    search_fields = ('item__name', 'item_category__name')
    list_filter = ('item_category', 'date')
    date_hierarchy = 'date'


@admin.register(Customer)
class CustomerAdmin(ImportExportModelAdmin):
    resource_classes = [CustomerResource]
    list_display = ('name', 'phone', 'mobile', 'contact_type', 'customer_group', 'supplier_group', 'credit_limit', 'state')
    search_fields = ('name', 'phone', 'mobile', 'gstin', 'state')
    list_filter = ('contact_type', 'state', 'customer_group', 'supplier_group')
    readonly_fields = ('gstin',)
    fieldsets = (
        (None, {
            'fields': ('name', 'address', 'place', 'phone', 'mobile', 'contact_type')
        }),
        ('Additional Information', {
            'fields': ('pan_tin', 'customer_group', 'supplier_group', 'credit_limit', 'credit_term', 'gstin', 'state', 'note', 'supplier_address'),
        }),
    )

