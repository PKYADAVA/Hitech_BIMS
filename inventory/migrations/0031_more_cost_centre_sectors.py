import re

from django.db import migrations

NEW_SECTORS = [
    "Unit", "Shed", "Feed Store", "Medicine Store", "Sales",
    "Administration", "Maintenance", "Transport", "HR", "Finance", "Other",
]


def _code_for(name, taken):
    base = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper() or "SECTOR"
    code = base
    suffix = 1
    while code in taken:
        suffix += 1
        code = f"{base}_{suffix}"
    taken.add(code)
    return code


def add_sectors(apps, schema_editor):
    Sector = apps.get_model("inventory", "Sector")
    taken = set(Sector.objects.values_list("code", flat=True))
    for name in NEW_SECTORS:
        if Sector.objects.filter(name=name).exists():
            continue
        Sector.objects.create(name=name, code=_code_for(name, taken))


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0030_sector_code'),
    ]

    operations = [
        migrations.RunPython(add_sectors, noop),
    ]
