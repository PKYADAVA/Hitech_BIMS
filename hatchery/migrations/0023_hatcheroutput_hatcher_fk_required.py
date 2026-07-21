import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("hatchery", "0022_hatcheroutput_hatcher_fk"),
    ]

    operations = [
        migrations.AlterField(
            model_name="hatchentryhatcheroutput",
            name="hatcher",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="hatch_entry_outputs", to="hatchery_master.hatcher",
            ),
        ),
        migrations.RemoveField(
            model_name="hatchentryhatcheroutput",
            name="hatcher_no",
        ),
    ]
