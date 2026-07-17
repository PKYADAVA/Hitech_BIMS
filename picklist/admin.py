from django.contrib import admin

from .models import FieldPicklistBinding, Picklist, PicklistValue


class PicklistValueInline(admin.TabularInline):
    model = PicklistValue
    extra = 1


@admin.register(Picklist)
class PicklistAdmin(admin.ModelAdmin):
    list_display = ("key", "name", "source_type", "source_model_key", "is_active")
    list_filter = ("source_type", "is_active")
    search_fields = ("key", "name")
    inlines = [PicklistValueInline]


@admin.register(FieldPicklistBinding)
class FieldPicklistBindingAdmin(admin.ModelAdmin):
    list_display = ("app_label", "model_name", "field_name", "mode", "picklist", "is_required")
    list_filter = ("app_label", "mode")
    search_fields = ("app_label", "model_name", "field_name")
