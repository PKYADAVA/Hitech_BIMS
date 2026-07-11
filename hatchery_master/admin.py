from django.contrib import admin
from import_export import resources
from import_export.admin import ImportExportModelAdmin
from import_export.fields import Field
from import_export.widgets import ForeignKeyWidget

from .models import ExpenseType, Hatcher, Hatchery, HatcheryExpense, Setter


# ---------------------------------------------------------------- #
# Import/export resources - override FK fields to resolve/display
# by a human-readable name instead of the numeric database id, so
# CSVs can be written and read by hand.
# ---------------------------------------------------------------- #

class SetterResource(resources.ModelResource):
    hatchery = Field(
        attribute='hatchery', column_name='hatchery',
        widget=ForeignKeyWidget(Hatchery, field='hatchery_name'),
    )

    class Meta:
        model = Setter


class HatcherResource(resources.ModelResource):
    hatchery = Field(
        attribute='hatchery', column_name='hatchery',
        widget=ForeignKeyWidget(Hatchery, field='hatchery_name'),
    )

    class Meta:
        model = Hatcher


class HatcheryExpenseResource(resources.ModelResource):
    hatchery = Field(
        attribute='hatchery', column_name='hatchery',
        widget=ForeignKeyWidget(Hatchery, field='hatchery_name'),
    )
    expense_type = Field(
        attribute='expense_type', column_name='expense_type',
        widget=ForeignKeyWidget(ExpenseType, field='name'),
    )

    class Meta:
        model = HatcheryExpense


@admin.register(Hatchery)
class HatcheryAdmin(ImportExportModelAdmin):
    """Admin interface for Hatchery master records."""
    list_display = (
        'hatchery_name', 'operation_type', 'owner_name', 'contact',
        'email', 'state', 'is_active', 'is_locked',
    )
    search_fields = ('hatchery_name', 'owner_name', 'contact', 'email')
    list_filter = ('operation_type', 'state', 'is_active', 'is_locked')
    list_per_page = 20


@admin.register(Setter)
class SetterAdmin(ImportExportModelAdmin):
    """Admin interface for Setter records."""
    resource_classes = [SetterResource]
    list_display = ('hatchery', 'setter_no', 'capacity', 'is_active', 'is_locked')
    search_fields = ('setter_no', 'hatchery__hatchery_name')
    list_filter = ('hatchery', 'is_active', 'is_locked')
    list_per_page = 20


@admin.register(Hatcher)
class HatcherAdmin(ImportExportModelAdmin):
    """Admin interface for Hatcher records."""
    resource_classes = [HatcherResource]
    list_display = ('hatchery', 'hatcher_no', 'capacity', 'is_active', 'is_locked')
    search_fields = ('hatcher_no', 'hatchery__hatchery_name')
    list_filter = ('hatchery', 'is_active', 'is_locked')
    list_per_page = 20


@admin.register(ExpenseType)
class ExpenseTypeAdmin(ImportExportModelAdmin):
    """Admin interface for Expense Type records."""
    list_display = ('name', 'is_active', 'is_locked')
    search_fields = ('name',)
    list_filter = ('is_active', 'is_locked')
    list_per_page = 20


@admin.register(HatcheryExpense)
class HatcheryExpenseAdmin(ImportExportModelAdmin):
    """Admin interface for Hatchery Expense records."""
    resource_classes = [HatcheryExpenseResource]
    list_display = ('date', 'hatchery', 'stage', 'expense_type', 'amount', 'is_active', 'is_locked')
    search_fields = ('hatchery__hatchery_name', 'expense_type__name')
    list_filter = ('hatchery', 'stage', 'expense_type', 'is_active', 'is_locked')
    list_per_page = 20
