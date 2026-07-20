from django.db import migrations, models


def backfill_sectors(apps, schema_editor):
    """Carry each row's existing single Office forward as a one-office
    'Limited' mapping (rather than resetting everyone to 'All Offices')."""
    BankCashMaster = apps.get_model("account", "BankCashMaster")
    for row in BankCashMaster.objects.exclude(sector__isnull=True):
        row.sectors.add(row.sector_id)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0028_mapping_remove_warehouse_branch_and_more'),
        ('account', '0015_bankcashmaster'),
    ]

    operations = [
        migrations.AddField(
            model_name='bankcashmaster',
            name='sectors',
            field=models.ManyToManyField(
                blank=True,
                help_text='Offices this bank/cash record is mapped to — leave empty to map to All Offices',
                related_name='bank_cash_masters',
                to='inventory.warehouse',
            ),
        ),
        migrations.RunPython(backfill_sectors, noop),
        migrations.RemoveField(
            model_name='bankcashmaster',
            name='sector',
        ),
    ]
