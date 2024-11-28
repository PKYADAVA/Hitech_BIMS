"""
URL configuration for employee-related views in the HR application.
"""
from django.urls import path
from hr.views import (
    delete_employee,
    edit_employee,
    employee_list,
    create_new_employee
)

urlpatterns = [
    path('employees/', employee_list, name='employee_list'),
    path('employees/new/', create_new_employee, name='create_new_employee'),
    path('employees/<int:pk>/edit/', edit_employee, name='edit_employee'),
    path('employees/<int:pk>/delete/', delete_employee, name='delete_employee'),
    
]
   
