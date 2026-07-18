# user/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('warehouse/', views.warehouse, name='warehouse'),
    path('warehouse/add/', views.warehouse_add, name='warehouse_add'),
    path('warehouse/<int:id>/edit/', views.warehouse_edit, name='warehouse_edit'),
    path('sector/', views.sector, name='sector'),
    path('sectors/', views.SectorAPI.as_view(), name='sector_list'),
    path('create-sector/', views.SectorAPI.as_view(), name='sector_create'),
    path('sector/<int:id>/', views.SectorAPI.as_view(), name='sector_update'),
    path('sector/<int:id>/delete/', views.SectorAPI.as_view(), name='sector_delete'),
    path('warehouse-mapping/', views.warehouse_mapping, name='warehouse_mapping'),
    path('warehouse-mapping/data/', views.warehouse_mapping_data, name='warehouse_mapping_data'),
    path('warehouse-mapping/save-branch/', views.warehouse_mapping_save_branch, name='warehouse_mapping_save_branch'),
    path('warehouse-mapping/save-hatchery/', views.warehouse_mapping_save_hatchery, name='warehouse_mapping_save_hatchery'),
    path('items/', views.items, name='items'),
    path('item_category/', views.item_category, name='item_category'),
    path('categories/', views.CategoryAPI.as_view(), name='category_list'),
    path('create-category/', views.CategoryAPI.as_view(), name='category_create'),
    path('category/<int:id>/', views.CategoryAPI.as_view(), name='category_update'),
    path('category/<int:id>/delete/', views.CategoryAPI.as_view(), name='category_delete'),
    path('warehouses/', views.WarehouseAPI.as_view(), name='warehouse_list'),
    path('create-warehouse/', views.WarehouseAPI.as_view(), name='warehouse_create'),
    path('warehouse/<int:id>/', views.WarehouseAPI.as_view(), name='warehouse_update'),
    path('warehouse/<int:id>/delete/', views.WarehouseAPI.as_view(), name='warehouse_delete'),
    path('item_list/', views.ItemAPI.as_view(), name='item_list'),
    path('create-item/', views.ItemAPI.as_view(), name='item_create'),
    path('item/<int:id>/', views.ItemAPI.as_view(), name='item_update'),
    path('item/<int:id>/delete/', views.ItemAPI.as_view(), name='item_delete'),

  
]
