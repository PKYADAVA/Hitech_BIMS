from django.apps import AppConfig


class InventoryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "inventory"

    def ready(self):
        # Records every Item Price List change, however it is made.
        from . import price_audit  # noqa: F401
