from django import template

from picklist.services import get_field_config

register = template.Library()


@register.inclusion_tag("picklist/_field.html")
def render_picklist_field(
    binding_path, current_value="", field_id=None, field_name=None,
    placeholder="", required=False,
):
    """Render a free-text <input> or a picklist-bound <select>.

    ``binding_path`` is "app_label.ModelName.field_name" (must be a
    registered BINDABLE_FIELDS entry). Falls back to a plain text input
    when the field has no PICKLIST binding, so unmigrated fields render
    exactly as they did before.
    """
    app_label, model_name, field = binding_path.split(".")
    config = get_field_config(app_label, model_name, field)
    return {
        "mode": config["mode"],
        "options": config["options"],
        "required": required or config["required"],
        "current_value": current_value or "",
        "field_id": field_id or field,
        "field_name": field_name or field,
        "placeholder": placeholder,
    }
