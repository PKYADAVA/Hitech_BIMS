from django.apps import AppConfig


class AlertHubConfig(AppConfig):
    """Business alerting: thresholds, notifications and the alert centre.

    Distinct from the ``alerts`` app, which is the CRUD audit trail. That one
    records *what a user did to a row*; this one records *what the business
    needs someone to look at*. They share a word and nothing else.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "alerthub"
    verbose_name = "Alerts & Notifications"

    def ready(self):
        # Import the detector modules so their decorators register. Cheap —
        # they only bind functions; every model import inside them is deferred
        # to call time so this cannot run during app loading.
        from . import detectors

        detectors.autodiscover()
