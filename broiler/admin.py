from django.contrib import admin
from django.utils.html import format_html
from .models import (
    Branch, Supervisor, BroilerPlace, Farmer, BroilerFarm, BroilerFarmShed,
    BroilerFarmImage, BroilerBatch, BroilerDisease,
)


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    """
    Admin interface for Branch model with optimized display and search functionality.
    """
    list_display = ('id', 'state', 'branch_name', 'get_farm_count')
    search_fields = ('branch_name', 'state')
    list_per_page = 20
    ordering = ('state', 'branch_name')
    
    def get_farm_count(self, obj):
        """Returns the count of farms associated with this branch."""
        count = BroilerFarm.objects.filter(branch=obj).count()
        return format_html('<span class="badge bg-info">{}</span>', count)
    get_farm_count.short_description = 'Farm Count'


@admin.register(Supervisor)
class SupervisorAdmin(admin.ModelAdmin):
    """
    Admin interface for Supervisor model with enhanced filtering and display.
    """
    list_display = ('id', 'name', 'phone_no', 'branch', 'get_place_count')
    search_fields = ('name', 'phone_no')
    list_filter = ('branch',)
    list_per_page = 20
    ordering = ('name',)
    
    def get_place_count(self, obj):
        """Returns the count of places managed by this supervisor."""
        count = BroilerPlace.objects.filter(supervisor=obj).count()
        return format_html('<span class="badge bg-info">{}</span>', count)
    get_place_count.short_description = 'Place Count'


@admin.register(BroilerPlace)
class BroilerPlaceAdmin(admin.ModelAdmin):
    """
    Admin interface for BroilerPlace model with optimized display and filtering.
    """
    list_display = ('id', 'place_name', 'supervisor')
    search_fields = ('place_name',)
    list_filter = ('supervisor',)
    list_per_page = 20
    ordering = ('place_name',)


@admin.register(Farmer)
class FarmerAdmin(admin.ModelAdmin):
    """
    Admin interface for Farmer model with optimized display and filtering.
    """
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
class BroilerFarmAdmin(admin.ModelAdmin):
    """
    Admin interface for BroilerFarm model with comprehensive display and filtering options.
    """
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
class BroilerBatchAdmin(admin.ModelAdmin):
    """
    Admin interface for BroilerBatch model with optimized display and filtering.
    """
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
class BroilerDiseaseAdmin(admin.ModelAdmin):
    """
    Admin interface for BroilerDisease model with enhanced display and filtering.
    """
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
