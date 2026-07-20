import re

from django.db import migrations, models

NEW_SECTORS = ["Department", "Farm", "Project", "Vehicle", "Production Unit"]


def _code_for(name, taken):
    base = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper() or "SECTOR"
    code = base
    suffix = 1
    while code in taken:
        suffix += 1
        code = f"{base}_{suffix}"
    taken.add(code)
    return code


def backfill_and_extend_sectors(apps, schema_editor):
    Sector = apps.get_model("inventory", "Sector")

    taken = set()
    for sector in Sector.objects.all():
        sector.code = _code_for(sector.name, taken)
        sector.save(update_fields=["code"])

    for name in NEW_SECTORS:
        if Sector.objects.filter(name=name).exists():
            continue
        Sector.objects.create(name=name, code=_code_for(name, taken))


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0029_alter_mapping_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='sector',
            name='code',
            field=models.CharField(blank=True, editable=False, default='',
                                    help_text='Auto-generated stable key, e.g. WAREHOUSE, BRANCH_OFFICE', max_length=30),
            preserve_default=False,
        ),
        migrations.RunPython(backfill_and_extend_sectors, noop),
        migrations.AlterField(
            model_name='sector',
            name='code',
            field=models.CharField(blank=True, editable=False, unique=True,
                                    help_text='Auto-generated stable key, e.g. WAREHOUSE, BRANCH_OFFICE', max_length=30),
        ),
    ]
