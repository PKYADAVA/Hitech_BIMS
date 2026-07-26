from django.db import migrations

CATEGORIES = [
    "Broiler", "Layer", "Breeder", "Parent Stock", "Grand Parent",
    "Commercial Layer", "Commercial Broiler", "Turkey", "Duck", "Quail", "Other",
]


def seed(apps, schema_editor):
    BirdCategory = apps.get_model("broiler", "BirdCategory")
    for i, name in enumerate(CATEGORIES, start=1):
        BirdCategory.objects.get_or_create(name=name, defaults={"sort_order": i})


def unseed(apps, schema_editor):
    BirdCategory = apps.get_model("broiler", "BirdCategory")
    BirdCategory.objects.filter(name__in=CATEGORIES).delete()


class Migration(migrations.Migration):
    dependencies = [("broiler", "0039_birdcategory")]
    operations = [migrations.RunPython(seed, unseed)]
