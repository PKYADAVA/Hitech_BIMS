from django.urls import path
from . import views

urlpatterns = [
    path('sales/', views.sales, name='sales'),
    path('customer/', views.customer, name='customer'),
    path('customers/', views.CustomerAPI.as_view(), name='customer_list'),
    path('customer/create/', views.CustomerAPI.as_view(), name='customer_create'),
    path('customer/<int:id>/', views.CustomerAPI.as_view(), name='customer_update'),
    path('customer/<int:id>/delete/', views.CustomerAPI.as_view(), name='customer_delete'),
    # path('terms/', views.terms, name='terms'),
    # path('terms_conditions/', views.TermsConditionsAPI.as_view(), name='terms_conditions_list'),
    # path('terms_conditions/create/', views.TermsConditionsAPI.as_view(), name='terms_conditions_create'),
    # path('terms_conditions/<int:id>/', views.TermsConditionsAPI.as_view(), name='terms_conditions_update'),
    # path('terms_conditions/<int:id>/delete', views.TermsConditionsAPI.as_view(), name='terms_conditions_delete'),
    path('customer_groups/', views.customer_groups, name='customer_groups'),
    path('customer_group/', views.CustomerGroupAPI.as_view(), name='customer_group_list'),
    path('customer_group/create/', views.CustomerGroupAPI.as_view(), name='customer_group_create'),
    path('customer_group/<int:id>/', views.CustomerGroupAPI.as_view(), name='customer_group_update'),
    path('customer_group/<int:id>/delete/', views.CustomerGroupAPI.as_view(), name='customer_group_delete'),
    path('sales_price/', views.sales_price, name='sales_price_master'),
    # path('sales_price_master/', views.SalesPriceMasterAPI.as_view(), name='sales_price_list'),
    # path('sales_price_master/create/', views.SalesPriceMasterAPI.as_view(), name='sales_price_create'),
    # path('sales_price_master/<int:id>/', views.SalesPriceMasterAPI.as_view(), name='sales_price_update'),
    # path('sales_price_master/<int:id>/delete/', views.SalesPriceMasterAPI.as_view(), name='sales_price_delete'),

]
