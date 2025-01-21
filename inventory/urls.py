# user/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('inventory/', views.inventory, name='inventory'), 
    path('warehouse/', views.warehouse, name='warehouse'),
    path('items/', views.items, name='items'),
    path('item_category/', views.item_category, name='item_category'),
  
]
