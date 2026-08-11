from django.contrib import admin

from .models import AppRelease


@admin.register(AppRelease)
class AppReleaseAdmin(admin.ModelAdmin):
    """Publish a new phone build: upload the APK, bump version_code, save.

    The app itself polls /api/v1/app-version for whichever row sorts first
    (highest version_code) — nothing else to wire up per release.
    """
    list_display = ("version", "version_code", "force_update", "created_at")
    list_filter = ("force_update",)
    ordering = ("-version_code",)
