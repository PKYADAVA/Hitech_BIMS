# broiler/urls.py
from django.urls import path
from . import views

from .views import BranchAPI, BranchTemplateView

urlpatterns = [
    path('broiler/', views.broiler, name='broiler'),    
    path('branches/', BranchTemplateView.as_view(), name='branch_list'),
    path('branches/<int:pk>/', BranchAPI.as_view(), name='branch_edit'),  # For editing
    path('branches/<int:pk>/delete/', BranchAPI.as_view(), name='branch_delete'),  # For deletion
    
]
