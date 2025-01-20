from django.urls import path
from . import views

urlpatterns = [
    path("purchase/", views.purchase, name="purchase"),
    path("supplier/", views.supplier, name="supplier"),
    path("terms/", views.terms, name="terms"),
    path("vendor_groups/", views.vendor_groups, name="vendor_groups"),
    path("tax_master/", views.tax_master, name="tax_master"),
]
