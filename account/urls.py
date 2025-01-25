from django.urls import path
from . import views

urlpatterns = [
   
    path('account/', views.account, name='account'),
    path('coa/', views.coa, name='coa'),
    path('chart-of-accounts/', views.ChartOfAccountsAPI.as_view(), name='chart_of_accounts_list'),
    path('chart-of-accounts/create/', views.ChartOfAccountsAPI.as_view(), name='chart_of_accounts_create'),
    path('chart-of-accounts/<int:id>/', views.ChartOfAccountsAPI.as_view(), name='chart-of-accounts_update'),
    path('chart-of-accounts/<int:id>/delete/', views.ChartOfAccountsAPI.as_view(), name='chart-of-accounts_delete'),
    path('fin_year/', views.fin_year, name='fin_year'),
    path('financial_year/', views.FinancialYearAPI.as_view(), name='financial_year_list'),
    path('financial-year/create/', views.FinancialYearAPI.as_view(), name='financial_year_create'),
    path('financial-year/<int:id>/', views.FinancialYearAPI.as_view(), name='financial_year_update'),
    path('financial-year/<int:id>/delete/', views.FinancialYearAPI.as_view(), name='financial_year_delete'),
    path('bank_cash/', views.bank_cash, name='bank_cash'),
    path('schedule/', views.schedule, name='schedule'),
    path('schedule_list/', views.ScheduleAPI.as_view(), name='schedule_list'),
    path('schedule/create/', views.ScheduleAPI.as_view(), name='schedule_create'),
    path('schedule/<int:id>/', views.ScheduleAPI.as_view(), name='schedule_update'),
    path('schedule/<int:id>/delete/', views.ScheduleAPI.as_view(), name='schedule_delete')

]
