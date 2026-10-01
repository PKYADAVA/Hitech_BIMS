from django.db import migrations

DEFAULT_CHARGE_TYPES = [
    "Transport", "Loading", "Unloading", "Toll", "Handling",
    "Weighment", "Vehicle Hire", "Other",
]


def seed(apps, schema_editor):
    ChargeType = apps.get_model('inventory', 'ChargeType')
    for i, name in enumerate(DEFAULT_CHARGE_TYPES):
        ChargeType.objects.get_or_create(name=name, defaults={'sort_order': i})


def unseed(apps, schema_editor):
    ChargeType = apps.get_model('inventory', 'ChargeType')
    ChargeType.objects.filter(name__in=DEFAULT_CHARGE_TYPES).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0039_chargetype_transferchargeheader_transferchargeline_and_more'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
