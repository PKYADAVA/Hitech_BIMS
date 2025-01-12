# broiler/urls.py
from django.urls import path
from . import views

from .views import BranchAPI, BranchTemplateView, BroilerBatchTemplateView, BroilerDiseaseTemplateView, BroilerFarmTemplateView, BroilerPlaceTemplateView, SupervisorAPI, SupervisorTemplateView

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
    path('branch-farm/', BroilerFarmTemplateView.as_view(), name='branch_farm'),
    path('broiler-disease/', BroilerDiseaseTemplateView.as_view(), name='broiler_disease'),
    path('broiler-batch/', BroilerBatchTemplateView.as_view(), name='broiler_batch')
    
]
