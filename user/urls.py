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
    # Named for the tab they serve, so user/access.py derives their rights:
    # create_user + toggle_active -> edit, create_user + delete -> delete.
    path('user/<int:user_id>/toggle-active/', views.toggle_user_active,
         name='create_user_toggle_active'),
    path('user/<int:user_id>/delete/', views.delete_user, name='create_user_delete'),
    # Named for the tab it serves, so user/access.py derives its rights.
    path('user/<int:user_id>/permissions/', views.user_permissions,
         name='create_user_permissions'),
    path('assign_permission_temp/', views.assign_groups, name='assign_groups'),
    path('manage_groups/', views.manage_groups, name='user_groups'),
    path('delete_group/', views.delete_group, name='delete_group'),
    path('get-assigned-groups/', views.get_assigned_groups, name='get_assigned_groups'),
    path('api/global-search/', views.global_search_api, name='global_search_api'),
    path('api/dashboard-widgets/', views.dashboard_widgets_api, name='dashboard_widgets_api'),
    path('api/master-import/<str:tab_code>/', views.master_import, name='master_import'),
    path('dashboard-access/', views.dashboard_access, name='dashboard_access'),
    path('dashboard-access/form/', views.dashboard_access_form, name='dashboard_access_form'),
    path('dashboard-access/<int:group_id>/preview/', views.dashboard_access_preview, name='dashboard_access_preview'),
    path('dashboard-access/<int:group_id>/delete/', views.dashboard_access_delete, name='dashboard_access_delete'),
    path('employee-access/', views.employee_access, name='employee_access'),
    path('employee-access/<int:pk>/row/', views.employee_access_row,
         name='employee_access_row'),
    path('employee-access/<int:pk>/delete/', views.employee_access_delete,
         name='employee_access_delete'),
    path('employee-access/employee/<int:pk>/', views.employee_access_info,
         name='employee_access_info'),
    path('mobile-access/', views.mobile_access, name='mobile_access'),
    path('mobile-access/form/', views.mobile_access_form, name='mobile_access_form'),
    path('mobile-access/<int:group_id>/preview/', views.mobile_access_preview, name='mobile_access_preview'),
    path('mobile-access/<int:group_id>/delete/', views.mobile_access_delete, name='mobile_access_delete'),
    path('user_analytics/', views.user_analytics, name='user_analytics'),
     path('analytics/data/', views.user_analytics_data, name='user_analytics_data'),

]
