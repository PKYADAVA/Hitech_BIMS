# Generated by Django 4.2.6 on 2024-12-01 13:18

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("hr", "0002_employee_personal_contact"),
    ]

    operations = [
        migrations.AlterField(
            model_name="employee",
            name="employee_id",
            field=models.IntegerField(blank=True, editable=False, unique=True),
        ),
    ]
