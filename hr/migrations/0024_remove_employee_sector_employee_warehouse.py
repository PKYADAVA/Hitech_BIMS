# Generated by Django 4.2.6 on 2025-01-28 21:13

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0002_rename_category_itemcategory"),
        ("hr", "0023_alter_employee_date_of_joining"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="employee",
            name="sector",
        ),
        migrations.AddField(
            model_name="employee",
            name="warehouse",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="employees",
                to="inventory.warehouse",
            ),
        ),
    ]
