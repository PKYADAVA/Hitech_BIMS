from django.db import models


class Category(models.Model):
    name = models.CharField(max_length=255, unique=True)

    def __str__(self):
        return self.name
    

class Warehouse(models.Model):
    name = models.CharField(max_length=255, unique=True)

    def __str__(self):
        return self.name 
    

class Item(models.Model):
    VALUATION_METHODS = [
        ('Weighted Average', 'Weighted Average'),
        ('Standard Costing', 'Standard Costing')
    ]

    USAGE_CHOICES = [
        ('Produced', 'Produced'),
        ('Sales', 'Sales'),
    ]

    SOURCE_CHOICES = [
        ('Produced', 'Produced'),
        ('Purchased', 'Purchased'),
    ]

    TYPE_CHOICES = [
        ('Raw Material', 'Raw Material'),
        ('Finished Goods', 'Finished Goods'),
        ('Semi-finished Goods', 'Semi-finished Goods'),
    ]

    ITEM_AC_CHOICES = [
        ('Asset', 'Asset'),
        ('Expense', 'Expense'),
    ]

    LOT_SERIAL_CONTROL_CHOICES = [
        ('None', 'None'),
        ('Lot', 'Lot'),
        ('Serial', 'Serial'),
    ]

    item_code = models.CharField(max_length=100, unique=True)
    description = models.TextField()
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='items')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='items')
    valuation_method = models.CharField(max_length=50, choices=VALUATION_METHODS)
    standard_cost_per_unit = models.DecimalField(max_digits=10, decimal_places=2)
    storage_uom = models.CharField(max_length=100)
    consumption_uom = models.CharField(max_length=100)
    usage = models.CharField(max_length=50, choices=USAGE_CHOICES)
    source = models.CharField(max_length=50, choices=SOURCE_CHOICES)
    type = models.CharField(max_length=50, choices=TYPE_CHOICES)
    item_account = models.CharField(max_length=50, choices=ITEM_AC_CHOICES)
    lot_serial_control = models.CharField(max_length=50, choices=LOT_SERIAL_CONTROL_CHOICES, default='None')
    kg_per_bag = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    hsn_code = models.CharField(max_length=100, null=True, blank=True)

    def __str__(self):
        return f"{self.item_code} - {self.description}"
