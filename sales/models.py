import re

from django.db import models
from purchase.models import VendorGroup, CreditTerm
from inventory.models import Item, ItemCategory





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

    class ContactType(models.TextChoices):
        SUPPLIER = "Supplier", "Supplier"
        CUSTOMER = "Customer", "Customer"
        BOTH = "Supplier & Customer", "Supplier & Customer"

    class PartyCategory(models.TextChoices):
        RETAILER = "Retailer", "Retailer"
        WHOLESALER = "Wholesaler", "Wholesaler"
        DISTRIBUTOR = "Distributor", "Distributor"
        FARMER = "Farmer", "Farmer"
        OTHER = "Other", "Other"

    class ToPayToReceive(models.TextChoices):
        TO_PAY = "To Pay", "To Pay"
        TO_RECEIVE = "To Receive", "To Receive"

    code = models.CharField(max_length=50, blank=True, null=True, help_text="Short customer code")
    name = models.CharField(max_length=255, help_text="Full name of the contact")
    address = models.TextField(help_text="Billing address of the contact")
    place = models.CharField(max_length=255, blank=True, null=True, help_text="Place information")
    phone = models.CharField(max_length=15, unique=True, blank=True, null=True, help_text="Primary phone number")
    mobile = models.CharField(max_length=15, unique=True, help_text="SMS/WhatsApp number")
    mobile_2 = models.CharField(max_length=15, blank=True, null=True, help_text="Secondary mobile number")
    email = models.EmailField(blank=True, null=True, help_text="Email address")
    aadhar = models.CharField(max_length=20, blank=True, null=True, help_text="Aadhar number")
    contact_type = models.CharField(
        max_length=20, choices=ContactType.choices, default=ContactType.BOTH, help_text="Party type"
    )
    party_category = models.CharField(
        max_length=20, choices=PartyCategory.choices, blank=True, null=True, help_text="Party category"
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
    credit_period = models.PositiveIntegerField(blank=True, null=True, help_text="Credit period in days")
    gstin = models.CharField(max_length=15, blank=True, null=True, help_text="GSTIN number")
    state = models.CharField(
        max_length=50,  blank=True, null=True, help_text="State of supply"
    )
    note = models.TextField(blank=True, null=True, help_text="Remarks")
    supplier_address = models.TextField(blank=True, null=True, help_text="Supplier address")
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True, help_text="Opening balance")
    to_pay_to_receive = models.CharField(max_length=20, choices=ToPayToReceive.choices, blank=True, null=True)
    as_on_date = models.DateField(blank=True, null=True, help_text="Opening balance as-on date")
    country = models.CharField(max_length=100, blank=True, null=True)
    currency = models.CharField(max_length=10, blank=True, null=True)
    account_no = models.CharField(max_length=50, blank=True, null=True, help_text="Bank account number")
    ifsc_code = models.CharField(max_length=20, blank=True, null=True)
    bank_details = models.TextField(blank=True, null=True)
    terms = models.TextField(blank=True, null=True, help_text="Terms and conditions")
    agreement_start_date = models.DateField(blank=True, null=True)
    agreement_months = models.PositiveIntegerField(blank=True, null=True)
    agreement_copy = models.FileField(upload_to="customer_documents/agreements/", blank=True, null=True)
    other_documents = models.FileField(upload_to="customer_documents/other/", blank=True, null=True)

    @classmethod
    def next_code(cls):
        prefix = "CUST-"
        serials = []
        for code in cls.objects.filter(code__startswith=prefix).values_list("code", flat=True):
            match = re.match(r"^CUST-(\d+)$", code or "")
            if match:
                serials.append(int(match.group(1)))
        return f"{prefix}{max(serials, default=0) + 1:04d}"

    def save(self, *args, **kwargs):
        if self._state.adding and not self.code:
            self.code = self.next_code()
        if not self.phone:
            self.phone = self.mobile
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class CustomerShippingAddress(models.Model):
    """Reusable delivery address belonging to a customer."""
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="shipping_addresses")
    label = models.CharField(max_length=100)
    address = models.TextField()
    contact_person = models.CharField(max_length=100, blank=True)
    mobile = models.CharField(max_length=15, blank=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_default", "label", "id"]
        constraints = [
            models.UniqueConstraint(fields=["customer", "label"], name="unique_customer_shipping_address_label"),
        ]

    def __str__(self):
        return f"{self.customer} - {self.label}"
