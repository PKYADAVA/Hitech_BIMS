"""Admin registration for editable SMS templates."""

from django.contrib import admin

from .models import SmsTemplate


@admin.register(SmsTemplate)
class SmsTemplateAdmin(admin.ModelAdmin):
    list_display = ("key", "module", "name", "is_active", "updated_at")
    list_filter = ("module", "is_active")
    search_fields = ("key", "name", "body", "description")
    list_editable = ("is_active",)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("key", "module", "name", "is_active")}),
        ("Content", {"fields": ("body", "description", "dlt_template_id")}),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )
