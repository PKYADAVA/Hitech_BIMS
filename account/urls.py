from django.urls import path
from . import views
from . import api_views
from . import journal_api

urlpatterns = [
    # Chart of Accounts engine APIs
    path('api/chart-of-accounts/', api_views.CoAListCreateAPI.as_view(), name='api_coa_list'),
    path('api/chart-of-accounts/tree/', api_views.CoATreeAPI.as_view(), name='api_coa_tree'),
    path('api/chart-of-accounts/search/', api_views.CoASearchAPI.as_view(), name='api_coa_search'),
    path('api/chart-of-accounts/templates/', api_views.CoATemplatesAPI.as_view(), name='api_coa_templates'),
    path('api/chart-of-accounts/generate/', api_views.CoAGenerateAPI.as_view(), name='api_coa_generate'),
    path('api/chart-of-accounts/import/', api_views.CoAImportAPI.as_view(), name='api_coa_import'),
    path('api/chart-of-accounts/import/template/', api_views.CoAImportTemplateAPI.as_view(), name='api_coa_import_template'),
    path('api/chart-of-accounts/export/', api_views.CoAExportAPI.as_view(), name='api_coa_export'),
    path('api/chart-of-accounts/opening-balance/', api_views.CoAOpeningBalanceAPI.as_view(), name='api_coa_opening_balance'),
    path('api/chart-of-accounts/audit/', api_views.CoAAuditLogAPI.as_view(), name='api_coa_audit'),
    path('api/chart-of-accounts/<int:id>/', api_views.CoADetailAPI.as_view(), name='api_coa_detail'),
    # Journal engine APIs
    path('vouchers/', views.vouchers, name='vouchers'),
    path('api/vouchers/', journal_api.VoucherListCreateAPI.as_view(), name='api_voucher_list'),
    path('api/vouchers/<int:id>/', journal_api.VoucherDetailAPI.as_view(), name='api_voucher_detail'),
    path('api/vouchers/<int:id>/post/', journal_api.VoucherPostAPI.as_view(), name='api_voucher_post'),
    path('api/vouchers/<int:id>/cancel/', journal_api.VoucherCancelAPI.as_view(), name='api_voucher_cancel'),
    path('api/chart-of-accounts/<int:id>/ledger/', journal_api.AccountLedgerAPI.as_view(), name='api_coa_ledger'),
    path('api/reports/trial-balance/', journal_api.TrialBalanceAPI.as_view(), name='api_trial_balance'),
    path('reports/ledger/', views.ledger_report, name='ledger_report'),
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
    path('company-profile/', views.company_profile, name='company_profile'),
    path('terms/', views.terms, name='terms'),
    path('terms_conditions/', views.TermsConditionsAPI.as_view(), name='terms_conditions_list'),
    path('terms_conditions/create/', views.TermsConditionsAPI.as_view(), name='terms_conditions_create'),
    path('terms_conditions/<int:id>/', views.TermsConditionsAPI.as_view(), name='terms_conditions_update'),
    path('terms_conditions/<int:id>/delete', views.TermsConditionsAPI.as_view(), name='terms_conditions_delete'),

]
