from django.contrib import admin
from import_export.admin import ImportExportModelAdmin
from .models import HatchSetting, HatchEggIntake, HatchHatcherOutput, HatchSalesLine


class HatchEggIntakeInline(admin.TabularInline):
    model = HatchEggIntake
    extra = 0


class HatchHatcherOutputInline(admin.TabularInline):
    model = HatchHatcherOutput
    extra = 0


class HatchSalesLineInline(admin.TabularInline):
    model = HatchSalesLine
    extra = 0


@admin.register(HatchSetting)
class HatchSettingAdmin(ImportExportModelAdmin):
    """
    Admin interface for HatchSetting (hatch register & sales sheet) records.
    """
    list_display = (
        'id', 'setting_no', 'batch_flock_no', 'supplier_name',
        'received_date', 'setting_date', 'hatch_date',
    )
    search_fields = ('setting_no', 'batch_flock_no', 'supplier_name', 'primary_machine_nos')
    list_filter = ('supplier_name', 'setting_date')
    list_per_page = 20
    ordering = ('-setting_date',)
    inlines = [HatchEggIntakeInline, HatchHatcherOutputInline, HatchSalesLineInline]
    fieldsets = (
        ('Hatch Lot & Timeline Identification', {
            'fields': (
                'setting_no', 'batch_flock_no', 'supplier_name', 'primary_machine_nos',
                'received_date', 'received_time', 'setting_date', 'transfer_date',
                'hatch_date', 'push_time',
            )
        }),
        ('Egg Intake Totals', {
            'fields': ('received_qty', 'breakage_qty', 'crack_qty', 'setting_qty')
        }),
        ('Environmental & Post-Hatch Consumables Log', {
            'fields': (
                'setter_temperature', 'setter_humidity', 'hatcher_temperature',
                'hatcher_humidity', 'avg_chick_weight', 'medicine_vaccine',
                'packing_boxes_used', 'remarks',
            )
        }),
        ('Sign-off', {
            'fields': ('prepared_by', 'verified_by')
        }),
    )
