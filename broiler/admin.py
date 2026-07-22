from django.contrib import admin
from import_export import resources
from import_export.admin import ImportExportModelAdmin
from import_export.fields import Field
from import_export.widgets import ForeignKeyWidget
from django.utils.html import format_html
from account.models import ChartOfAccount
from .models import (
    Branch, Breed, BreedStandard, Supervisor, BroilerLine, Farmer, FarmerGroup, Region, BroilerFarm,
    BroilerFarmShed, BroilerFarmImage, BroilerBatch, BroilerDisease,
    GrowingChargeScheme, GCProductionCostIncentive, GCSalesIncentive, GCMortalityIncentive,
    GCFCRIncentive, GCSummerIncentive, GCProductionCostDecentive, GCMortalityDecentive,
    GCFCRRecovery, GCFarmerClassification,
)


# ---------------------------------------------------------------- #
# Import/export resources - override FK fields to resolve/display
# by a human-readable name instead of the numeric database id, so
# CSVs can be written and read by hand.
# ---------------------------------------------------------------- #

class FarmerGroupResource(resources.ModelResource):
    pay_account = Field(
        attribute='pay_account', column_name='pay_account',
        widget=ForeignKeyWidget(ChartOfAccount, field='description'),
    )
    advance_account = Field(
        attribute='advance_account', column_name='advance_account',
        widget=ForeignKeyWidget(ChartOfAccount, field='description'),
    )

    class Meta:
        model = FarmerGroup


class BranchResource(resources.ModelResource):
    region = Field(
        attribute='region', column_name='region',
        widget=ForeignKeyWidget(Region, field='description'),
    )

    class Meta:
        model = Branch


class SupervisorResource(resources.ModelResource):
    branch = Field(
        attribute='branch', column_name='branch',
        widget=ForeignKeyWidget(Branch, field='branch_name'),
    )

    class Meta:
        model = Supervisor


class BroilerLineResource(resources.ModelResource):
    region = Field(
        attribute='region', column_name='region',
        widget=ForeignKeyWidget(Region, field='description'),
    )
    branch = Field(
        attribute='branch', column_name='branch',
        widget=ForeignKeyWidget(Branch, field='branch_name'),
    )

    class Meta:
        model = BroilerLine


class FarmerResource(resources.ModelResource):
    farmer_group = Field(
        attribute='farmer_group', column_name='farmer_group',
        widget=ForeignKeyWidget(FarmerGroup, field='description'),
    )

    class Meta:
        model = Farmer


class BroilerFarmResource(resources.ModelResource):
    branch = Field(
        attribute='branch', column_name='branch',
        widget=ForeignKeyWidget(Branch, field='branch_name'),
    )
    supervisor = Field(
        attribute='supervisor', column_name='supervisor',
        widget=ForeignKeyWidget(Supervisor, field='name'),
    )
    farmer = Field(
        attribute='farmer', column_name='farmer',
        widget=ForeignKeyWidget(Farmer, field='farmer_name'),
    )

    class Meta:
        model = BroilerFarm


class BroilerBatchResource(resources.ModelResource):
    broiler_farm = Field(
        attribute='broiler_farm', column_name='broiler_farm',
        widget=ForeignKeyWidget(BroilerFarm, field='farm_name'),
    )

    class Meta:
        model = BroilerBatch


class BroilerDiseaseResource(resources.ModelResource):
    batch = Field(
        attribute='batch', column_name='batch',
        widget=ForeignKeyWidget(BroilerBatch, field='batch_name'),
    )

    class Meta:
        model = BroilerDisease


@admin.register(FarmerGroup)
class FarmerGroupAdmin(ImportExportModelAdmin):
    """Admin interface for FarmerGroup records."""
    resource_classes = [FarmerGroupResource]
    list_display = ('code', 'description', 'pay_account', 'advance_account', 'is_active', 'is_locked')
    search_fields = ('code', 'description')
    list_filter = ('is_active', 'is_locked')
    list_per_page = 20


@admin.register(Region)
class RegionAdmin(ImportExportModelAdmin):
    """Admin interface for Region records."""
    list_display = ('code', 'description', 'is_active', 'is_locked')
    search_fields = ('code', 'description')
    list_filter = ('is_active', 'is_locked')
    list_per_page = 20


@admin.register(Breed)
class BreedAdmin(ImportExportModelAdmin):
    """Admin interface for Breed records."""
    list_display = ('code', 'description', 'is_active', 'is_locked')
    search_fields = ('code', 'description')
    list_filter = ('is_active', 'is_locked')
    list_per_page = 20


@admin.register(BreedStandard)
class BreedStandardAdmin(ImportExportModelAdmin):
    """Admin interface for Breed Standard records."""
    list_display = ('code', 'breed', 'age', 'body_weight', 'feed_intake',
                    'avg_daily_gain', 'fcr', 'cum_feed', 'is_active', 'is_locked')
    search_fields = ('code', 'breed__code', 'breed__description')
    list_filter = ('breed', 'is_active', 'is_locked')
    list_per_page = 20


@admin.register(Branch)
class BranchAdmin(ImportExportModelAdmin):
    """
    Admin interface for Branch model with optimized display and search functionality.
    """
    resource_classes = [BranchResource]
    list_display = ('code', 'branch_name', 'region', 'prefix', 'get_farm_count', 'is_active', 'is_locked')
    search_fields = ('code', 'branch_name', 'prefix')
    list_filter = ('region', 'is_active', 'is_locked')
    list_per_page = 20
    ordering = ('code',)
    
    def get_farm_count(self, obj):
        """Returns the count of farms associated with this branch."""
        count = BroilerFarm.objects.filter(branch=obj).count()
        return format_html('<span class="badge bg-info">{}</span>', count)
    get_farm_count.short_description = 'Farm Count'


@admin.register(Supervisor)
class SupervisorAdmin(ImportExportModelAdmin):
    """
    Admin interface for Supervisor model with enhanced filtering and display.
    """
    resource_classes = [SupervisorResource]
    list_display = ('id', 'name', 'phone_no', 'branch')
    search_fields = ('name', 'phone_no')
    list_filter = ('branch',)
    list_per_page = 20
    ordering = ('name',)


@admin.register(BroilerLine)
class BroilerLineAdmin(ImportExportModelAdmin):
    """
    Admin interface for BroilerLine model with optimized display and filtering.
    """
    resource_classes = [BroilerLineResource]
    list_display = ('code', 'description', 'region', 'branch', 'is_active', 'is_locked')
    search_fields = ('code', 'description')
    list_filter = ('region', 'branch', 'is_active', 'is_locked')
    list_per_page = 20
    ordering = ('code',)


@admin.register(Farmer)
class FarmerAdmin(ImportExportModelAdmin):
    """
    Admin interface for Farmer model with optimized display and filtering.
    """
    resource_classes = [FarmerResource]
    list_display = (
        'id', 'farmer_name', 'mobile_no', 'farmer_group', 'usc',
        'service_no', 'get_farm_count'
    )
    search_fields = ('farmer_name', 'mobile_no', 'pan_no', 'aadhar_no', 'usc', 'service_no')
    list_filter = ('farmer_group',)
    list_per_page = 20
    ordering = ('farmer_name',)

    def get_farm_count(self, obj):
        """Returns the count of farms belonging to this farmer."""
        count = obj.get_farm_count()
        return format_html('<span class="badge bg-info">{}</span>', count)
    get_farm_count.short_description = 'Farm Count'


class BroilerFarmShedInline(admin.TabularInline):
    model = BroilerFarmShed
    extra = 0


class BroilerFarmImageInline(admin.TabularInline):
    model = BroilerFarmImage
    extra = 0


@admin.register(BroilerFarm)
class BroilerFarmAdmin(ImportExportModelAdmin):
    """
    Admin interface for BroilerFarm model with comprehensive display and filtering options.
    """
    resource_classes = [BroilerFarmResource]
    list_display = (
        'id', 'farm_name', 'farm_code', 'branch', 'supervisor',
        'farmer', 'farm_type', 'agreement_start_date', 'agreement_end_date',
        'get_batch_count'
    )
    search_fields = ('farm_name', 'farm_code', 'farmer__farmer_name', 'line')
    list_filter = ('branch', 'supervisor', 'farm_type', 'region')
    list_per_page = 20
    ordering = ('farm_name',)
    inlines = [BroilerFarmShedInline, BroilerFarmImageInline]
    fieldsets = (
        ('Basic Information', {
            'fields': ('farm_name', 'farm_code', 'farm_type', 'farmer')
        }),
        ('Location Details', {
            'fields': (
                'branch', 'supervisor', 'region', 'line', 'state', 'district',
                'area', 'farm_address', 'farm_pincode', 'farm_latitude', 'farm_longitude',
            )
        }),
        ('Farm Details', {
            'fields': ('farm_capacity', 'farm_sqft', 'remarks')
        }),
        ('Agreement', {
            'fields': (
                'agreement_start_date', 'agreement_end_date', 'agreement_months',
                'agreement_copy', 'other_documents',
            )
        }),
        ('Security Cheques', {
            'fields': (
                'cheque_1_no', 'cheque_1_file', 'cheque_2_no', 'cheque_2_file',
                'cheque_3_no', 'cheque_3_file', 'cheque_4_no', 'cheque_4_file',
            )
        }),
    )

    def get_batch_count(self, obj):
        """Returns the count of batches in this farm."""
        count = BroilerBatch.objects.filter(broiler_farm=obj).count()
        return format_html('<span class="badge bg-info">{}</span>', count)
    get_batch_count.short_description = 'Batch Count'


@admin.register(BroilerBatch)
class BroilerBatchAdmin(ImportExportModelAdmin):
    """
    Admin interface for BroilerBatch model with optimized display and filtering.
    """
    resource_classes = [BroilerBatchResource]
    list_display = ('id', 'batch_name', 'broiler_farm', 'get_disease_count')
    search_fields = ('batch_name',)
    list_filter = ('broiler_farm',)
    list_per_page = 20
    ordering = ('-id',)
    
    def get_disease_count(self, obj):
        """Returns the count of diseases associated with this batch."""
        count = BroilerDisease.objects.filter(batch=obj).count()
        return format_html('<span class="badge bg-danger">{}</span>', count)
    get_disease_count.short_description = 'Disease Count'


@admin.register(BroilerDisease)
class BroilerDiseaseAdmin(ImportExportModelAdmin):
    """
    Admin interface for BroilerDisease model with enhanced display and filtering.
    """
    resource_classes = [BroilerDiseaseResource]
    list_display = ('id', 'disease_code', 'disease_name', 'symptoms', 'diagnosis', 'get_batch_name')
    search_fields = ('disease_code', 'disease_name', 'symptoms', 'diagnosis')
    list_filter = ('disease_name',)
    list_per_page = 20
    ordering = ('disease_name',)
    
    def get_batch_name(self, obj):
        """Returns the name of the batch associated with this disease."""
        if hasattr(obj, 'batch') and obj.batch:
            return obj.batch.batch_name
        return '-'
    get_batch_name.short_description = 'Batch'


def _gc_inline(model_cls):
    return type(f"{model_cls.__name__}Inline", (admin.TabularInline,), {"model": model_cls, "extra": 0})


@admin.register(GrowingChargeScheme)
class GrowingChargeSchemeAdmin(admin.ModelAdmin):
    """Admin interface for the Rearing / Growing Charge master."""
    list_display = ('id', 'scheme_code', 'schema_name', 'region', 'branch', 'from_date', 'to_date', 'is_active', 'is_locked')
    search_fields = ('scheme_code', 'schema_name')
    list_filter = ('is_active', 'is_locked', 'region', 'branch')
    list_per_page = 20
    ordering = ('-id',)
    raw_id_fields = ('region', 'branch')
    inlines = [_gc_inline(m) for m in (
        GCProductionCostIncentive, GCSalesIncentive, GCMortalityIncentive, GCFCRIncentive,
        GCSummerIncentive, GCProductionCostDecentive, GCMortalityDecentive, GCFCRRecovery,
        GCFarmerClassification,
    )]
