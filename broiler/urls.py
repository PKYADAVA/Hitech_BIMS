# broiler/urls.py
from django.urls import path
from . import views

from .views import BranchAPI, BranchTemplateView

urlpatterns = [
    path('broiler/', views.broiler, name='broiler'),    
    path('branches/', BranchTemplateView.as_view(), name='branch_template'),
    path('branch_list/', BranchAPI.as_view(), name='branch_list'),  # For listing all branches
    path('create-branch/', BranchAPI.as_view(), name='branch_create'),  # For creating new branches
    path('branches/<int:id>/', BranchAPI.as_view(), name='branch_edit'),  # For editing and deleting
    path('branches/<int:id>/delete/', BranchAPI.as_view(), name='branch_delete')
    
]
