# Generated manually.

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0003_rename_contact_customer"),
    ]

    operations = [
        migrations.CreateModel(
            name="CustomerShippingAddress",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("label", models.CharField(max_length=100)),
                ("address", models.TextField()),
                ("contact_person", models.CharField(blank=True, max_length=100)),
                ("mobile", models.CharField(blank=True, max_length=15)),
                ("is_default", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("customer", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="shipping_addresses", to="sales.customer")),
            ],
            options={"ordering": ["-is_default", "label", "id"]},
        ),
        migrations.AddConstraint(
            model_name="customershippingaddress",
            constraint=models.UniqueConstraint(fields=("customer", "label"), name="unique_customer_shipping_address_label"),
        ),
    ]
