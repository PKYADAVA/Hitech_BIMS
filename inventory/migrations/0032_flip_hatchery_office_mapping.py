from django.db import migrations


def flip(apps, schema_editor):
    Mapping = apps.get_model("inventory", "Mapping")
    for row in Mapping.objects.filter(type="hatchery_office"):
        row.from_id, row.to_id = row.to_id, row.from_id
        row.save(update_fields=["from_id", "to_id"])


class Migration(migrations.Migration):
    """Hatchery -> Office was keyed one-row-per-hatchery (a hatchery could
    only ever point at a single office). Flips it to one-row-per-office
    (from_id=warehouse, to_id=hatchery) so one hatchery can have several
    offices, the same shape Sector -> Branch already uses. flip() is its own
    inverse, so it doubles as the reverse migration."""

    dependencies = [
        ('inventory', '0031_more_cost_centre_sectors'),
    ]

    operations = [
        migrations.RunPython(flip, flip),
    ]
