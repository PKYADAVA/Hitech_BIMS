# Converts Item.storage_uom / Item.consumption_uom from free-text CharField
# to a ForeignKey against the new UnitOfMeasurement master.
#
# Existing text values aren't dropped: a UnitOfMeasurement row is created for
# every distinct non-blank value in use (matching the mechanism that already
# broke inventory.0010 on Warehouse.code — add nullable, backfill, then swap).

from django.db import migrations, models
import django.db.models.deletion


def backfill_uom_fk(apps, schema_editor):
    Item = apps.get_model('inventory', 'Item')
    UnitOfMeasurement = apps.get_model('inventory', 'UnitOfMeasurement')
    uom_cache = {}

    def uom_for(name):
        name = (name or '').strip()
        if not name:
            return None
        if name not in uom_cache:
            uom, _ = UnitOfMeasurement.objects.get_or_create(name=name)
            uom_cache[name] = uom
        return uom_cache[name]

    for item in Item.objects.all():
        storage = uom_for(item.storage_uom_text)
        consumption = uom_for(item.consumption_uom_text)
        Item.objects.filter(pk=item.pk).update(
            storage_uom_fk=storage, consumption_uom_fk=consumption,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0020_unitofmeasurement'),
    ]

    operations = [
        migrations.RenameField(
            model_name='item',
            old_name='storage_uom',
            new_name='storage_uom_text',
        ),
        migrations.RenameField(
            model_name='item',
            old_name='consumption_uom',
            new_name='consumption_uom_text',
        ),
        migrations.AddField(
            model_name='item',
            name='storage_uom_fk',
            field=models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='items_storage_uom', to='inventory.unitofmeasurement'),
        ),
        migrations.AddField(
            model_name='item',
            name='consumption_uom_fk',
            field=models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='items_consumption_uom', to='inventory.unitofmeasurement'),
        ),
        migrations.RunPython(backfill_uom_fk, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='item',
            name='storage_uom_text',
        ),
        migrations.RemoveField(
            model_name='item',
            name='consumption_uom_text',
        ),
        migrations.RenameField(
            model_name='item',
            old_name='storage_uom_fk',
            new_name='storage_uom',
        ),
        migrations.RenameField(
            model_name='item',
            old_name='consumption_uom_fk',
            new_name='consumption_uom',
        ),
    ]
