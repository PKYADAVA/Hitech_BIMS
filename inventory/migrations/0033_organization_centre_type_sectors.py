import re

from django.db import migrations

NEW_SECTORS = [
    "Purchase", "General Warehouse", "Processing Plant", "Laboratory", "Quality Control",
]

# Sector.code -> clearer display name (code stays stable, only name changes).
RENAMES = {
    "FEED_STORE": "Feed Warehouse",
    "MEDICINE_STORE": "Medicine Warehouse",
}


def _code_for(name, taken):
    base = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper() or "SECTOR"
    code = base
    suffix = 1
    while code in taken:
        suffix += 1
        code = f"{base}_{suffix}"
    taken.add(code)
    return code


def add_and_rename_sectors(apps, schema_editor):
    Sector = apps.get_model("inventory", "Sector")
    taken = set(Sector.objects.values_list("code", flat=True))
    for name in NEW_SECTORS:
        if Sector.objects.filter(name=name).exists():
            continue
        Sector.objects.create(name=name, code=_code_for(name, taken))
    for code, new_name in RENAMES.items():
        Sector.objects.filter(code=code).update(name=new_name)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0032_flip_hatchery_office_mapping'),
    ]

    operations = [
        migrations.RunPython(add_and_rename_sectors, noop),
    ]
