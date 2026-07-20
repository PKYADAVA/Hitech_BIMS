from django.db import migrations, models


def backfill_codes(apps, schema_editor):
    Designation = apps.get_model("hr", "Designation")
    for designation in Designation.objects.filter(code=""):
        designation.code = f"DSG-{designation.pk:04d}"
        designation.save(update_fields=["code"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("hr", "0025_delete_sector"),
    ]

    operations = [
        migrations.AddField(
            model_name="designation",
            name="code",
            field=models.CharField(
                blank=True,
                default="",
                editable=False,
                help_text="Auto-generated code for this designation",
                max_length=20,
            ),
            preserve_default=False,
        ),
        migrations.RunPython(backfill_codes, noop),
        migrations.AlterField(
            model_name="designation",
            name="code",
            field=models.CharField(
                blank=True,
                editable=False,
                help_text="Auto-generated code for this designation",
                max_length=20,
                unique=True,
            ),
        ),
    ]
