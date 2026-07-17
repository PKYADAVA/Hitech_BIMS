# picklist/sources.py
"""
Curated allowlist of models a "model-sourced" Picklist may pull its options
from. An admin picks a source by its friendly label in the Picklist Master UI;
the actual queryset/value/label wiring below is developer-defined so a bad
filter or field name can never be entered through the UI.

These are *soft* references: the picklist-bound field stays a plain text
column (no DB foreign key), validated at save time against a live query of
the source model. Use a real ForeignKey instead when you need cascade
behaviour or DB-level referential integrity.
"""

from django.apps import apps


def _vendor_group_queryset():
    VendorGroup = apps.get_model("purchase", "VendorGroup")
    return VendorGroup.objects.all()


def _vendor_group_label(obj):
    return f"{obj.code} - {obj.description}" if obj.description else (obj.code or str(obj.pk))


def _chart_of_account_queryset():
    ChartOfAccount = apps.get_model("account", "ChartOfAccount")
    return ChartOfAccount.objects.filter(status="Active")


def _chart_of_account_label(obj):
    return str(obj)


def _customer_group_queryset():
    CustomerGroup = apps.get_model("sales", "CustomerGroup")
    return CustomerGroup.objects.all()


def _customer_group_label(obj):
    return f"{obj.code} - {obj.description}" if obj.description else (obj.code or str(obj.pk))


PICKLIST_SOURCE_MODELS = {
    "vendor_group": {
        "label": "Vendor Group",
        "value_field": "code",
        "label_fn": _vendor_group_label,
        "queryset_fn": _vendor_group_queryset,
    },
    "customer_group": {
        "label": "Customer Group",
        "value_field": "code",
        "label_fn": _customer_group_label,
        "queryset_fn": _customer_group_queryset,
    },
    "chart_of_account_active": {
        "label": "Chart of Accounts (Active)",
        "value_field": "code",
        "label_fn": _chart_of_account_label,
        "queryset_fn": _chart_of_account_queryset,
    },
}

SOURCE_MODEL_CHOICES = [(key, cfg["label"]) for key, cfg in PICKLIST_SOURCE_MODELS.items()]
