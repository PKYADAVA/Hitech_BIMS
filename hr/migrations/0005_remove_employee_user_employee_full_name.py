# Generated by Django 4.2.6 on 2025-01-03 23:17

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("hr", "0004_employee_relieve"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="employee",
            name="user",
        ),
        migrations.AddField(
            model_name="employee",
            name="full_name",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]
