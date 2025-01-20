from django.urls import path
from . import views

urlpatterns = [
    path("purchase/", views.purchase, name="purchase"),
    path("supplier/", views.supplier, name="supplier"),
    path('suppliers/', views.VendorGroupAPI.as_view(), name='supplier_list'),
    path('supplier/create/', views.SupplierAPI.as_view(), name='supplier_create'),
    path('supplier/update/<int:id>/', views.SupplierAPI.as_view(), name='supplier_update'),
    path('supplier/delete/<int:id>/', views.SupplierAPI.as_view(), name='supplier_delete'),
    path("terms/", views.terms, name="terms"),
    path('terms_conditions/', views.TermsConditionsAPI.as_view(), name='terms_conditions_list'),
    path('terms_conditions/create/', views.TermsConditionsAPI.as_view(), name='terms_conditions_create'),
    path('terms_conditions/update/<int:id>/', views.TermsConditionsAPI.as_view(), name='terms_conditions_update'),
    path('terms_conditions/delete/<int:id>/', views.TermsConditionsAPI.as_view(), name='terms_conditions_delete'),
    path("vendor_groups/", views.vendor_groups, name="vendor_groups"),
    path('vendor_group/', views.VendorGroupAPI.as_view(), name='vendor_group_list'),
    path('vendor_group/create/', views.VendorGroupAPI.as_view(), name='vendor_group_create'),
    path('vendor_group/update/<int:id>/', views.VendorGroupAPI.as_view(), name='vendor_group_update'),
    path('vendor_group/delete/<int:id>/', views.VendorGroupAPI.as_view(), name='vendor_group_delete'),
    path("tax_master/", views.tax_master, name="tax_master"),
    path('tax_masters/', views.TaxMasterAPI.as_view(), name='tax_master_list'),
    path('tax_master/create/', views.TaxMasterAPI.as_view(), name='tax_master_create'),
    path('tax_master/update/<int:id>/', views.TaxMasterAPI.as_view(), name='tax_master_update'),
    path('tax_master/delete/<int:id>/', views.TaxMasterAPI.as_view(), name='tax_master_delete'),
]
