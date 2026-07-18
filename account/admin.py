from django.contrib import admin
from import_export import resources
from import_export.admin import ImportExportModelAdmin
from import_export.fields import Field
from import_export.widgets import ForeignKeyWidget
from django.utils.translation import gettext_lazy as _
from inventory.models import Warehouse
from .models import (
    AccountAuditLog,
    AccountGroup,
    AccountType,
    BankCode,
    ChartOfAccount,
    CoACategory,
    CoAGenerationLog,
    CoATemplate,
    CoATemplateAccount,
    CostCenter,
    FinancialYear,
    NarrationSettings,
    Schedule,
    TermsConditions,
    Voucher,
    VoucherLine,
)


class ChartOfAccountResource(resources.ModelResource):
    schedule = Field(
        attribute='schedule', column_name='schedule',
        widget=ForeignKeyWidget(Schedule, field='code'),
    )

    class Meta:
        model = ChartOfAccount


class BankCodeResource(resources.ModelResource):
    sector = Field(
        attribute='sector', column_name='sector',
        widget=ForeignKeyWidget(Warehouse, field='name'),
    )

    class Meta:
        model = BankCode


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
    resource_classes = [ChartOfAccountResource]
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
    resource_classes = [BankCodeResource]
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


@admin.register(TermsConditions)
class TermsConditionsAdmin(ImportExportModelAdmin):
    list_display = ('type', 'party_type', 'condition')
    list_filter = ('party_type',)
    search_fields = ('type',)


@admin.register(AccountType)
class AccountTypeAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'normal_balance', 'report', 'code_range_start', 'code_range_end', 'is_system')
    ordering = ('sort_order',)

    def get_readonly_fields(self, request, obj=None):
        # System types keep their identity; only ranges/order are tunable.
        if obj and obj.is_system:
            return ('code', 'name', 'is_system')
        return ()

    def has_delete_permission(self, request, obj=None):
        if obj and obj.is_system:
            return False
        return super().has_delete_permission(request, obj)


@admin.register(AccountGroup)
class AccountGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'account_type', 'is_system', 'is_active')
    list_filter = ('account_type', 'is_system', 'is_active')
    search_fields = ('name',)


class CoATemplateAccountInline(admin.TabularInline):
    model = CoATemplateAccount
    fields = ('account_code', 'account_name', 'account_type', 'account_group', 'parent', 'is_group', 'system_role', 'sort_order')
    extra = 0
    show_change_link = True


@admin.register(CoATemplate)
class CoATemplateAdmin(admin.ModelAdmin):
    list_display = ('template_name', 'industry', 'country', 'currency', 'status', 'created_date')
    list_filter = ('industry', 'country', 'status')
    search_fields = ('template_name', 'description')
    inlines = [CoATemplateAccountInline]


@admin.register(CoAGenerationLog)
class CoAGenerationLogAdmin(admin.ModelAdmin):
    list_display = ('company', 'template', 'status', 'started_at', 'finished_at', 'created_by')
    list_filter = ('status',)
    readonly_fields = ('company', 'template', 'status', 'summary', 'error', 'started_at', 'finished_at', 'created_by')

    def has_add_permission(self, request):
        return False


@admin.register(AccountAuditLog)
class AccountAuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'action', 'account', 'user', 'ip_address')
    list_filter = ('action',)
    search_fields = ('account__code', 'account__description', 'reason')
    readonly_fields = ('company', 'account', 'action', 'old_values', 'new_values', 'reason', 'ip_address', 'user', 'timestamp')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False  # audit trail is immutable


@admin.register(CostCenter)
class CostCenterAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'kind', 'company', 'parent', 'is_active')
    list_filter = ('kind', 'is_active')
    search_fields = ('code', 'name')


class VoucherLineInline(admin.TabularInline):
    model = VoucherLine
    fields = ('line_no', 'account', 'cost_center', 'debit', 'credit', 'narration')
    extra = 0

    def has_change_permission(self, request, obj=None):
        # Lines follow the voucher lifecycle: editable only while Draft.
        return obj is None or obj.status == 'Draft'

    has_add_permission = has_change_permission
    has_delete_permission = has_change_permission


@admin.register(Voucher)
class VoucherAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'voucher_type', 'date', 'company', 'total_debit', 'status', 'posted_at')
    list_filter = ('voucher_type', 'status', 'financial_year', 'narration_source')
    search_fields = ('voucher_no', 'narration', 'reference')
    readonly_fields = ('voucher_no', 'status', 'total_debit', 'total_credit',
                       'posted_by', 'posted_at', 'cancelled_by', 'cancelled_at',
                       'auto_narration', 'narration_source', 'narration_edited_by', 'narration_edited_at')
    inlines = [VoucherLineInline]

    def has_delete_permission(self, request, obj=None):
        # Posted/cancelled vouchers are part of the books; never hard-delete.
        return obj is not None and obj.status == 'Draft'


@admin.register(NarrationSettings)
class NarrationSettingsAdmin(admin.ModelAdmin):
    list_display = ('enabled', 'include_amount', 'include_reference', 'include_party', 'modified_by', 'modified_at')
    readonly_fields = ('modified_by', 'modified_at')

    def has_add_permission(self, request):
        # Singleton (pk=1, see NarrationSettings.get_solo()): only one row ever.
        return not NarrationSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        obj.modified_by = request.user
        super().save_model(request, obj, form, change)
