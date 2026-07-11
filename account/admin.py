from django.contrib import admin
from import_export.admin import ImportExportModelAdmin
from django.utils.translation import gettext_lazy as _
from .models import FinancialYear, Schedule, ChartOfAccount, BankCode, CoACategory


@admin.register(CoACategory)
class CoACategoryAdmin(ImportExportModelAdmin):
    """
    Admin configuration for CoACategory model.
    """
    list_display = ('code', 'type', 'description', 'is_active', 'is_locked', 'created_at')
    list_filter = ('type', 'is_active', 'is_locked')
    search_fields = ('code', 'description')
    ordering = ('code',)
    list_per_page = 20
    readonly_fields = ('code', 'created_at', 'updated_at')

    fieldsets = (
        (None, {
            'fields': ('code', 'type', 'description', 'is_active', 'is_locked')
        }),
        (_('Timestamps'), {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(FinancialYear)
class FinancialYearAdmin(ImportExportModelAdmin):
    """
    Admin configuration for FinancialYear model.
    
    Provides a clean interface for managing financial years with proper validation
    and display of important fields.
    """
    list_display = ('start_date', 'end_date', 'is_active', 'created_at')
    list_filter = ('is_active', 'start_date', 'end_date')
    search_fields = ('start_date', 'end_date')
    ordering = ('-start_date',)
    list_per_page = 20
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        (None, {
            'fields': ('start_date', 'end_date', 'is_active')
        }),
        (_('Timestamps'), {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Schedule)
class ScheduleAdmin(ImportExportModelAdmin):
    """
    Admin configuration for Schedule model.
    
    Provides a clean interface for managing schedules with proper validation
    and display of important fields.
    """
    list_display = ('code', 'name', 'description', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('code', 'name', 'description')
    ordering = ('code',)
    list_per_page = 20
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        (None, {
            'fields': ('code', 'name', 'description')
        }),
        (_('Timestamps'), {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(ChartOfAccount)
class ChartOfAccountAdmin(ImportExportModelAdmin):
    """
    Admin configuration for ChartOfAccount model.
    
    Provides a clean interface for managing chart of accounts with proper validation
    and display of important fields.
    """
    list_display = ('code', 'description', 'type', 'control_type', 'schedule', 'status', 'created_at')
    list_filter = ('type', 'status', 'schedule', 'created_at')
    search_fields = ('code', 'description', 'control_type')
    ordering = ('code',)
    list_per_page = 20
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        (None, {
            'fields': ('code', 'description', 'type', 'control_type', 'schedule', 'status')
        }),
        (_('Timestamps'), {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(BankCode)
class BankCodeAdmin(ImportExportModelAdmin):
    """
    Admin configuration for BankCode model.
    
    Provides a clean interface for managing bank codes with proper validation
    and display of important fields.
    """
    list_display = ('bank_code', 'bank_name', 'sector', 'micr', 'contact_person', 'created_at')
    list_filter = ('sector', 'created_at')
    search_fields = ('bank_code', 'bank_name', 'micr', 'contact_person')
    ordering = ('bank_name',)
    list_per_page = 20
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        (None, {
            'fields': ('bank_code', 'bank_name', 'sector', 'micr')
        }),
        (_('Contact Information'), {
            'fields': ('address', 'email', 'phone', 'fax', 'contact_person')
        }),
        (_('Timestamps'), {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
