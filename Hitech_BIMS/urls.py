"""
URL configuration for Hitech_BIMS project.
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

# Define URL patterns
urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("user.urls")),
    path("", include("broiler.urls")),
    path("", include("hr.urls")),
    path("", include("inventory.urls")),
    path("", include("account.urls")),
    path("", include("purchase.urls")),
    path("", include("sales.urls")),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
