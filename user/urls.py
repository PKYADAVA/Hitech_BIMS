# user/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('', views.login, name='login'),
    path('login/', views.login, name='login'),
    path('logout/', views.logout, name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('home/', views.home, name='home'),
    path('forgot-password/', views.forgot_password_view, name='forgot_password'),
    path('update_password/', views.update_password, name='update_password'),
    path('user_profile/', views.user_profile, name='user_profile'),
    path('create_user_temp/', views.create_user, name='create_user'),
    path('update_user/<int:user_id>/', views.update_user, name='update_user'),
    path('assign_permission_temp/', views.assign_groups, name='assign_groups'),
    path('manage_groups/', views.manage_groups, name='user_groups'),
    path('delete_group/', views.delete_group, name='delete_group'),
    path('get-assigned-groups/', views.get_assigned_groups, name='get_assigned_groups'),
    path('api/global-search/', views.global_search_api, name='global_search_api'),
    path('api/dashboard-widgets/', views.dashboard_widgets_api, name='dashboard_widgets_api'),
    path('dashboard-access/', views.dashboard_access, name='dashboard_access'),
    path('dashboard-access/form/', views.dashboard_access_form, name='dashboard_access_form'),
    path('dashboard-access/<int:group_id>/preview/', views.dashboard_access_preview, name='dashboard_access_preview'),
    path('dashboard-access/<int:group_id>/delete/', views.dashboard_access_delete, name='dashboard_access_delete'),
    path('user_analytics/', views.user_analytics, name='user_analytics'),
     path('analytics/data/', views.user_analytics_data, name='user_analytics_data'),

]
