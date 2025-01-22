from django.contrib import admin
from .models import ItemCategory, Warehouse, Item


@admin.register(ItemCategory)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'name')
    search_fields = ('name',)


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ('id', 'name')
    search_fields = ('name',)


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'item_code', 'description', 'category', 'warehouse', 'valuation_method', 
                    'usage', 'source', 'type', 'item_account', 'lot_serial_control')
    list_filter = ('category', 'warehouse', 'valuation_method', 'usage', 'source', 'type', 'item_account', 'lot_serial_control')
    search_fields = ('item_code', 'description', 'category__name', 'warehouse__name', 'hsn_code')
    autocomplete_fields = ('category', 'warehouse')
    fieldsets = (
        ("General Information", {
            'fields': ('item_code', 'description', 'category', 'warehouse')
        }),
        ("Specifications", {
            'fields': ('valuation_method', 'standard_cost_per_unit', 'storage_uom', 
                       'consumption_uom', 'usage', 'source', 'type', 'item_account', 'lot_serial_control')
        }),
        ("Additional Details", {
            'fields': ('kg_per_bag', 'hsn_code')
        }),
    )
    ordering = ('item_code',)
    list_per_page = 25
