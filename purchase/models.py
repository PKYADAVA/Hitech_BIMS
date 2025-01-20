from django.db import models
from django.db import models
from django.utils.timezone import now


class Supplier(models.Model):
    name = models.CharField(max_length=255, null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    place = models.CharField(max_length=100, null=True, blank=True)
    mobile = models.CharField(max_length=15, null=True, blank=True)
    contact_type = models.CharField(max_length=50, null=True, blank=True)
    pan = models.CharField(max_length=20, null=True, blank=True)
    supplier_group = models.CharField(max_length=100, null=True, blank=True)
    gstin = models.CharField(max_length=15, null=True, blank=True)
    state = models.CharField(max_length=50, null=True, blank=True)
    credit_term = models.IntegerField(null=True, blank=True)
    note = models.TextField(null=True, blank=True)

    def __str__(self):
        return self.name or "Unnamed Supplier"

class TaxMaster(models.Model):
    tax_code = models.CharField(max_length=50, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    tax_percentage = models.FloatField(null=True, blank=True)
    rule = models.CharField(max_length=50, null=True, blank=True)
    coa = models.CharField(max_length=100, null=True, blank=True)

    def __str__(self):
        return self.tax_code or "Unnamed Tax Code"

class VendorGroup(models.Model):
    code = models.CharField(max_length=50, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    currency = models.CharField(max_length=50, null=True, blank=True)
    control_account = models.CharField(max_length=100, null=True, blank=True)
    prepayment_account = models.CharField(max_length=100, null=True, blank=True)

    def __str__(self):
        return self.code or "Unnamed Vendor Group"

class TermsConditions(models.Model):
    type = models.CharField(max_length=100, null=True, blank=True)
    condition = models.TextField(null=True, blank=True)

    def __str__(self):
        return self.type or "Unnamed Terms and Condition"

class CreditTerm(models.Model):
    term = models.CharField(verbose_name="Credit Term", max_length=50, unique=True)

    def __str__(self):
        return self.term

class PurchaseOrder(models.Model):
        date = models.DateField(verbose_name="Date", default=now)
        vendor = models.ForeignKey(
            VendorGroup,
            verbose_name="Vendor Name",
            on_delete=models.CASCADE,
            related_name="purchase_orders"
        )
        invoice = models.CharField(verbose_name="Invoice", max_length=100)
        book_invoice = models.CharField(verbose_name="Book Invoice", max_length=255, blank=True, null=True)
        dc_no = models.CharField(verbose_name="Dc No", max_length=100, blank=True, null=True)
        credit_term = models.ForeignKey(
            CreditTerm,
            verbose_name="Credit Term",
            on_delete=models.SET_NULL,
            null=True,
            blank=True,
            related_name="purchase_orders"
        )
        item_tax = models.DecimalField(verbose_name="Item Tax", max_digits=10, decimal_places=2, default=0)

        calculation_based_on = models.CharField(
            verbose_name="Calculation Based On",
            max_length=255,
            choices=[("Sent Quantity", "Sent Quantity"), ("Received Quantity", "Received Quantity")],
            default="Sent Quantity"
        )
        basic_amount = models.DecimalField(verbose_name="Basic Amount", max_digits=10, decimal_places=2, default=0)
        broker_name = models.CharField(verbose_name="Broker Name", max_length=255, blank=True,
                                       null=True)
        vehicle_no = models.CharField(verbose_name="Vehicle No.", max_length=50, blank=True, null=True)
        total_amount = models.DecimalField(verbose_name="Total Amount", max_digits=10, decimal_places=2, default=0)
        driver_name = models.CharField(verbose_name="Driver Name", max_length=255, blank=True, null=True)
        freight = models.BooleanField(verbose_name="Freight Include", default=False)
        freight_amount = models.DecimalField(verbose_name="Freight Amount", max_digits=10, decimal_places=2, default=0)
        pay_later_via = models.CharField(verbose_name="Pay Later Via", max_length=255)  # Dropdown list
        tcs = models.CharField(verbose_name="TCS", max_length=255)
        tcs_percent = models.DecimalField(verbose_name="TCS %", max_digits=5, decimal_places=2, default=0)
        tcs_amount = models.DecimalField(verbose_name="TCS Amount", max_digits=10, decimal_places=2, default=0)
        grand_total = models.DecimalField(verbose_name="Grand Total", max_digits=10, decimal_places=2, default=0)
        round_off = models.DecimalField(verbose_name="Round Off", max_digits=10, decimal_places=2, default=0)
        round_off_type = models.CharField(
            verbose_name="Round Off Type",
            max_length=10,
            choices=[("Add", "Add"), ("Deduct", "Deduct")],
            default="Add"
        )
        net_total = models.DecimalField(verbose_name="Net Total", max_digits=10, decimal_places=2, default=0)
        narration = models.TextField(verbose_name="Narration", max_length=225, blank=True, null=True)

        def __str__(self):
            return f"Purchase Order - {self.invoice}"

class PurchaseOrderLineItem(models.Model):
    purchase_order = models.ForeignKey(PurchaseOrder, verbose_name="Purchase Order", on_delete=models.CASCADE, related_name="line_items")
    category = models.CharField(verbose_name=" Item Category", max_length=100)
    code = models.CharField(verbose_name="Item Code", max_length=100)
    description = models.TextField(verbose_name="Item Description")
    units = models.CharField(verbose_name="Units", max_length=100, blank=True, null=True)
    price_per_unit = models.DecimalField(verbose_name="Price / Unit", max_digits=10, decimal_places=2, default=0)
    qty_sent = models.DecimalField(verbose_name="Qty Sent", max_digits=10, decimal_places=2, default=0)
    qty_received = models.DecimalField(verbose_name="Qty Received", max_digits=10, decimal_places=2, default=0)
    qty_free = models.DecimalField(verbose_name="Qty Free", max_digits=10, decimal_places=2, default=0)
    type = models.CharField(verbose_name="Type", max_length=100, blank=True, null=True)
    bags_or_boxes = models.CharField(verbose_name="Bags / Boxes", max_length=100, blank=True, null=True)
    weight = models.DecimalField(verbose_name="Weight", max_digits=10, decimal_places=2, default=0)
    discount_type = [
        ('percentage', 'Percentage'),
        ('amount', 'Amount'),
    ]
    vat = models.DecimalField(verbose_name="VAT (%)", max_digits=5, decimal_places=2, default=0)
    warehouse = models.CharField(verbose_name="Warehouse", max_length=100)
    flock = models.CharField(verbose_name="Flock", max_length=100, blank=True, null=True)
    sqft = models.DecimalField(verbose_name="Sqft", max_digits=10, decimal_places=2, default=0)
    sqft_per_chick = models.DecimalField(verbose_name="Sqft / Chicks", max_digits=10, decimal_places=2, default=0)

    def __str__(self):
        return f"Line Item {self.code} for {self.purchase_order.invoice}"

