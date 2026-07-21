from django.db import migrations

# Old tab_code -> new tab_code, following the Cost Center -> Organization
# Centre rename in user.access.MODULE_REGISTRY.
RENAMES = {
    "cost_center": "organization_centre",
    "cost_center_mapping": "organization_centre_mapping",
}


def rename_forward(apps, schema_editor):
    GroupTabPermission = apps.get_model("user", "GroupTabPermission")
    for old_code, new_code in RENAMES.items():
        GroupTabPermission.objects.filter(tab_code=old_code).update(tab_code=new_code)


def rename_backward(apps, schema_editor):
    GroupTabPermission = apps.get_model("user", "GroupTabPermission")
    for old_code, new_code in RENAMES.items():
        GroupTabPermission.objects.filter(tab_code=new_code).update(tab_code=old_code)


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0004_groupaccessprofile_is_superuser'),
    ]

    operations = [
        migrations.RunPython(rename_forward, rename_backward),
    ]
