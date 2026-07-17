# picklist/checks.py
"""System check verifying every BINDABLE_FIELDS entry resolves to a real
model field, so a typo/renamed field fails `python manage.py check` loudly
instead of silently at render time."""

from django.apps import apps as django_apps
from django.core.checks import Error, register


@register()
def check_bindable_fields(app_configs, **kwargs):
    from .bindable_fields import BINDABLE_FIELDS

    errors = []
    for entry in BINDABLE_FIELDS:
        app_label, model_name, field_name = entry["app_label"], entry["model_name"], entry["field_name"]
        try:
            model = django_apps.get_model(app_label, model_name)
        except LookupError:
            errors.append(Error(
                f"BINDABLE_FIELDS entry references unknown model '{app_label}.{model_name}'.",
                id="picklist.E001",
            ))
            continue
        try:
            model._meta.get_field(field_name)
        except Exception:
            errors.append(Error(
                f"BINDABLE_FIELDS entry references unknown field "
                f"'{field_name}' on '{app_label}.{model_name}'.",
                id="picklist.E002",
            ))
    return errors
