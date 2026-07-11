from django.contrib import admin

from .models import ExpenseType, Hatcher, Hatchery, HatcheryExpense, Setter


@admin.register(Hatchery)
class HatcheryAdmin(admin.ModelAdmin):
    """Admin interface for Hatchery master records."""
    list_display = (
        'hatchery_name', 'operation_type', 'owner_name', 'contact',
        'email', 'state', 'is_active', 'is_locked',
    )
    search_fields = ('hatchery_name', 'owner_name', 'contact', 'email')
    list_filter = ('operation_type', 'state', 'is_active', 'is_locked')
    list_per_page = 20


@admin.register(Setter)
class SetterAdmin(admin.ModelAdmin):
    """Admin interface for Setter records."""
    list_display = ('hatchery', 'setter_no', 'capacity', 'is_active', 'is_locked')
    search_fields = ('setter_no', 'hatchery__hatchery_name')
    list_filter = ('hatchery', 'is_active', 'is_locked')
    list_per_page = 20


@admin.register(Hatcher)
class HatcherAdmin(admin.ModelAdmin):
    """Admin interface for Hatcher records."""
    list_display = ('hatchery', 'hatcher_no', 'capacity', 'is_active', 'is_locked')
    search_fields = ('hatcher_no', 'hatchery__hatchery_name')
    list_filter = ('hatchery', 'is_active', 'is_locked')
    list_per_page = 20


@admin.register(ExpenseType)
class ExpenseTypeAdmin(admin.ModelAdmin):
    """Admin interface for Expense Type records."""
    list_display = ('name', 'is_active', 'is_locked')
    search_fields = ('name',)
    list_filter = ('is_active', 'is_locked')
    list_per_page = 20


@admin.register(HatcheryExpense)
class HatcheryExpenseAdmin(admin.ModelAdmin):
    """Admin interface for Hatchery Expense records."""
    list_display = ('date', 'hatchery', 'stage', 'expense_type', 'amount', 'is_active', 'is_locked')
    search_fields = ('hatchery__hatchery_name', 'expense_type__name')
    list_filter = ('hatchery', 'stage', 'expense_type', 'is_active', 'is_locked')
    list_per_page = 20
