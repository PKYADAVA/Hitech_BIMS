from django.urls import path

from . import views

urlpatterns = [
    path('hatchery-master/', views.hatchery_master_list, name='hatchery_master_list'),
    path('hatchery-master/add/', views.create_hatchery, name='hatchery_master_create'),
    path('hatchery-master/<int:id>/edit/', views.edit_hatchery, name='hatchery_master_edit'),
    path('hatchery-master/<int:id>/delete/', views.delete_hatchery, name='hatchery_master_delete'),
    path('hatchery-master/<int:id>/toggle-active/', views.toggle_hatchery_active, name='hatchery_master_toggle_active'),
    path('hatchery-master/<int:id>/toggle-lock/', views.toggle_hatchery_lock, name='hatchery_master_toggle_lock'),

    path('setter/', views.setter_list, name='setter_list'),
    path('setter/add/', views.create_setter, name='setter_create'),
    path('setter/<int:id>/edit/', views.edit_setter, name='setter_edit'),
    path('setter/<int:id>/delete/', views.delete_setter, name='setter_delete'),
    path('setter/<int:id>/toggle-active/', views.toggle_setter_active, name='setter_toggle_active'),
    path('setter/<int:id>/toggle-lock/', views.toggle_setter_lock, name='setter_toggle_lock'),

    path('hatcher/', views.hatcher_list, name='hatcher_list'),
    path('hatcher/add/', views.create_hatcher, name='hatcher_create'),
    path('hatcher/<int:id>/edit/', views.edit_hatcher, name='hatcher_edit'),
    path('hatcher/<int:id>/delete/', views.delete_hatcher, name='hatcher_delete'),
    path('hatcher/<int:id>/toggle-active/', views.toggle_hatcher_active, name='hatcher_toggle_active'),
    path('hatcher/<int:id>/toggle-lock/', views.toggle_hatcher_lock, name='hatcher_toggle_lock'),

    path('expense-type/', views.expense_type_list, name='expense_type_list'),
    path('expense-type/add/', views.create_expense_type, name='expense_type_create'),
    path('expense-type/<int:id>/edit/', views.edit_expense_type, name='expense_type_edit'),
    path('expense-type/<int:id>/delete/', views.delete_expense_type, name='expense_type_delete'),
    path('expense-type/<int:id>/toggle-active/', views.toggle_expense_type_active, name='expense_type_toggle_active'),
    path('expense-type/<int:id>/toggle-lock/', views.toggle_expense_type_lock, name='expense_type_toggle_lock'),

    path('hatchery-expense/', views.hatchery_expense_list, name='hatchery_expense_list'),
    path('hatchery-expense/add/', views.create_hatchery_expense, name='hatchery_expense_create'),
    path('hatchery-expense/<int:id>/edit/', views.edit_hatchery_expense, name='hatchery_expense_edit'),
    path('hatchery-expense/<int:id>/delete/', views.delete_hatchery_expense, name='hatchery_expense_delete'),
    path('hatchery-expense/<int:id>/toggle-active/', views.toggle_hatchery_expense_active, name='hatchery_expense_toggle_active'),
    path('hatchery-expense/<int:id>/toggle-lock/', views.toggle_hatchery_expense_lock, name='hatchery_expense_toggle_lock'),
]
