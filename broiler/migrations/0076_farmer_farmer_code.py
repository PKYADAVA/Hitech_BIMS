"""Give every farmer a code.

The farmer was the one master here without one — its neighbours (farmer group,
region, branch, supervisor, farm) all mint theirs on first save, so a farmer
could only be referred to by name.

Existing rows are numbered oldest first, so FRM-0001 is the farmer who has
been on the books longest and the codes keep counting up the way new ones
will. ``created_at`` has been on the model since it was created and was never
backfilled, so it is a real creation time rather than a migration timestamp;
``id`` breaks ties, and covers any row whose timestamp is somehow equal.
"""
from django.db import migrations, models


def issue_codes(apps, schema_editor):
    Farmer = apps.get_model("broiler", "Farmer")
    for serial, farmer in enumerate(Farmer.objects.order_by("created_at", "id"), start=1):
        Farmer.objects.filter(pk=farmer.pk).update(farmer_code=f"FRM-{serial:04d}")


def drop_codes(apps, schema_editor):
    apps.get_model("broiler", "Farmer").objects.update(farmer_code="")


class Migration(migrations.Migration):

    dependencies = [("broiler", "0075_gcsettlementrecalculation")]

    operations = [
        migrations.AddField(
            model_name="farmer",
            name="farmer_code",
            field=models.CharField(
                blank=True, default="", editable=False, max_length=20,
                help_text="Auto-generated code for this farmer, e.g. FRM-0001"),
            preserve_default=False,
        ),
        migrations.RunPython(issue_codes, drop_codes),
        migrations.AlterField(
            model_name="farmer",
            name="farmer_code",
            field=models.CharField(
                blank=True, editable=False, max_length=20, unique=True,
                help_text="Auto-generated code for this farmer, e.g. FRM-0001"),
        ),
    ]
