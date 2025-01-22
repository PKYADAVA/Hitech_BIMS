from django.contrib import admin
from .models import FinancialYear, Schedule, ChartOfAccount, BankCode


@admin.register(FinancialYear)
class FinancialYearAdmin(admin.ModelAdmin):
    list_display = ('id', 'start_date', 'end_date', 'is_active', 'created_at', 'updated_at')
    list_filter = ('is_active',)
    search_fields = ('start_date', 'end_date')
    ordering = ('-start_date',)
    list_per_page = 25
    fieldsets = (
        ("Financial Year Details", {
            'fields': ('start_date', 'end_date', 'is_active')
        }),
        ("Timestamps", {
            'fields': ('created_at', 'updated_at')
        }),
    )
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Schedule)
class ScheduleAdmin(admin.ModelAdmin):
    list_display = ('id', 'code', 'name', 'created_at', 'updated_at')
    search_fields = ('code', 'name')
    ordering = ('code',)
    list_per_page = 25
    fieldsets = (
        ("Schedule Details", {
            'fields': ('code', 'name', 'description')
        }),
        ("Timestamps", {
            'fields': ('created_at', 'updated_at')
        }),
    )
    readonly_fields = ('created_at', 'updated_at')


@admin.register(ChartOfAccount)
class ChartOfAccountAdmin(admin.ModelAdmin):
    list_display = ('id', 'code', 'description', 'type', 'status', 'schedule', 'created_at', 'updated_at')
    list_filter = ('type', 'status')
    search_fields = ('code', 'description', 'schedule__name')
    autocomplete_fields = ('schedule',)
    ordering = ('code',)
    list_per_page = 25
    fieldsets = (
        ("Account Details", {
            'fields': ('code', 'description', 'type', 'status')
        }),
        ("Control and Schedule", {
            'fields': ('control_type', 'schedule')
        }),
        ("Timestamps", {
            'fields': ('created_at', 'updated_at')
        }),
    )
    readonly_fields = ('created_at', 'updated_at')


@admin.register(BankCode)
class BankCodeAdmin(admin.ModelAdmin):
    list_display = ('id', 'bank_code', 'bank_name', 'sector', 'email', 'phone', 'contact_person', 'created_at', 'updated_at')
    list_filter = ('sector',)
    search_fields = ('bank_code', 'bank_name', 'sector__name', 'email', 'phone')
    autocomplete_fields = ('sector',)
    ordering = ('bank_name',)
    list_per_page = 25
    fieldsets = (
        ("Bank Details", {
            'fields': ('bank_code', 'bank_name', 'sector')
        }),
        ("Contact Information", {
            'fields': ('micr', 'address', 'email', 'phone', 'fax', 'contact_person')
        }),
        ("Timestamps", {
            'fields': ('created_at', 'updated_at')
        }),
    )
    readonly_fields = ('created_at', 'updated_at')
