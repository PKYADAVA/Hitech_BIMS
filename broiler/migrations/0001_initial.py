# Generated by Django 4.2.6 on 2025-01-09 15:44

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Branch',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('state', models.CharField(max_length=100)),
                ('branch_name', models.CharField(max_length=100)),
            ],
        ),
        migrations.CreateModel(
            name='BroilerDisease',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('disease_code', models.CharField(max_length=50)),
                ('disease_name', models.CharField(max_length=100)),
                ('symptoms', models.TextField()),
                ('diagnosis', models.TextField()),
                ('image', models.ImageField(blank=True, null=True, upload_to='disease_images/')),
            ],
        ),
        migrations.CreateModel(
            name='Supervisor',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('phone_no', models.CharField(max_length=15)),
                ('address', models.TextField()),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='broiler.branch')),
            ],
        ),
        migrations.CreateModel(
            name='BroilerPlace',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('place_name', models.CharField(max_length=100)),
                ('supervisor', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='broiler.supervisor')),
            ],
        ),
        migrations.CreateModel(
            name='BroilerFarm',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('farm_code', models.CharField(max_length=50)),
                ('farm_name', models.CharField(max_length=100)),
                ('mobile_no', models.CharField(max_length=15)),
                ('block_name', models.CharField(max_length=100)),
                ('address', models.TextField()),
                ('farm_latitude', models.FloatField()),
                ('farm_longitude', models.FloatField()),
                ('farm_type', models.CharField(max_length=50)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='broiler.branch')),
                ('broiler_place', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='broiler.broilerplace')),
                ('supervisor', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='broiler.supervisor')),
            ],
        ),
        migrations.CreateModel(
            name='BroilerBatch',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('batch_name', models.CharField(max_length=50)),
                ('broiler_farm', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='broiler.broilerfarm')),
            ],
        ),
    ]
