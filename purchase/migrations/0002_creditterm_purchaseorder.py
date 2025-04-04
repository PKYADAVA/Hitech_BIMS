# Generated by Django 4.2.6 on 2025-01-20 19:19

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('purchase', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='CreditTerm',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('term', models.CharField(max_length=50, unique=True, verbose_name='Credit Term')),
            ],
        ),
        migrations.CreateModel(
            name='PurchaseOrder',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(default=django.utils.timezone.now, verbose_name='Date')),
                ('invoice', models.CharField(max_length=100, verbose_name='Invoice')),
                ('book_invoice', models.CharField(blank=True, max_length=255, null=True, verbose_name='Book Invoice')),
                ('dc_no', models.CharField(blank=True, max_length=100, null=True, verbose_name='Dc No')),
                ('item_tax', models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='Item Tax')),
                ('calculation_based_on', models.CharField(choices=[('Sent Quantity', 'Sent Quantity'), ('Received Quantity', 'Received Quantity')], default='Sent Quantity', max_length=255, verbose_name='Calculation Based On')),
                ('basic_amount', models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='Basic Amount')),
                ('broker_name', models.CharField(blank=True, max_length=255, null=True, verbose_name='Broker Name')),
                ('vehicle_no', models.CharField(blank=True, max_length=50, null=True, verbose_name='Vehicle No.')),
                ('total_amount', models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='Total Amount')),
                ('driver_name', models.CharField(blank=True, max_length=255, null=True, verbose_name='Driver Name')),
                ('freight', models.BooleanField(default=False, verbose_name='Freight Include')),
                ('freight_amount', models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='Freight Amount')),
                ('pay_later_via', models.CharField(max_length=255, verbose_name='Pay Later Via')),
                ('tcs', models.CharField(max_length=255, verbose_name='TCS')),
                ('tcs_percent', models.DecimalField(decimal_places=2, default=0, max_digits=5, verbose_name='TCS %')),
                ('tcs_amount', models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='TCS Amount')),
                ('grand_total', models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='Grand Total')),
                ('round_off', models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='Round Off')),
                ('round_off_type', models.CharField(choices=[('Add', 'Add'), ('Deduct', 'Deduct')], default='Add', max_length=10, verbose_name='Round Off Type')),
                ('net_total', models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='Net Total')),
                ('narration', models.TextField(blank=True, max_length=225, null=True, verbose_name='Narration')),
                ('credit_term', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='purchase_orders', to='purchase.creditterm', verbose_name='Credit Term')),
                ('vendor', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='purchase_orders', to='purchase.vendorgroup', verbose_name='Vendor Name')),
            ],
        ),
    ]
