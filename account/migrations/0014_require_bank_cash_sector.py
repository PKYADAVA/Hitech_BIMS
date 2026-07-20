import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0028_mapping_remove_warehouse_branch_and_more'),
        ('account', '0013_cashcode'),
    ]

    operations = [
        migrations.AlterField(
            model_name='bankcode',
            name='sector',
            field=models.ForeignKey(
                help_text='Office this bank account is mapped to',
                on_delete=django.db.models.deletion.PROTECT,
                related_name='banks',
                to='inventory.warehouse',
            ),
        ),
        migrations.AlterField(
            model_name='cashcode',
            name='sector',
            field=models.ForeignKey(
                help_text='Office this cash location is mapped to',
                on_delete=django.db.models.deletion.PROTECT,
                related_name='cash_locations',
                to='inventory.warehouse',
            ),
        ),
    ]
