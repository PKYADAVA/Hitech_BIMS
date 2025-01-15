from django.contrib import admin
from .models import Branch, Supervisor, BroilerPlace, BroilerFarm, BroilerBatch, BroilerDisease


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ('id', 'state', 'branch_name')
    search_fields = ('branch_name', 'state')


@admin.register(Supervisor)
class SupervisorAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'phone_no', 'branch')
    search_fields = ('name', 'phone_no')
    list_filter = ('branch',)


@admin.register(BroilerPlace)
class BroilerPlaceAdmin(admin.ModelAdmin):
    list_display = ('id', 'place_name', 'supervisor')
    search_fields = ('place_name',)
    list_filter = ('supervisor',)


@admin.register(BroilerFarm)
class BroilerFarmAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'farm_name', 'farm_code', 'branch', 'supervisor', 'broiler_place',
        'mobile_no', 'block_name', 'farm_type'
    )
    search_fields = ('farm_name', 'farm_code', 'mobile_no', 'block_name')
    list_filter = ('branch', 'supervisor', 'broiler_place', 'farm_type')


@admin.register(BroilerBatch)
class BroilerBatchAdmin(admin.ModelAdmin):
    list_display = ('id', 'batch_name', 'broiler_farm')
    search_fields = ('batch_name',)
    list_filter = ('broiler_farm',)


@admin.register(BroilerDisease)
class BroilerDiseaseAdmin(admin.ModelAdmin):
    list_display = ('id', 'disease_code', 'disease_name', 'symptoms', 'diagnosis')
    search_fields = ('disease_code', 'disease_name')
    list_filter = ('disease_name',)
