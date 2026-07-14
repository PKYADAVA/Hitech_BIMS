# Generated manually because the local Python launcher is unavailable.

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("hatchery", "0007_hatchsalesline_discount_percent_and_more"),
        ("inventory", "0002_rename_category_itemcategory"),
        ("sales", "0003_rename_contact_customer"),
    ]

    operations = [
        migrations.CreateModel(
            name="DeliveryChallan",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("challan_no", models.CharField(blank=True, editable=False, max_length=30, unique=True)),
                ("date", models.DateField()),
                ("shipping_address", models.TextField(blank=True)),
                ("transport_mode", models.CharField(default="Road", max_length=20)),
                ("vehicle_no", models.CharField(blank=True, max_length=50)),
                ("driver_name", models.CharField(blank=True, max_length=100)),
                ("driver_mobile", models.CharField(blank=True, max_length=20)),
                ("transporter_name", models.CharField(blank=True, max_length=150)),
                ("transport_document_no", models.CharField(blank=True, max_length=50)),
                ("transport_document_date", models.DateField(blank=True, null=True)),
                ("eway_bill_no", models.CharField(blank=True, max_length=50)),
                ("eway_bill_date", models.DateField(blank=True, null=True)),
                ("print_price_details", models.BooleanField(default=True)),
                ("terms", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="hatchery_challans", to="sales.customer")),
            ],
            options={"ordering": ["-date", "-id"]},
        ),
        migrations.CreateModel(
            name="DeliveryChallanItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("packing_size", models.DecimalField(decimal_places=2, default=1, max_digits=10)),
                ("units", models.DecimalField(decimal_places=2, default=1, max_digits=10)),
                ("quantity", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("unit", models.CharField(blank=True, max_length=30)),
                ("price", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("discount_percent", models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ("tax_percent", models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ("amount", models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ("challan", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="items", to="hatchery.deliverychallan")),
                ("item", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="delivery_challan_items", to="inventory.item")),
            ],
            options={"ordering": ["id"]},
        ),
    ]
