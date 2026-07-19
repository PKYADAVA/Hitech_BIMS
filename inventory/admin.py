from django.contrib import admin
from import_export import resources
from import_export.admin import ImportExportModelAdmin
from import_export.fields import Field
from import_export.widgets import ForeignKeyWidget, ManyToManyWidget
from .models import ItemCategory, Warehouse, Item


class ItemResource(resources.ModelResource):
    category = Field(
        attribute='category', column_name='category',
        widget=ForeignKeyWidget(ItemCategory, field='name'),
    )
    warehouse = Field(
        attribute='warehouse', column_name='warehouse',
        widget=ManyToManyWidget(Warehouse, field='name'),
    )

    class Meta:
        model = Item


@admin.register(ItemCategory)
class CategoryAdmin(ImportExportModelAdmin):
    list_display = ('id', 'name')
    search_fields = ('name',)


@admin.register(Warehouse)
class WarehouseAdmin(ImportExportModelAdmin):
    list_display = ('id', 'name')
    search_fields = ('name',)


@admin.register(Item)
class ItemAdmin(ImportExportModelAdmin):
    resource_classes = [ItemResource]
    list_display = ('id', 'item_code', 'description', 'category', 'warehouse_list', 'valuation_method',
                    'usage', 'source', 'type', 'item_account', 'lot_serial_control')
    list_filter = ('category', 'warehouse', 'valuation_method', 'usage', 'source', 'type', 'item_account', 'lot_serial_control')
    search_fields = ('item_code', 'description', 'category__name', 'warehouse__name', 'hsn_code')
    autocomplete_fields = ('category',)
    filter_horizontal = ('warehouse',)

    def warehouse_list(self, obj):
        return ", ".join(w.name for w in obj.warehouse.all())
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
