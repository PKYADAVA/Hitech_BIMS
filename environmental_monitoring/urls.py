from django.urls import path

from . import views

urlpatterns = [
    path('environmental-monitoring/dashboard/', views.dashboard, name='env_dashboard'),
    path('environmental-monitoring/settings/tapo-account/', views.tapo_account_settings, name='env_tapo_account'),
    path('environmental-monitoring/settings/default-thresholds/', views.default_thresholds_settings, name='env_default_thresholds'),
    path('environmental-monitoring/api/status/', views.sensor_status_api, name='env_api_status'),
    path('environmental-monitoring/api/sensor/<int:id>/history/', views.sensor_history_api, name='env_api_readings'),
    path('environmental-monitoring/api/ingest/', views.ingest_hub_reading, name='env_api_ingest'),

    path('environmental-monitoring/hubs/', views.hub_list, name='env_hub_list'),
    path('environmental-monitoring/hubs/add/', views.create_hub, name='env_hub_create'),
    path('environmental-monitoring/hubs/<int:id>/edit/', views.edit_hub, name='env_hub_edit'),
    path('environmental-monitoring/hubs/<int:id>/delete/', views.delete_hub, name='env_hub_delete'),
    path('environmental-monitoring/hubs/<int:id>/regenerate-token/', views.regenerate_hub_token, name='env_hub_regenerate_token'),

    path('environmental-monitoring/sensors/', views.sensor_list, name='env_sensor_list'),
    path('environmental-monitoring/sensors/<int:id>/edit/', views.edit_sensor, name='env_sensor_edit'),

    path('environmental-monitoring/alerts/', views.alert_list, name='env_alert_list'),
    path('environmental-monitoring/alerts/<int:id>/acknowledge/', views.acknowledge_alert, name='env_alert_acknowledge'),
    path('environmental-monitoring/alerts/clear-all/', views.clear_all_alerts, name='env_alert_clear_all'),
]
