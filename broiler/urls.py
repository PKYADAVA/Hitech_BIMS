# broiler/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('broiler/', views.broiler, name='broiler'),    
]
