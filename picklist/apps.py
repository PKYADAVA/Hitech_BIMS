from django.apps import AppConfig


class PicklistConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "picklist"
    verbose_name = "Picklist Master"

    def ready(self):
        from . import checks  # noqa: F401 — registers the system check
