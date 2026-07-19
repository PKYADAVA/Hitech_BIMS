# Adds an auto-generated code to ItemCategory. Existing categories get one
# backfilled before the unique constraint is enforced — adding it with
# unique=True in a single AddField would collide on the shared '' default
# for any table that already has rows (see inventory.0010's original bug).

import re

from django.db import migrations, models


def backfill_category_codes(apps, schema_editor):
    ItemCategory = apps.get_model('inventory', 'ItemCategory')
    prefix = "CAT-"
    serials = []
    for code in ItemCategory.objects.exclude(code='').values_list('code', flat=True):
        match = re.match(r"^CAT-(\d+)$", code or "")
        if match:
            serials.append(int(match.group(1)))
    next_serial = max(serials, default=0) + 1
    for category in ItemCategory.objects.filter(code='').order_by('pk'):
        category.code = f"{prefix}{next_serial:04d}"
        category.save(update_fields=['code'])
        next_serial += 1


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0023_itempricelist'),
    ]

    operations = [
        migrations.AddField(
            model_name='itemcategory',
            name='code',
            field=models.CharField(blank=True, editable=False, help_text='Auto-generated code for this category, e.g. CAT-0001', max_length=20, default=''),
            preserve_default=False,
        ),
        migrations.RunPython(backfill_category_codes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='itemcategory',
            name='code',
            field=models.CharField(blank=True, editable=False, help_text='Auto-generated code for this category, e.g. CAT-0001', max_length=20, unique=True),
        ),
    ]
