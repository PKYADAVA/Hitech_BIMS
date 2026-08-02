from django.core.validators import MinValueValidator
from django.db import migrations, models


def set_refresh_to_120(apps, schema_editor):
    """Bump the live dashboard to a 2-minute (120s) auto-refresh.

    Editable afterwards from Tracking Settings; this just moves the running
    value off the old 30s default. Only rows still on the previous default are
    touched, so any deliberately-customised interval is preserved.
    """
    TrackingSettings = apps.get_model("tracking", "TrackingSettings")
    TrackingSettings.objects.filter(dashboard_refresh_seconds=30).update(
        dashboard_refresh_seconds=120
    )


def revert_refresh_to_30(apps, schema_editor):
    TrackingSettings = apps.get_model("tracking", "TrackingSettings")
    TrackingSettings.objects.filter(dashboard_refresh_seconds=120).update(
        dashboard_refresh_seconds=30
    )


class Migration(migrations.Migration):

    dependencies = [
        ("tracking", "0006_employeelivelocation_heartbeat_at_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="trackingsettings",
            name="dashboard_refresh_seconds",
            field=models.PositiveIntegerField(
                default=120,
                help_text="Auto-refresh interval of the live dashboard (seconds).",
                validators=[MinValueValidator(10)],
            ),
        ),
        migrations.RunPython(set_refresh_to_120, revert_refresh_to_30),
    ]
