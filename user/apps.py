from django.apps import AppConfig


class UserConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "user"

    def ready(self):
        # Wires the Mobile Access cache invalidation. Imported for the side
        # effect of connecting the signals — an access cache that can serve a
        # stale "yes" is a security bug, so this must not depend on whichever
        # view happens to write the tables.
        from . import signals  # noqa: F401
