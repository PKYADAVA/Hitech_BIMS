"""
URL configuration for Hitech_BIMS project.
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from .admin_import_template import admin_import_template
from .app_download import app_download

# Define URL patterns
urlpatterns = [
    # Sample-template download for every import-export admin Import page.
    # Must precede the admin catch-all so it resolves under /admin/.
    path("admin/import-template/", admin_import_template, name="admin_import_template"),
    path("admin/", admin.site.urls),
    # Public: the address staff are given to install the Android app.
    path("app/", app_download, name="app_download"),
    path("", include("user.urls")),
    path("", include("broiler.urls")),
    path("", include("hatchery.urls")),
    path("", include("hatchery_master.urls")),
    path("", include("hr.urls")),
    path("", include("inventory.urls")),
    path("", include("account.urls")),
    path("", include("purchase.urls")),
    path("", include("sales.urls")),
    path("", include("notification.urls")),
    path("", include("environmental_monitoring.urls")),
    path("", include("tracking.urls")),
    path("", include("picklist.urls")),
    # Alert & Audit module: /alerts/center/ page + /api/alerts/ REST API.
    path("", include("alerts.urls")),
    # Business Alerts & Notifications: /notifications/, /alert-config/ and the
    # /api/alerthub/ REST API that the bell, centre and dashboard widget read.
    path("", include("alerthub.urls")),
    # Mobile API v1 (JWT-authenticated; additive, does not affect the web app).
    path("api/v1/", include("api.urls")),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
