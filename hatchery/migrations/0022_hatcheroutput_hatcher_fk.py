import django.db.models.deletion
from django.db import migrations, models


def backfill_hatcher(apps, schema_editor):
    HatchEntryHatcherOutput = apps.get_model("hatchery", "HatchEntryHatcherOutput")
    Hatcher = apps.get_model("hatchery_master", "Hatcher")
    for row in HatchEntryHatcherOutput.objects.select_related(
        "hatch_entry__tray_setting__hatchery"
    ):
        hatchery = row.hatch_entry.tray_setting.hatchery
        label = (row.hatcher_no or "").strip() or "UNSPECIFIED"
        hatcher, _created = Hatcher.objects.get_or_create(
            hatchery=hatchery, hatcher_no=label, defaults={"capacity": 0},
        )
        row.hatcher_id = hatcher.id
        row.save(update_fields=["hatcher"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("hatchery_master", "0003_hatcher"),
        ("hatchery", "0021_hatchentryhatcheroutput"),
    ]

    operations = [
        migrations.AddField(
            model_name="hatchentryhatcheroutput",
            name="hatcher",
            field=models.ForeignKey(
                null=True, blank=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="hatch_entry_outputs", to="hatchery_master.hatcher",
            ),
        ),
        migrations.RunPython(backfill_hatcher, noop),
    ]
