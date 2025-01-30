# user/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('register/', views.register, name='register'),
    path('', views.login, name='login'),
    path('login/', views.login, name='login'),
    path('logout/', views.logout, name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('home/', views.home, name='home'),
    path('forgot-password/', views.forgot_password_view, name='forgot_password'),  
    path('user_management/', views.user_management, name='user_management'),
    path('update_password/', views.update_password, name='update_password'),
    path('user_profile/', views.user_profile, name='user_profile'),
    path('create_user_temp/', views.create_user, name='create_user'),
    path('assign_permission_temp/', views.assign_groups, name='assign_groups'),
    path('manage_groups/', views.manage_groups, name='user_groups'),
    path('delete_group/', views.delete_group, name='delete_group'),
    path('get-assigned-groups/', views.get_assigned_groups, name='get_assigned_groups'),
    path('user_analytics/', views.user_analytics, name='user_analytics'),

]
