# broiler/urls.py
from django.urls import path
from . import views

from .views import BranchAPI, BranchTemplateView, BroilerBatchAPI, BroilerBatchTemplateView, BroilerDiseaseAPI, BroilerDiseaseTemplateView, BroilerFarmAPI, BroilerFarmTemplateView, BroilerPlaceAPI, BroilerPlaceTemplateView, SupervisorAPI, SupervisorTemplateView

urlpatterns = [
    path('broiler/', views.broiler, name='broiler'),  
    path('branches/', BranchTemplateView.as_view(), name='branch_template'),
    path('branch_list/', BranchAPI.as_view(), name='branch_list'),  # For listing all branches
    path('create-branch/', BranchAPI.as_view(), name='branch_create'),  # For creating new branches
    path('branches/<int:id>/', BranchAPI.as_view(), name='branch_edit'),  # For editing branches
    path('branches/<int:id>/delete/', BranchAPI.as_view(), name='branch_delete'), # For deleting branches
    path('branch-supervisor/', SupervisorTemplateView.as_view(), name='supervisor_template'),
    path('supervisor_list/', SupervisorAPI.as_view(), name='supervisor_list'),  # For listing all supervisor
    path('create-supervisor/', SupervisorAPI.as_view(), name='supervisor_create'),  # For creating new supervisor
    path('supervisor/<int:id>/', SupervisorAPI.as_view(), name='supervisor_edit'),  # For editing supervisor
    path('supervisor/<int:id>/delete/', SupervisorAPI.as_view(), name='supervisor_delete'), # For deleting supervisor
    path('branch-place/', BroilerPlaceTemplateView.as_view(), name='branch_place'),
    path('branch_place_list/', BroilerPlaceAPI.as_view(), name='broiler_place_list'),  # For listing all broiler place
    path('create-branch-place/', BroilerPlaceAPI.as_view(), name='broiler_place_create'),  # For creating new broiler place
    path('branch_place/<int:id>/', BroilerPlaceAPI.as_view(), name='broiler_place_edit'),  # For editing broiler place
    path('branch_place/<int:id>/delete/', BroilerPlaceAPI.as_view(), name='broiler_place_delete'), # For deleting broiler place
    path('branch-farm/', BroilerFarmTemplateView.as_view(), name='branch_farm'),
    path('broiler_farm/', BroilerFarmAPI.as_view(), name='broiler_farm_list'),
    path('broiler_farm/<int:id>/', BroilerFarmAPI.as_view(), name='broiler_farm_detail'),
    path('create-broiler-farm/', BroilerFarmAPI.as_view(), name='broiler_farm_create'),  # For creating new broiler disease    
    path('broiler_farm/<int:id>/delete/', BroilerFarmAPI.as_view(), name='broiler_farm_delete'), # For deleting broiler disease
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
    
]
