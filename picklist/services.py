# picklist/services.py
"""Runtime lookups used by templates (rendering) and views (validation)."""

from django.core.exceptions import ValidationError

from .models import FieldPicklistBinding, Picklist
from .sources import PICKLIST_SOURCE_MODELS


def resolve_options(picklist):
    """Return [(value, label), ...] for a Picklist, always live-queried."""
    if picklist is None:
        return []
    if picklist.source_type == Picklist.SourceType.STATIC:
        return [
            (v.value, v.label)
            for v in picklist.values.filter(is_active=True).order_by("sort_order", "label", "id")
        ]
    config = PICKLIST_SOURCE_MODELS.get(picklist.source_model_key)
    if not config:
        return []
    queryset = config["queryset_fn"]()
    value_field = config["value_field"]
    label_fn = config["label_fn"]
    return [(getattr(obj, value_field), label_fn(obj)) for obj in queryset]


def get_binding(app_label, model_name, field_name):
    return (
        FieldPicklistBinding.objects.select_related("picklist")
        .filter(app_label=app_label, model_name=model_name, field_name=field_name)
        .first()
    )


def get_field_config(app_label, model_name, field_name):
    """Resolve mode + options for template rendering. Always returns a dict."""
    binding = get_binding(app_label, model_name, field_name)
    if not binding or binding.mode != FieldPicklistBinding.Mode.PICKLIST or not binding.picklist_id:
        return {"mode": "FREE_TEXT", "options": [], "required": bool(binding and binding.is_required)}
    return {
        "mode": "PICKLIST",
        "options": resolve_options(binding.picklist),
        "required": binding.is_required,
    }


def validate_value(app_label, model_name, field_name, value):
    """Raise ValidationError if a PICKLIST-bound field's value isn't a current option."""
    binding = get_binding(app_label, model_name, field_name)
    if not binding or binding.mode != FieldPicklistBinding.Mode.PICKLIST or not binding.picklist_id:
        return
    if not value:
        if binding.is_required:
            raise ValidationError(f"{binding.human_label} is required.")
        return
    valid_values = {v for v, _ in resolve_options(binding.picklist)}
    if value not in valid_values:
        raise ValidationError(f"'{value}' is not a valid option for {binding.human_label}.")
