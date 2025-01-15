"""
URL configuration for Hitech_BIMS project.
"""

from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("user.urls")),
    path("", include("broiler.urls")),
    path("", include("hr.urls")),
    path("", include("inventory.urls")),
    path("", include("account.urls")),
    path("", include("purchase.urls")),
    path("", include("sales.urls"))
]
