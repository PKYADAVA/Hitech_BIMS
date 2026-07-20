from django.db import migrations, models
import django.db.models.deletion

# Old CostCenter.kind string value -> new Sector.code it now points to.
OLD_KIND_TO_SECTOR_CODE = {
    "Department": "DEPARTMENT",
    "Warehouse": "WAREHOUSE",
    "Farm": "FARM",
    "Project": "PROJECT",
    "Branch": "BRANCH_OFFICE",
    "Vehicle": "VEHICLE",
    "ProductionUnit": "PRODUCTION_UNIT",
}


def backfill_kind_fk(apps, schema_editor):
    CostCenter = apps.get_model("account", "CostCenter")
    Sector = apps.get_model("inventory", "Sector")

    sector_by_code = {s.code: s.id for s in Sector.objects.all()}
    for cc in CostCenter.objects.all():
        sector_id = sector_by_code.get(OLD_KIND_TO_SECTOR_CODE.get(cc.kind_old))
        if sector_id is None:
            # Unrecognized legacy value - fall back to Department rather than
            # leaving the row without a kind.
            sector_id = sector_by_code.get("DEPARTMENT")
        cc.kind_id = sector_id
        cc.save(update_fields=["kind"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0030_sector_code'),
        ('account', '0018_costcenter_branch'),
    ]

    operations = [
        migrations.RenameField(
            model_name='costcenter',
            old_name='kind',
            new_name='kind_old',
        ),
        migrations.AddField(
            model_name='costcenter',
            name='kind',
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='cost_centers', to='inventory.sector',
                help_text='What this cost center represents — shared with Inventory > Sector',
            ),
        ),
        migrations.RunPython(backfill_kind_fk, noop),
        migrations.AlterField(
            model_name='costcenter',
            name='kind',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='cost_centers', to='inventory.sector',
                help_text='What this cost center represents — shared with Inventory > Sector',
            ),
        ),
        migrations.RemoveField(
            model_name='costcenter',
            name='kind_old',
        ),
    ]
