"""Django-admin registration for the Employee Tracking module.

The admin is a superuser-only maintenance surface (WebAccessMiddleware bounces
everyone else); day-to-day configuration happens on the module's own Settings
page. Credential fields are write-only here — existing values are never
rendered back.
"""

from django import forms
from django.contrib import admin

from .models import (
    EmployeeCustomerVisit,
    EmployeeGeofence,
    EmployeeGpsAttendance,
    EmployeeLiveLocation,
    EmployeeLocationHistory,
    EmployeeProviderMapping,
    EmployeeRoute,
    EmployeeRoutePoint,
    TrackingLog,
    TrackingProvider,
    TrackingSettings,
    TrackingSync,
)

SECRET_FIELDS = ("password", "access_token", "api_key", "webhook_secret")


class TrackingProviderForm(forms.ModelForm):
    """Renders secrets as blank password inputs; blank submit keeps the stored value."""

    class Meta:
        model = TrackingProvider
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in SECRET_FIELDS:
            self.fields[field_name].widget = forms.PasswordInput(render_value=False)
            self.fields[field_name].required = False
            if self.instance.pk:
                self.fields[field_name].help_text = (
                    "Leave blank to keep the currently stored value."
                )

    def clean(self):
        cleaned = super().clean()
        if self.instance.pk:
            for field_name in SECRET_FIELDS:
                if not cleaned.get(field_name):
                    cleaned[field_name] = getattr(self.instance, field_name)
        return cleaned


@admin.register(TrackingProvider)
class TrackingProviderAdmin(admin.ModelAdmin):
    form = TrackingProviderForm
    list_display = ("name", "provider_type", "is_active", "priority",
                    "refresh_interval_seconds", "last_sync_status", "last_synced_at")
    list_filter = ("provider_type", "is_active")
    search_fields = ("name", "api_url")
    readonly_fields = ("last_sync_status", "last_synced_at", "last_error",
                       "created_at", "updated_at")


@admin.register(EmployeeProviderMapping)
class EmployeeProviderMappingAdmin(admin.ModelAdmin):
    list_display = ("employee", "provider", "external_id", "external_name",
                    "is_active", "last_seen_at")
    list_filter = ("provider", "is_active")
    search_fields = ("employee__full_name", "external_id", "external_name")
    raw_id_fields = ("employee",)


@admin.register(TrackingSync)
class TrackingSyncAdmin(admin.ModelAdmin):
    list_display = ("provider", "sync_type", "status", "triggered_by", "started_at",
                    "finished_at", "records_fetched", "records_created", "records_skipped")
    list_filter = ("provider", "sync_type", "status", "triggered_by")
    date_hierarchy = "started_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(EmployeeLiveLocation)
class EmployeeLiveLocationAdmin(admin.ModelAdmin):
    list_display = ("employee", "status", "latitude", "longitude", "speed_kmh",
                    "battery_pct", "recorded_at", "synced_at")
    list_filter = ("status", "gps_enabled")
    search_fields = ("employee__full_name",)

    def has_add_permission(self, request):
        return False


@admin.register(EmployeeLocationHistory)
class EmployeeLocationHistoryAdmin(admin.ModelAdmin):
    list_display = ("employee", "recorded_at", "latitude", "longitude",
                    "speed_kmh", "event_type")
    list_filter = ("event_type",)
    search_fields = ("employee__full_name",)
    date_hierarchy = "recorded_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class EmployeeRoutePointInline(admin.TabularInline):
    model = EmployeeRoutePoint
    extra = 0
    can_delete = False
    readonly_fields = [f.name for f in EmployeeRoutePoint._meta.fields]


@admin.register(EmployeeRoute)
class EmployeeRouteAdmin(admin.ModelAdmin):
    list_display = ("employee", "date", "total_distance_km", "stops_count",
                    "average_speed_kmh", "is_finalized")
    list_filter = ("is_finalized",)
    search_fields = ("employee__full_name",)
    date_hierarchy = "date"
    inlines = [EmployeeRoutePointInline]

    def has_add_permission(self, request):
        return False


@admin.register(EmployeeCustomerVisit)
class EmployeeCustomerVisitAdmin(admin.ModelAdmin):
    list_display = ("employee", "customer", "visit_date", "status",
                    "check_in_at", "check_out_at", "duration")
    list_filter = ("status",)
    search_fields = ("employee__full_name", "customer__name")
    date_hierarchy = "visit_date"


@admin.register(EmployeeGpsAttendance)
class EmployeeGpsAttendanceAdmin(admin.ModelAdmin):
    list_display = ("employee", "date", "check_in_at", "check_out_at",
                    "is_late", "is_early_exit", "check_in_inside_fence", "status")
    list_filter = ("status", "is_late", "is_early_exit")
    search_fields = ("employee__full_name",)
    date_hierarchy = "date"
    readonly_fields = ("attendance", "approved_by", "approved_at")

    def has_add_permission(self, request):
        return False


@admin.register(EmployeeGeofence)
class EmployeeGeofenceAdmin(admin.ModelAdmin):
    list_display = ("name", "geofence_type", "radius_m", "is_active",
                    "alert_on_entry", "alert_on_exit")
    list_filter = ("geofence_type", "is_active")
    search_fields = ("name", "address")


@admin.register(TrackingLog)
class TrackingLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "log_type", "event", "severity", "employee", "message")
    list_filter = ("log_type", "severity", "event")
    search_fields = ("message", "employee__full_name")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TrackingSettings)
class TrackingSettingsAdmin(admin.ModelAdmin):
    list_display = ("__str__", "enabled", "map_provider", "modified_by", "modified_at")

    def has_add_permission(self, request):
        # Singleton: the row is created by get_solo(); never add a second.
        return not TrackingSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
