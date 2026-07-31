"""Admin for alert configuration and the notification record."""
from __future__ import annotations

from django.contrib import admin
from django.utils.html import format_html

from .constants import PRIORITY_COLOR
from .models import (
    AlertRule,
    Notification,
    NotificationPreference,
    NotificationRecipient,
)


def _priority_pill(priority, label):
    return format_html(
        '<span style="background:{};color:#fff;border-radius:1rem;'
        'padding:.1rem .55rem;font-size:.75rem;font-weight:600">{}</span>',
        PRIORITY_COLOR.get(priority, "#6b7280"), label,
    )


@admin.register(AlertRule)
class AlertRuleAdmin(admin.ModelAdmin):
    list_display = ("name", "module", "rule_key", "priority_pill", "threshold",
                    "is_active", "supported")
    list_filter = ("module", "priority", "is_active", "via_email", "via_sms")
    search_fields = ("name", "rule_key")
    filter_horizontal = ("notify_groups", "notify_branches", "notify_org_centres",
                         "notify_farms", "notify_warehouses")
    readonly_fields = ("module", "created_by", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("name", "rule_key", "module", "priority", "is_active")}),
        ("Trigger condition", {"fields": ("operator", "threshold",
                                          "cooldown_hours")}),
        ("Notify", {"fields": ("notify_groups", "notify_branches",
                               "notify_org_centres", "notify_farms",
                               "notify_warehouses")}),
        ("Channels", {"fields": ("via_in_app", "via_email", "via_sms",
                                 "via_whatsapp")}),
        ("Audit", {"fields": ("created_by", "created_at", "updated_at")}),
    )

    @admin.display(description="Priority", ordering="priority")
    def priority_pill(self, obj):
        return _priority_pill(obj.priority, obj.get_priority_display())

    @admin.display(boolean=True, description="Has detector")
    def supported(self, obj):
        return obj.is_supported

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


class RecipientInline(admin.TabularInline):
    model = NotificationRecipient
    extra = 0
    can_delete = False
    readonly_fields = ("user", "is_read", "read_at", "delivered_channels",
                       "created_at")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    """Read-only. Notifications are a record of what people were told; editing
    one after the fact would make the history a claim rather than evidence."""

    list_display = ("created_at", "priority_pill", "module", "title",
                    "scope_label", "recipient_count")
    list_filter = ("module", "priority", "rule_key", "created_at")
    search_fields = ("title", "message", "object_display", "voucher_no")
    date_hierarchy = "created_at"
    inlines = [RecipientInline]
    readonly_fields = [f.name for f in Notification._meta.fields]

    @admin.display(description="Priority", ordering="priority")
    def priority_pill(self, obj):
        return _priority_pill(obj.priority, obj.get_priority_display())

    @admin.display(description="Place")
    def scope_label(self, obj):
        return obj.scope_label or "—"

    @admin.display(description="Sent to")
    def recipient_count(self, obj):
        return obj.recipients.count()

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ("user", "receive_in_app", "receive_email", "receive_sms",
                    "receive_whatsapp", "min_priority", "updated_at")
    list_filter = ("receive_in_app", "receive_email", "min_priority")
    search_fields = ("user__username", "user__first_name", "user__last_name")
