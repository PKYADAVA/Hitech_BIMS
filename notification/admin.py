"""Admin registration for editable SMS and WhatsApp templates."""

from django.contrib import admin

from .models import SmsTemplate, WhatsappTemplate


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


@admin.register(WhatsappTemplate)
class WhatsappTemplateAdmin(admin.ModelAdmin):
    list_display = ("key", "module", "name", "template_name", "language", "is_active", "updated_at")
    list_filter = ("module", "is_active", "header_type")
    search_fields = ("key", "name", "template_name", "description")
    list_editable = ("is_active",)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("key", "module", "name", "is_active")}),
        ("Meta template", {"fields": ("template_name", "language", "parameter_map",
                                      "header_type", "header_media_url")}),
        ("Content", {"fields": ("description",)}),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )
