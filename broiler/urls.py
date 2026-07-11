# broiler/urls.py
from django.urls import path
from . import views

from .views import BranchAPI, BranchTemplateView, BroilerBatchAPI, BroilerBatchTemplateView, BroilerDiseaseAPI, BroilerDiseaseTemplateView, BroilerFarmAPI, BroilerFarmTemplateView, BroilerLineAPI, BroilerLineTemplateView, FarmerAPI, FarmerGroupAPI, FarmerGroupTemplateView, RegionAPI, RegionTemplateView, SupervisorAPI, SupervisorTemplateView

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
    path('broiler-batch/', BroilerBatchTemplateView.as_view(), name='broiler_batch'),
    path('broiler_batch_list/', BroilerBatchAPI.as_view(), name='broiler_batch_list'),  # For listing all broiler batch
    path('create-batch/', BroilerBatchAPI.as_view(), name='broiler_batch_create'),  # For creating new broiler batch
    path('broiler_batch/<int:id>/', BroilerBatchAPI.as_view(), name='broiler_batch_edit'),  # For editing broiler batch
    path('broiler_batch/<int:id>/delete/', BroilerBatchAPI.as_view(), name='broiler_batch_delete'), # For deleting broiler batch
    path('get-supervisors/', views.get_supervisors, name='get_supervisors'),

]
