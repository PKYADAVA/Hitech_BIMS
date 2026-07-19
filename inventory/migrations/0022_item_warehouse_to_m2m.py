# Converts Item.warehouse from a required single ForeignKey to a
# ManyToManyField, so an item can be stocked at multiple warehouses (or all
# of them) instead of exactly one. Each existing Item's single warehouse is
# preserved as the sole member of its new warehouse set.

from django.db import migrations, models


def backfill_warehouse_m2m(apps, schema_editor):
    Item = apps.get_model('inventory', 'Item')
    for item in Item.objects.all():
        if item.warehouse_fk_id:
            item.warehouse_m2m.add(item.warehouse_fk_id)


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0021_item_uom_to_fk'),
    ]

    operations = [
        migrations.RenameField(
            model_name='item',
            old_name='warehouse',
            new_name='warehouse_fk',
        ),
        migrations.AddField(
            model_name='item',
            name='warehouse_m2m',
            field=models.ManyToManyField(blank=True, related_name='items_m2m', to='inventory.warehouse'),
        ),
        migrations.RunPython(backfill_warehouse_m2m, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='item',
            name='warehouse_fk',
        ),
        migrations.RenameField(
            model_name='item',
            old_name='warehouse_m2m',
            new_name='warehouse',
        ),
        migrations.AlterField(
            model_name='item',
            name='warehouse',
            field=models.ManyToManyField(blank=True, related_name='items', to='inventory.warehouse',
                                         help_text='Warehouse(s) that stock/handle this item'),
        ),
    ]
