"""URL configuration for the Employee Tracking module.

Page url-names are the Web-Access tab codes; API url-names are registered as
``extra_urls`` of their owning tab (see ``user/access.py``), so the
permission matrix guards everything here.
"""

from django.urls import path

from tracking import api_views, views

urlpatterns = [
    # Pages
    path("tracking/dashboard/", views.tracking_dashboard, name="tracking_dashboard"),
    path("tracking/attendance/", views.tracking_attendance, name="tracking_attendance"),
    path("tracking/visits/", views.tracking_visits, name="tracking_visits"),
    path("tracking/routes/", views.tracking_routes, name="tracking_routes"),
    path("tracking/reports/", views.tracking_reports, name="tracking_reports"),
    path("tracking/geofences/", views.tracking_geofences, name="tracking_geofences"),
    path("tracking/alerts/", views.tracking_alerts, name="tracking_alerts"),
    path("tracking/settings/", views.tracking_settings, name="tracking_settings"),
    # JSON APIs
    path("api/tracking/live/", api_views.LiveDashboardAPI.as_view(),
         name="api_tracking_live"),
    path("api/tracking/settings/", api_views.TrackingSettingsAPI.as_view(),
         name="api_tracking_settings"),
    path("api/tracking/providers/", api_views.TrackingProviderAPI.as_view(),
         name="api_tracking_providers"),
    path("api/tracking/providers/test/", api_views.ProviderTestAPI.as_view(),
         name="api_tracking_provider_test"),
    path("api/tracking/mappings/", api_views.MappingAPI.as_view(),
         name="api_tracking_mappings"),
    path("api/tracking/route/", api_views.RouteAPI.as_view(),
         name="api_tracking_route"),
    path("api/tracking/reports/", api_views.ReportsAPI.as_view(),
         name="api_tracking_reports"),
    path("api/tracking/visits/", api_views.VisitsAPI.as_view(),
         name="api_tracking_visits"),
    path("api/tracking/visits/link/", api_views.VisitLinkAPI.as_view(),
         name="api_tracking_visit_link"),
    path("api/tracking/attendance/", api_views.GpsAttendanceAPI.as_view(),
         name="api_tracking_attendance"),
    path("api/tracking/attendance/approve/", api_views.GpsAttendanceApprovalAPI.as_view(),
         name="api_tracking_attendance_approve"),
    path("api/tracking/sync-now/", api_views.SyncNowAPI.as_view(),
         name="api_tracking_sync_now"),
    path("api/tracking/geofences/", api_views.GeofenceAPI.as_view(),
         name="api_tracking_geofences"),
    path("api/tracking/alerts/", api_views.AlertsAPI.as_view(),
         name="api_tracking_alerts"),
    # Vendor-facing: secret-authenticated, no session (see WebhookAPI docstring).
    path("api/tracking/webhook/<int:provider_id>/", api_views.WebhookAPI.as_view(),
         name="api_tracking_webhook"),
]
