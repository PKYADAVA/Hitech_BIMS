# Renames account.CostCenter -> account.OrganizationCentre in place
# (preserves all existing rows and the VoucherLine.cost_center FK data),
# renames the ``kind`` field to ``centre_type``, and adds the new
# ``category`` field (Cost Centre / Profit Centre / Both) — unifying what
# would otherwise be separate Cost Centre and Profit Centre masters.

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


# Sector.code -> default category for existing rows, mirroring the user's
# own Cost/Profit/Both example mapping (Branch/Head Office -> Both,
# Farm/Sales/Hatchery/Processing Plant -> Profit, everything else -> Cost).
CENTRE_TYPE_CATEGORY_DEFAULTS = {
    'BRANCH_OFFICE': 'BOTH', 'HEAD_OFFICE': 'BOTH',
    'FARM': 'PROFIT', 'SALES': 'PROFIT', 'HATCHERY': 'PROFIT', 'PROCESSING_PLANT': 'PROFIT',
}


def backfill_category(apps, schema_editor):
    OrganizationCentre = apps.get_model("account", "OrganizationCentre")
    for cc in OrganizationCentre.objects.select_related("centre_type"):
        cc.category = CENTRE_TYPE_CATEGORY_DEFAULTS.get(cc.centre_type.code, 'COST')
        cc.save(update_fields=["category"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('inventory', '0032_flip_hatchery_office_mapping'),
        ('account', '0021_costcenter_allow_children_only_and_more'),
    ]

    operations = [
        migrations.RenameModel(old_name='CostCenter', new_name='OrganizationCentre'),
        migrations.AlterModelOptions(
            name='organizationcentre',
            options={'ordering': ['code'], 'verbose_name': 'Organization Centre', 'verbose_name_plural': 'Organization Centres'},
        ),
        migrations.RemoveConstraint(
            model_name='organizationcentre',
            name='uniq_costcenter_company_code',
        ),
        migrations.RenameField(
            model_name='organizationcentre',
            old_name='kind',
            new_name='centre_type',
        ),
        migrations.AlterField(
            model_name='organizationcentre',
            name='centre_type',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name='organization_centres',
                to='inventory.sector', help_text='What this centre represents — shared with Inventory > Sector',
            ),
        ),
        migrations.AlterField(
            model_name='organizationcentre',
            name='company',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                related_name='organization_centres', to='account.companyprofile',
            ),
        ),
        migrations.AlterField(
            model_name='organizationcentre',
            name='branch',
            field=models.OneToOneField(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name='organization_centre', to='broiler.branch',
                help_text="Broiler Branch this centre represents — auto-created the first time the "
                          "branch is saved; see account.signals.branch_cost_center",
            ),
        ),
        migrations.AlterField(
            model_name='organizationcentre',
            name='created_by',
            field=models.ForeignKey(
                blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name='organization_centres_created', to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name='organizationcentre',
            name='updated_by',
            field=models.ForeignKey(
                blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name='organization_centres_updated', to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddConstraint(
            model_name='organizationcentre',
            constraint=models.UniqueConstraint(fields=('company', 'code'), name='uniq_orgcentre_company_code'),
        ),
        migrations.AddField(
            model_name='organizationcentre',
            name='category',
            field=models.CharField(
                choices=[('COST', 'Cost Centre'), ('PROFIT', 'Profit Centre'), ('BOTH', 'Both')],
                default='BOTH', max_length=10,
                help_text='Whether this centre is used for expense tracking (Cost Centre), '
                          'revenue/profitability (Profit Centre), or both',
            ),
        ),
        migrations.RunPython(backfill_category, noop),
        migrations.AlterField(
            model_name='accountingcontrolsettings',
            name='require_cost_center',
            field=models.BooleanField(
                default=False,
                help_text="Every voucher line must carry a cost center — falls back to the Default "
                          "Organization Centre (see OrganizationCentre.is_default) if a line doesn't specify "
                          "one, and is rejected at posting if neither is present",
            ),
        ),
    ]
