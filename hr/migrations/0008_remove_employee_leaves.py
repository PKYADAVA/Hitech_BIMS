# Generated by Django 4.2.6 on 2025-01-11 14:25

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("hr", "0007_rename_emergency_contact_1_employee_emergency_contact_and_more"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="employee",
            name="leaves",
        ),
    ]
