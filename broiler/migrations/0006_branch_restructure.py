from django.db import migrations, models
import django.db.models.deletion


def backfill_region_and_prefix(apps, schema_editor):
    Branch = apps.get_model('broiler', 'Branch')
    Region = apps.get_model('broiler', 'Region')

    for branch in Branch.objects.all():
        old_state = (branch.state or '').strip() or 'Unspecified'
        region = Region.objects.filter(description=old_state).first()
        if not region:
            region = Region.objects.create(description=old_state)
            region.code = f"RGN-{region.pk:04d}"
            region.save(update_fields=['code'])
        branch.region_id = region.id

        if not branch.prefix:
            candidate = ''.join(ch for ch in branch.branch_name if ch.isalnum())[:3].upper()
            branch.prefix = candidate or 'BRH'

        if not branch.code:
            branch.code = f"BRH-{branch.pk:04d}"

        branch.save()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('broiler', '0005_region'),
    ]

    operations = [
        migrations.AddField(
            model_name='branch',
            name='region',
            field=models.ForeignKey(
                null=True, blank=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='branches', to='broiler.region',
                help_text='Region this branch belongs to',
            ),
        ),
        migrations.AddField(
            model_name='branch',
            name='prefix',
            field=models.CharField(max_length=10, blank=True, default='', help_text='Short prefix code for this branch'),
        ),
        migrations.AddField(
            model_name='branch',
            name='code',
            field=models.CharField(max_length=20, unique=True, editable=False, blank=True, null=True, help_text='Auto-generated code for this branch'),
        ),
        migrations.AddField(
            model_name='branch',
            name='is_active',
            field=models.BooleanField(default=True, help_text='Inactive branches are hidden from selection elsewhere'),
        ),
        migrations.AddField(
            model_name='branch',
            name='is_locked',
            field=models.BooleanField(default=False, help_text="Locked records can't be edited or deleted"),
        ),

        migrations.RunPython(backfill_region_and_prefix, noop),

        migrations.RemoveField(
            model_name='branch',
            name='state',
        ),
        migrations.AlterField(
            model_name='branch',
            name='region',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='branches', to='broiler.region',
                help_text='Region this branch belongs to',
            ),
        ),
        migrations.AlterField(
            model_name='branch',
            name='prefix',
            field=models.CharField(max_length=10, help_text='Short prefix code for this branch'),
        ),
        migrations.AlterField(
            model_name='branch',
            name='code',
            field=models.CharField(max_length=20, unique=True, editable=False, blank=True, help_text='Auto-generated code for this branch'),
        ),
        migrations.AlterModelOptions(
            name='branch',
            options={'ordering': ['code'], 'verbose_name': 'Branch', 'verbose_name_plural': 'Branches'},
        ),
    ]
