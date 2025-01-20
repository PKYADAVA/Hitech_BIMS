from django.urls import path
from . import views

urlpatterns = [
    path("purchase/", views.purchase, name="purchase"),
    path("supplier/", views.supplier, name="supplier"),
    path("terms/", views.terms, name="terms"),
    path("vendor_groups/", views.vendor_groups, name="vendor_groups"),
    path('vendor_group/', views.VendorGroupAPI.as_view(), name='vendor_group_list'),
    path('vendor_group/create/', views.VendorGroupAPI.as_view(), name='vendor_group_create'),
    path('vendor_group/update/<int:id>/', views.VendorGroupAPI.as_view(), name='vendor_group_update'),
    path('vendor_group/delete/<int:id>/', views.VendorGroupAPI.as_view(), name='vendor_group_delete'),
    path("tax_master/", views.tax_master, name="tax_master"),
]
