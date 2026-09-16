"""Let a farm be recorded without its bird capacity.

Capacity is surveyed, not always known when a farm is first entered, and the
form refused to save without it. Every reader already copes with it missing —
the reports render a dash, the utilisation figure reports "unknown" rather
than 0%, and the phone's farm form never marked it required in the first
place, so a farm entered there could not be saved at all.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("broiler", "0076_farmer_farmer_code")]

    operations = [
        migrations.AlterField(
            model_name="broilerfarm",
            name="farm_capacity",
            field=models.PositiveIntegerField(
                blank=True, null=True, help_text="Bird capacity of the farm"),
        ),
    ]
