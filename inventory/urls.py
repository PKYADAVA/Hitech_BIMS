# user/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('inventory/', views.inventory, name='inventory'), 
  
]
