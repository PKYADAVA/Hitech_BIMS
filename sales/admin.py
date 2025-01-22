from django.contrib import admin
from .models import ContactType, CustomerGroup, SalesPriceMaster, Customer


@admin.register(CustomerGroup)
class CustomerGroupAdmin(admin.ModelAdmin):
    list_display = ('code', 'description', 'currency', 'control_account', 'advance_account')
    search_fields = ('code', 'description', 'currency')
    list_filter = ('currency',)


@admin.register(SalesPriceMaster)
class SalesPriceMasterAdmin(admin.ModelAdmin):
    list_display = ('item_category', 'item', 'price', 'date')
    search_fields = ('item__name', 'item_category__name')
    list_filter = ('item_category', 'date')
    date_hierarchy = 'date'


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
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

