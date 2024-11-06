# user/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('hr/', views.hr, name='hr'), 
]
   
