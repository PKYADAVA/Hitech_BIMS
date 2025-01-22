from django.db import models
from purchase.models import VendorGroup, CreditTerm
from inventory.models import Item, ItemCategory



class ContactType(models.TextChoices):
    SUPPLIER = "Supplier", "Supplier"
    CUSTOMER = "Customer", "Customer"
    BOTH = "Supplier & Customer", "Supplier & Customer"


class CustomerGroup(models.Model):
    code = models.CharField(max_length=50, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    currency = models.CharField(max_length=50, null=True, blank=True)
    control_account = models.CharField(max_length=100, null=True, blank=True)
    advance_account = models.CharField(max_length=100, null=True, blank=True)


class SalesPriceMaster(models.Model):
    item_category = models.ForeignKey(
    'inventory.ItemCategory', on_delete=models.SET_NULL, blank=True, null=True, help_text="Item category"
)
    item = models.ForeignKey(
        'inventory.Item', on_delete=models.SET_NULL, blank=True, null=True, help_text="Item"
    )
    price = models.DecimalField(
        max_digits=10, decimal_places=2, help_text="Sales price of the item"
    )
    date = models.DateField(
        auto_now_add=True, help_text="Date of price entry"
    )

    def __str__(self):
        return f"{self.item} - {self.price}"



# Create your models here.
class Customer(models.Model):
    name = models.CharField(max_length=255, help_text="Full name of the contact")
    address = models.TextField(help_text="Address of the contact")
    place = models.CharField(max_length=255, blank=True, null=True, help_text="Place information")
    phone = models.CharField(max_length=15, unique=True, help_text="Primary phone number")
    mobile = models.CharField(max_length=15, unique=True, help_text="Mobile number")
    contact_type = models.CharField(
        max_length=20, choices=ContactType.choices, default=ContactType.BOTH, help_text="Type of contact"
    )
    pan_tin = models.CharField(max_length=50, blank=True, null=True, help_text="PAN/TIN number")
    customer_group = models.ForeignKey(
        CustomerGroup, on_delete=models.SET_NULL, blank=True, null=True, help_text="Customer group"
    )
    supplier_group = models.ForeignKey(
        VendorGroup, on_delete=models.SET_NULL, blank=True, null=True, help_text="Supplier group"
    )
    credit_limit = models.DecimalField(
        max_digits=10, decimal_places=2, default=0.00, help_text="Credit limit in currency"
    )
    credit_term = models.ForeignKey(
       CreditTerm, on_delete=models.SET_NULL, blank=True, null=True, help_text="Credit term"
    )
    gstin = models.CharField(max_length=15, blank=True, null=True, help_text="GSTIN number")
    state = models.CharField(
        max_length=50,  blank=True, null=True, help_text="State"
    )
    note = models.TextField(blank=True, null=True, help_text="Additional notes")
    supplier_address = models.TextField(blank=True, null=True, help_text="Supplier address")

    def __str__(self):
        return self.name