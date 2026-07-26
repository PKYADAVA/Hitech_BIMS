from django.db import migrations

# bird_type choice value -> BirdCategory name
MAP = {"broiler": "Broiler", "layer": "Layer", "breeder": "Breeder"}


def forward(apps, schema_editor):
    FeedPhaseMaster = apps.get_model("broiler", "FeedPhaseMaster")
    BirdCategory = apps.get_model("broiler", "BirdCategory")
    for m in FeedPhaseMaster.objects.all():
        cat = BirdCategory.objects.filter(name=MAP.get(m.bird_type, "")).first()
        if cat:
            m.bird_category = cat
            m.save(update_fields=["bird_category"])


def backward(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("broiler", "0042_feedphasemaster_bird_category")]
    operations = [migrations.RunPython(forward, backward)]
