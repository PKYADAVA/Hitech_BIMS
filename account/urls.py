from django.urls import path
from . import views

urlpatterns = [
   
    path('account/', views.account, name='account'),
    path('coa/', views.coa, name='coa'),
    path('fin_year/', views.fin_year, name='fin_year'),
    path('bank_cash/', views.bank_cash, name='bank_cash'),
    path('schedule/', views.schedule, name='schedule'),
]
