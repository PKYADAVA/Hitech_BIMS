from django.urls import path
from . import views

urlpatterns = [
   
    path('account/', views.account, name='account'),
    path('coa/', views.coa, name='coa'),
    path('fin_year/', views.fin_year, name='fin_year'),
    path('financial_year/', views.FinancialYearAPI.as_view(), name='financial_year_list'),
    path('financial-year/create/', views.FinancialYearAPI.as_view(), name='financial_yea_create'),
    path('financial-year/<int:id>/', views.FinancialYearAPI.as_view(), name='financial_year_update'),
    path('financial-year/<int:id>/delete/', views.FinancialYearAPI.as_view(), name='financial_year_delete'),
    path('bank_cash/', views.bank_cash, name='bank_cash'),
    path('schedule/', views.schedule, name='schedule'),
]
