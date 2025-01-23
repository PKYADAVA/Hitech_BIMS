# user/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('inventory/', views.inventory, name='inventory'), 
    path('warehouse/', views.warehouse, name='warehouse'),
    path('items/', views.items, name='items'),
    path('item_category/', views.item_category, name='item_category'),
    path('categories/', views.CategoryAPI.as_view(), name='category_list'),
    path('category/create/', views.CategoryAPI.as_view(), name='category_create'),
    path('category/<int:id>/', views.CategoryAPI.as_view(), name='category_update'),
    path('category/<int:id>/delete/', views.CategoryAPI.as_view(), name='category_delete'),
    path('warehouses/', views.WarehouseAPI.as_view(), name='warehouse_list'),
    path('create-warehouse/', views.WarehouseAPI.as_view(), name='warehouse_create'),
    path('warehouse/<int:id>/', views.WarehouseAPI.as_view(), name='warehouse_update'),
    path('warehouse/<int:id>/delete/', views.WarehouseAPI.as_view(), name='warehouse_delete'),
    path('item_list/', views.ItemAPI.as_view(), name='item_list'),
    path('item/create/', views.ItemAPI.as_view(), name='item_create'),
    path('item/<int:id>/', views.ItemAPI.as_view(), name='item_update'),
    path('item/<int:id>/delete/', views.ItemAPI.as_view(), name='item_delete'),

  
]
