"""App configuration for the Employee Tracking module."""

from django.apps import AppConfig


class TrackingConfig(AppConfig):
    """Employee Tracking — provider-agnostic GPS tracking (TrackoLap, …)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "tracking"
    verbose_name = "Employee Tracking"
