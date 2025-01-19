# Generated by Django 4.2.6 on 2025-01-18 22:22

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("hr", "0014_delete_attendance"),
    ]

    operations = [
        migrations.CreateModel(
            name="Attendance",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("date", models.DateField(blank=True, null=True)),
                ("check_in_time", models.TimeField(blank=True, null=True)),
                ("check_out_time", models.TimeField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("Present", "Present"),
                            ("Absent", "Absent"),
                            ("On Leave", "On Leave"),
                            ("First Half", "First Half"),
                            ("Second Half", "Second Half"),
                        ],
                        default="Present",
                        max_length=20,
                        null=True,
                    ),
                ),
                (
                    "employee",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="attendance_records",
                        to="hr.employee",
                    ),
                ),
            ],
        ),
    ]
