from django.db import migrations, models
import django.db.models.deletion


def backfill_region_and_branch(apps, schema_editor):
    BroilerLine = apps.get_model('broiler', 'BroilerLine')

    for line in BroilerLine.objects.all():
        supervisor = line.supervisor
        line.branch_id = supervisor.branch_id
        line.region_id = supervisor.branch.region_id
        if not line.code:
            line.code = f"LNS-{line.pk:04d}"
        line.save()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('broiler', '0006_branch_restructure'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='broilerplace',
            unique_together=set(),
        ),
        migrations.RenameModel(
            old_name='BroilerPlace',
            new_name='BroilerLine',
        ),
        migrations.RenameField(
            model_name='broilerline',
            old_name='place_name',
            new_name='description',
        ),
        migrations.AlterField(
            model_name='broilerline',
            name='description',
            field=models.CharField(max_length=100, help_text='Name of the line'),
        ),
        migrations.AlterModelOptions(
            name='broilerline',
            options={'ordering': ['description'], 'verbose_name': 'Broiler Line', 'verbose_name_plural': 'Broiler Lines'},
        ),
        migrations.AddField(
            model_name='broilerline',
            name='region',
            field=models.ForeignKey(
                null=True, blank=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='broiler_lines', to='broiler.region',
                help_text='Region this line belongs to',
            ),
        ),
        migrations.AddField(
            model_name='broilerline',
            name='branch',
            field=models.ForeignKey(
                null=True, blank=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='broiler_lines', to='broiler.branch',
                help_text='Branch this line belongs to',
            ),
        ),
        migrations.AddField(
            model_name='broilerline',
            name='code',
            field=models.CharField(max_length=20, unique=True, editable=False, blank=True, null=True, help_text='Auto-generated code for this line'),
        ),
        migrations.AddField(
            model_name='broilerline',
            name='is_active',
            field=models.BooleanField(default=True, help_text='Inactive lines are hidden from selection elsewhere'),
        ),
        migrations.AddField(
            model_name='broilerline',
            name='is_locked',
            field=models.BooleanField(default=False, help_text="Locked records can't be edited or deleted"),
        ),

        migrations.RunPython(backfill_region_and_branch, noop),

        migrations.RemoveField(
            model_name='broilerline',
            name='supervisor',
        ),
        migrations.AlterField(
            model_name='broilerline',
            name='region',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='broiler_lines', to='broiler.region',
                help_text='Region this line belongs to',
            ),
        ),
        migrations.AlterField(
            model_name='broilerline',
            name='branch',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='broiler_lines', to='broiler.branch',
                help_text='Branch this line belongs to',
            ),
        ),
        migrations.AlterField(
            model_name='broilerline',
            name='code',
            field=models.CharField(max_length=20, unique=True, editable=False, blank=True, help_text='Auto-generated code for this line'),
        ),
        migrations.AlterModelOptions(
            name='broilerline',
            options={'ordering': ['code'], 'verbose_name': 'Broiler Line', 'verbose_name_plural': 'Broiler Lines'},
        ),
    ]

