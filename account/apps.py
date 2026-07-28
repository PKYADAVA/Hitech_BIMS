from django.apps import AppConfig


class AccountConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "account"

    def ready(self):
        from . import signals  # noqa: F401  (registers auto-ledger receivers)
        from Hitech_BIMS import remarks_describe  # noqa: F401  (auto-fill blank remarks on save)
        from Hitech_BIMS import text_format  # noqa: F401  (Title-Case remarks/narration on save)
