from django.contrib import admin

from .models import AppRelease, ImpersonationSettings


@admin.register(AppRelease)
class AppReleaseAdmin(admin.ModelAdmin):
    """Publish a new phone build: upload the APK, bump version_code, save.

    The app itself polls /api/v1/app-version for whichever row sorts first
    (highest version_code) — nothing else to wire up per release.
    """
    list_display = ("version", "version_code", "force_update", "created_at")
    list_filter = ("force_update",)
    ordering = ("-version_code",)


@admin.register(ImpersonationSettings)
class ImpersonationSettingsAdmin(admin.ModelAdmin):
    """The switch behind User > Users > "View as".

    Here rather than on a page of its own because it is the kind of thing that
    should take a deliberate trip to the admin to change, like the other
    posting switches. Off until somebody turns it on.
    """

    list_display = ("enabled", "modified_at")
    readonly_fields = ("modified_at",)

    def has_add_permission(self, request):
        # One row, reached through get_solo(); adding a second would only make
        # it ambiguous which one the ERP reads.
        return not ImpersonationSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
