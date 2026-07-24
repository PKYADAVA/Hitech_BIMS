# broiler/urls.py
from django.urls import path
from . import views

from .views import BranchAPI, BranchTemplateView, BroilerBatchAPI, BroilerBatchTemplateView, BroilerDiseaseAPI, BroilerDiseaseTemplateView, BroilerFarmAPI, BroilerFarmShedAPI, BroilerFarmShedTemplateView, BroilerFarmTemplateView, BroilerLineAPI, BroilerLineTemplateView, FarmerAPI, FarmerGroupAPI, FarmerGroupTemplateView, RegionAPI, RegionTemplateView, SupervisorAPI, SupervisorTemplateView

urlpatterns = [
    path('farmer-group/', FarmerGroupTemplateView.as_view(), name='farmer_group'),
    path('farmer_group_list/', FarmerGroupAPI.as_view(), name='farmer_group_list'),  # For listing all farmer groups
    path('create-farmer-group/', FarmerGroupAPI.as_view(), name='farmer_group_create'),  # For creating new farmer group
    path('farmer_group/<int:id>/', FarmerGroupAPI.as_view(), name='farmer_group_edit'),  # For editing farmer group
    path('farmer_group/<int:id>/delete/', FarmerGroupAPI.as_view(), name='farmer_group_delete'), # For deleting farmer group
    path('farmer_group/<int:id>/toggle-active/', views.toggle_farmer_group_active, name='farmer_group_toggle_active'),
    path('farmer_group/<int:id>/toggle-lock/', views.toggle_farmer_group_lock, name='farmer_group_toggle_lock'),
    path('region/', RegionTemplateView.as_view(), name='region'),
    path('region_list/', RegionAPI.as_view(), name='region_list'),  # For listing all regions
    path('create-region/', RegionAPI.as_view(), name='region_create'),  # For creating new region
    path('region/<int:id>/', RegionAPI.as_view(), name='region_edit'),  # For editing region
    path('region/<int:id>/delete/', RegionAPI.as_view(), name='region_delete'), # For deleting region
    path('region/<int:id>/toggle-active/', views.toggle_region_active, name='region_toggle_active'),
    path('region/<int:id>/toggle-lock/', views.toggle_region_lock, name='region_toggle_lock'),
    path('branches/', BranchTemplateView.as_view(), name='branch_template'),
    path('branch_list/', BranchAPI.as_view(), name='branch_list'),  # For listing all branches
    path('create-branch/', BranchAPI.as_view(), name='branch_create'),  # For creating new branches
    path('branch/<int:id>/', BranchAPI.as_view(), name='branch_edit'),  # For editing branches
    path('branch/<int:id>/delete/', BranchAPI.as_view(), name='branch_delete'), # For deleting branches
    path('branch/<int:id>/toggle-active/', views.toggle_branch_active, name='branch_toggle_active'),
    path('branch/<int:id>/toggle-lock/', views.toggle_branch_lock, name='branch_toggle_lock'),
    path('branch-supervisor/', SupervisorTemplateView.as_view(), name='supervisor_template'),
    path('supervisor_list/', SupervisorAPI.as_view(), name='supervisor_list'),  # For listing all supervisor
    path('create-supervisor/', SupervisorAPI.as_view(), name='supervisor_create'),  # For creating new supervisor
    path('supervisor/<int:id>/', SupervisorAPI.as_view(), name='supervisor_edit'),  # For editing supervisor
    path('supervisor/<int:id>/delete/', SupervisorAPI.as_view(), name='supervisor_delete'), # For deleting supervisor
    path('broiler-line/', BroilerLineTemplateView.as_view(), name='broiler_line'),
    path('broiler_line_list/', BroilerLineAPI.as_view(), name='broiler_line_list'),  # For listing all broiler lines
    path('create-broiler-line/', BroilerLineAPI.as_view(), name='broiler_line_create'),  # For creating new broiler line
    path('broiler_line/<int:id>/', BroilerLineAPI.as_view(), name='broiler_line_edit'),  # For editing broiler line
    path('broiler_line/<int:id>/delete/', BroilerLineAPI.as_view(), name='broiler_line_delete'), # For deleting broiler line
    path('broiler_line/<int:id>/toggle-active/', views.toggle_broiler_line_active, name='broiler_line_toggle_active'),
    path('broiler_line/<int:id>/toggle-lock/', views.toggle_broiler_line_lock, name='broiler_line_toggle_lock'),
    path('get-branches-by-region/', views.get_branches_by_region, name='get_branches_by_region'),
    path('get-lines-by-branch/', views.get_lines_by_branch, name='get_lines_by_branch'),
    path('branch-farm/', BroilerFarmTemplateView.as_view(), name='branch_farm'),
    path('farmer_list/', FarmerAPI.as_view(), name='farmer_list'),  # For listing all farmers
    path('create-farmer/', FarmerAPI.as_view(), name='farmer_create'),  # For creating new farmer
    path('farmer/<int:id>/', FarmerAPI.as_view(), name='farmer_detail'),  # For fetching a farmer
    path('farmer/<int:id>/update/', FarmerAPI.as_view(), name='farmer_update'),  # For updating a farmer
    path('farmer/<int:id>/delete/', FarmerAPI.as_view(), name='farmer_delete'),  # For deleting a farmer
    path('broiler_farm/', BroilerFarmAPI.as_view(), name='broiler_farm_list'),
    path('broiler_farm/<int:id>/', BroilerFarmAPI.as_view(), name='broiler_farm_detail'),
    path('broiler_farm_create/', BroilerFarmAPI.as_view(), name='broiler_farm_create'),  # For creating new broiler farm
    path('broiler_farm/<int:id>/update/', BroilerFarmAPI.as_view(), name='broiler_farm_update'),  # For updating a broiler farm
    path('broiler_farm/<int:id>/delete/', BroilerFarmAPI.as_view(), name='broiler_farm_delete'), # For deleting broiler farm
    path('broiler-disease/', BroilerDiseaseTemplateView.as_view(), name='broiler_disease'),
    path('broiler_disease/', BroilerDiseaseAPI.as_view(), name='broiler_disease_list'),
    path('broiler_disease/<int:id>/', BroilerDiseaseAPI.as_view(), name='broiler_disease_detail'),
    path('create-broiler-disease/', BroilerDiseaseAPI.as_view(), name='broiler_disease_create'),  # For creating new broiler disease    
    path('broiler_disease/<int:id>/delete/', BroilerDiseaseAPI.as_view(), name='broiler_disease_delete'), # For deleting broiler disease

    path('broiler-farm-shed/', BroilerFarmShedTemplateView.as_view(), name='broiler_farm_shed'),
    path('broiler_farm_shed/', BroilerFarmShedAPI.as_view(), name='broiler_farm_shed_list'),
    path('create-broiler-farm-shed/', BroilerFarmShedAPI.as_view(), name='broiler_farm_shed_create'),
    path('broiler_farm_shed/<int:id>/', BroilerFarmShedAPI.as_view(), name='broiler_farm_shed_detail'),
    path('broiler_farm_shed/<int:id>/delete/', BroilerFarmShedAPI.as_view(), name='broiler_farm_shed_delete'),
    path('broiler-batch/', BroilerBatchTemplateView.as_view(), name='broiler_batch'),
    path('broiler_batch_list/', BroilerBatchAPI.as_view(), name='broiler_batch_list'),  # For listing all broiler batch
    path('create-batch/', BroilerBatchAPI.as_view(), name='broiler_batch_create'),  # For creating new broiler batch
    path('broiler_batch/<int:id>/', BroilerBatchAPI.as_view(), name='broiler_batch_edit'),  # For editing broiler batch
    path('broiler_batch/<int:id>/delete/', BroilerBatchAPI.as_view(), name='broiler_batch_delete'), # For deleting broiler batch
    path('get-supervisors/', views.get_supervisors, name='get_supervisors'),

    path('daily-entry/', views.DailyEntryListTemplateView.as_view(), name='daily_entry_list'),
    path('daily-entry/add/', views.DailyEntryFormTemplateView.as_view(), name='daily_entry_add'),
    path('daily_entry_api/', views.DailyEntryAPI.as_view(), name='daily_entry_api_list'),
    path('daily_entry_api/group-delete/', views.daily_entry_group_delete, name='daily_entry_group_delete'),
    path('daily_entry_api/<int:id>/', views.DailyEntryAPI.as_view(), name='daily_entry_api'),
    path('daily-entry/farm-lookup/', views.daily_entry_farm_lookup, name='daily_entry_farm_lookup'),
    path('daily-entry/stock-lookup/', views.daily_entry_stock_lookup, name='daily_entry_stock_lookup'),

    path('daily-entry/single/', views.SingleBatchDailyEntryListTemplateView.as_view(), name='daily_entry_single_list'),
    path('daily-entry/single/add/', views.SingleBatchDailyEntryFormTemplateView.as_view(), name='daily_entry_single_add'),

    path('medicine-entry/', views.MedicineEntryListTemplateView.as_view(), name='medicine_entry_list'),
    path('medicine-entry/add/', views.MedicineEntryFormTemplateView.as_view(), name='medicine_entry_add'),
    path('medicine_entry_api/', views.MedicineEntryAPI.as_view(), name='medicine_entry_api_list'),
    path('medicine_entry_api/group-delete/', views.medicine_entry_group_delete, name='medicine_entry_group_delete'),
    path('medicine_entry_api/<int:id>/', views.MedicineEntryAPI.as_view(), name='medicine_entry_api'),
    path('medicine-entry/farm-lookup/', views.medicine_entry_farm_lookup, name='medicine_entry_farm_lookup'),
    path('medicine-entry/item-lookup/', views.medicine_entry_item_lookup, name='medicine_entry_item_lookup'),
    path('medicine-entry/stock-lookup/', views.medicine_entry_stock_lookup, name='medicine_entry_stock_lookup'),

    path('bird-sale/', views.BirdSaleListTemplateView.as_view(), name='bird_sale_list'),
    path('bird-sale/add/', views.BirdSaleFormTemplateView.as_view(), name='bird_sale_add'),
    path('bird-sale/<int:id>/edit/', views.BirdSaleFormTemplateView.as_view(), name='bird_sale_edit'),
    path('bird_sale_api/', views.BirdSaleAPI.as_view(), name='bird_sale_api_list'),
    path('bird_sale_api/<int:id>/', views.BirdSaleAPI.as_view(), name='bird_sale_api'),
    path('bird-sale/farm-lookup/', views.bird_sale_farm_lookup, name='bird_sale_farm_lookup'),

    path('bird-sale-receipt/', views.BirdSaleReceiptListTemplateView.as_view(), name='bird_sale_receipt_list'),
    path('bird-sale-receipt/add/', views.BirdSaleReceiptFormTemplateView.as_view(), name='bird_sale_receipt_add'),
    path('bird-sale-receipt/<int:id>/edit/', views.BirdSaleReceiptFormTemplateView.as_view(), name='bird_sale_receipt_edit'),
    path('bird_sale_receipt_api/', views.BirdSaleReceiptAPI.as_view(), name='bird_sale_receipt_api_list'),
    path('bird_sale_receipt_api/<int:id>/', views.BirdSaleReceiptAPI.as_view(), name='bird_sale_receipt_api'),
    path('bird-sale-receipt/balance-lookup/', views.bird_sale_receipt_balance_lookup, name='bird_sale_receipt_balance_lookup'),

    path('broiler-report/', views.broiler_batch_report, name='broiler_batch_report'),
    path('chicks-placement-report/', views.chicks_placement_report, name='chicks_placement_report'),
    path('feed-dispatch-stock-report/', views.feed_dispatch_stock_report, name='feed_dispatch_stock_report'),
    path('live-flock-summary/', views.live_flock_summary_report, name='live_flock_summary_report'),
    path('day-record-report/', views.day_record_report, name='day_record_report'),

    path('chicks-placement/', views.ChicksPlacementListTemplateView.as_view(), name='chicks_placement_list'),
    path('chicks-placement/add/', views.ChicksPlacementFormTemplateView.as_view(), name='chicks_placement_add'),

    path('breed/', views.BreedTemplateView.as_view(), name='breed'),
    path('breed_list/', views.BreedAPI.as_view(), name='breed_list'),  # For listing all breeds
    path('create-breed/', views.BreedAPI.as_view(), name='breed_create'),  # For creating new breed
    path('breed/<int:id>/', views.BreedAPI.as_view(), name='breed_edit'),  # For editing breed
    path('breed/<int:id>/delete/', views.BreedAPI.as_view(), name='breed_delete'),  # For deleting breed
    path('breed/<int:id>/toggle-active/', views.toggle_breed_active, name='breed_toggle_active'),
    path('breed/<int:id>/toggle-lock/', views.toggle_breed_lock, name='breed_toggle_lock'),

    path('breed-standard/', views.BreedStandardTemplateView.as_view(), name='breed_standard'),
    path('breed_standard_list/', views.BreedStandardAPI.as_view(), name='breed_standard_list'),  # Grouped by breed
    path('save-breed-standard/', views.save_breed_standard, name='breed_standard_save'),  # Create/replace a breed's curve
    path('breed-standard/breed/<int:breed_id>/', views.breed_standard_by_breed, name='breed_standard_by_breed'),  # Rows for edit
    path('breed_standard/<int:id>/', views.BreedStandardAPI.as_view(), name='breed_standard_detail'),
    path('breed_standard/<int:id>/delete/', views.BreedStandardAPI.as_view(), name='breed_standard_delete'),
    path('breed_standard/<int:id>/toggle-active/', views.toggle_breed_standard_active, name='breed_standard_toggle_active'),
    path('breed_standard/<int:id>/toggle-lock/', views.toggle_breed_standard_lock, name='breed_standard_toggle_lock'),

    path('growing-charge/', views.GrowingChargeSchemeTemplateView.as_view(), name='growing_charge'),
    path('growing_charge_list/', views.GrowingChargeSchemeAPI.as_view(), name='growing_charge_list'),
    path('create-growing-charge/', views.GrowingChargeSchemeAPI.as_view(), name='growing_charge_create'),
    path('growing_charge/<int:id>/', views.GrowingChargeSchemeAPI.as_view(), name='growing_charge_edit'),
    path('growing_charge/<int:id>/delete/', views.GrowingChargeSchemeAPI.as_view(), name='growing_charge_delete'),
    path('growing_charge/<int:id>/toggle-active/', views.toggle_growing_charge_active, name='growing_charge_toggle_active'),
    path('growing_charge/<int:id>/toggle-lock/', views.toggle_growing_charge_lock, name='growing_charge_toggle_lock'),
    path('growing_charge/<int:id>/duplicate/', views.growing_charge_duplicate, name='growing_charge_duplicate'),

    # Farmer Growing Charge Settlement / Batch Closing
    path('gc-settlement/', views.GCSettlementTemplateView.as_view(), name='gc_settlement'),
    path('gc_settlement_batches/', views.gc_settlement_batches, name='gc_settlement_batches'),
    path('gc_settlement_schemes/', views.gc_settlement_schemes, name='gc_settlement_schemes'),
    path('gc_settlement_autofill/', views.gc_settlement_autofill_api, name='gc_settlement_autofill'),
    path('gc_settlement_list/', views.GCSettlementAPI.as_view(), name='gc_settlement_list'),
    path('create-gc-settlement/', views.GCSettlementAPI.as_view(), name='gc_settlement_create'),
    path('gc_settlement/<int:id>/', views.GCSettlementAPI.as_view(), name='gc_settlement_detail'),
    path('gc_settlement/<int:id>/delete/', views.GCSettlementAPI.as_view(), name='gc_settlement_delete'),
    path('gc_settlement/<int:id>/print/', views.gc_settlement_print, name='gc_settlement_print'),
]
