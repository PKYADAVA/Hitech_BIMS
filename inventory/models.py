import re

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.timezone import now


class ItemCategory(models.Model):
    code = models.CharField(max_length=20, unique=True, editable=False, blank=True,
                            help_text="Auto-generated code for this category, e.g. CAT-0001")
    name = models.CharField(max_length=255, unique=True)

    def __str__(self):
        return self.name

    @classmethod
    def next_code(cls):
        prefix = "CAT-"
        serials = []
        for code in cls.objects.filter(code__startswith=prefix).values_list("code", flat=True):
            match = re.match(r"^CAT-(\d+)$", code or "")
            if match:
                serials.append(int(match.group(1)))
        return f"{prefix}{max(serials, default=0) + 1:04d}"

    def save(self, *args, **kwargs):
        if self._state.adding and not self.code:
            self.code = self.next_code()
        super().save(*args, **kwargs)
    

class Sector(models.Model):
    """Classifies what an Office is (Warehouse, Head Office, ...) and, since
    it's shared with account.OrganizationCentre.centre_type, what an
    Organization Centre represents (Department, Vehicle, Project, ...).
    ``code`` is a stable key set once at creation from the name — matching
    logic elsewhere (e.g. which Sector row means "this is a Branch") keys
    off ``code``, not the freely-renameable ``name``, so renaming a Sector
    never silently breaks that logic."""
    code = models.CharField(max_length=30, unique=True, editable=False, blank=True,
                            help_text="Auto-generated stable key, e.g. WAREHOUSE, BRANCH_OFFICE")
    name = models.CharField(max_length=255, unique=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self._state.adding and not self.code:
            base = re.sub(r"[^A-Za-z0-9]+", "_", self.name).strip("_").upper() or "SECTOR"
            code = base
            suffix = 1
            while Sector.objects.filter(code=code).exists():
                suffix += 1
                code = f"{base}_{suffix}"
            self.code = code
        super().save(*args, **kwargs)


class UnitOfMeasurement(models.Model):
    name = models.CharField(max_length=100, unique=True, help_text="e.g. Kilogram, Piece, Litre")
    symbol = models.CharField(max_length=20, blank=True, help_text="Short form, e.g. Kg, Pcs, Ltr")

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.symbol})" if self.symbol else self.name


class Warehouse(models.Model):
    """A physical location (branch office, feedmill, hatchery, warehouse,
    etc.) — labelled "Office" in the UI. ``name`` doubles as the "Sector
    Description" shown on the Office form."""
    code = models.CharField(max_length=20, unique=True, editable=False, blank=True,
                            help_text="Auto-generated code for this office, e.g. SEH-0001")
    name = models.CharField(max_length=255, unique=True)
    sector = models.ForeignKey(Sector, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name="offices")
    address = models.TextField(blank=True)
    location = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.name

    @classmethod
    def next_code(cls):
        prefix = "SEH-"
        serials = []
        for code in cls.objects.filter(code__startswith=prefix).values_list("code", flat=True):
            match = re.match(r"^SEH-(\d+)$", code or "")
            if match:
                serials.append(int(match.group(1)))
        return f"{prefix}{max(serials, default=0) + 1:04d}"

    def save(self, *args, **kwargs):
        if self._state.adding and not self.code:
            self.code = self.next_code()
        super().save(*args, **kwargs)


class Mapping(models.Model):
    """Generic association between two entities elsewhere in the system —
    e.g. a Sector/Office mapped to its Broiler Branch, or a Hatchery mapped
    to its Office. Replaces bespoke FK columns (the old Warehouse.branch,
    Hatchery.warehouse) with one shared table any "map A to B" relationship
    can be registered under, keyed by ``type``. ``to_id=None`` means the
    "from" side has been explicitly unmapped rather than never mapped.

    ``type`` is the only thing that decides which models "from"/"to" refer
    to — resolving those ids to real objects is the caller's job (see
    inventory.views.MAPPING_TYPES), not this model's, since the two related
    apps (broiler, hatchery_master) can't be imported here without risking
    a circular import.
    """

    TYPE_SECTOR_BRANCH = "sector_branch"
    TYPE_HATCHERY_OFFICE = "hatchery_office"
    TYPE_OFFICE_COST_CENTER = "office_cost_center"
    TYPE_CHOICES = [
        (TYPE_SECTOR_BRANCH, "Sector → Branch"),
        (TYPE_HATCHERY_OFFICE, "Hatchery → Office"),
        (TYPE_OFFICE_COST_CENTER, "Office → Cost Center"),
    ]

    type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    from_id = models.PositiveIntegerField()
    to_id = models.PositiveIntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["type", "from_id"], name="unique_mapping_per_type_from"),
        ]

    def __str__(self):
        return f"{self.get_type_display()}: {self.from_id} -> {self.to_id}"


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

    item_code = models.CharField(max_length=100, unique=True, editable=False, blank=True,
                                 help_text="Auto-generated code for this item, e.g. ITM-0001")
    description = models.TextField()
    category = models.ForeignKey(ItemCategory, on_delete=models.CASCADE, related_name='items')
    warehouse = models.ManyToManyField(Warehouse, related_name='items', blank=True,
                                       help_text="Warehouse(s) that stock/handle this item")
    valuation_method = models.CharField(max_length=50, choices=VALUATION_METHODS)
    standard_cost_per_unit = models.DecimalField(max_digits=10, decimal_places=2)
    storage_uom = models.ForeignKey(UnitOfMeasurement, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='items_storage_uom')
    consumption_uom = models.ForeignKey(UnitOfMeasurement, on_delete=models.SET_NULL, null=True, blank=True,
                                        related_name='items_consumption_uom')
    usage = models.CharField(max_length=50, choices=USAGE_CHOICES)
    source = models.CharField(max_length=50, choices=SOURCE_CHOICES)
    type = models.CharField(max_length=50, choices=TYPE_CHOICES)
    item_account = models.CharField(max_length=50, choices=ITEM_AC_CHOICES)
    lot_serial_control = models.CharField(max_length=50, choices=LOT_SERIAL_CONTROL_CHOICES, default='None')
    kg_per_bag = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    hsn_code = models.CharField(max_length=100, null=True, blank=True)

    def __str__(self):
        return f"{self.item_code} - {self.description}"

    @classmethod
    def next_code(cls):
        prefix = "ITM-"
        serials = []
        for code in cls.objects.filter(item_code__startswith=prefix).values_list("item_code", flat=True):
            match = re.match(r"^ITM-(\d+)$", code or "")
            if match:
                serials.append(int(match.group(1)))
        return f"{prefix}{max(serials, default=0) + 1:04d}"

    def save(self, *args, **kwargs):
        if self._state.adding and not self.item_code:
            self.item_code = self.next_code()
        super().save(*args, **kwargs)


class ItemPriceList(models.Model):
    """A dated price entry for an Item — Inventory > Master > Item Price
    List. Not tied to sales; a general price history the item can be
    referenced against elsewhere."""

    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='price_list_entries')
    price = models.DecimalField(max_digits=10, decimal_places=2)
    effective_date = models.DateField(default=now)

    class Meta:
        ordering = ['-effective_date', '-id']
        unique_together = [('item', 'effective_date')]

    def __str__(self):
        return f"{self.item} - {self.price} (from {self.effective_date})"


class StockTransfer(models.Model):
    """One item moved from one location to another — Office/Warehouse or
    Broiler Farm, in any combination (warehouse-to-farm, farm-to-farm,
    farm-to-warehouse) — via Inventory > Transactions > Stock Transfer, with
    a running closing-stock balance for that item at the source location."""

    LOCATION_TYPE_CHOICES = [
        ('warehouse', 'Warehouse'),
        ('farm', 'Farm'),
    ]

    trnum = models.CharField(max_length=30, unique=True, editable=False, blank=True,
                             help_text="Auto-generated transfer number, e.g. ST-2627-0001")
    date = models.DateField(default=now)
    dc_no = models.CharField(max_length=100, blank=True)

    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name='stock_transfers')
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # Reference-only breakdown for Broiler > Chicks Placement — none of
    # these feed into `quantity` or the running `stock` balance below.
    # `quantity` (the Placement Qty actually received into inventory) is
    # computed client-side as chicks_ordered - transit_mortality - shortage
    # - culls and is the ONLY figure that affects warehouse stock.
    chicks_ordered = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    transit_mortality = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    shortage = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    culls = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    purchase_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    rate = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    stock = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False,
                                help_text="Running closing stock of the item at the source location after this transfer")

    from_location_type = models.CharField(max_length=10, choices=LOCATION_TYPE_CHOICES, default='warehouse')
    from_warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, null=True, blank=True,
                                       related_name='stock_transfers_out')
    from_farm = models.ForeignKey('broiler.BroilerFarm', on_delete=models.PROTECT, null=True, blank=True,
                                  related_name='stock_transfers_out')
    # Only meaningful when from_location_type == 'farm' — which of that
    # farm's batches this stock is being moved out of/consumed against.
    from_batch = models.ForeignKey('broiler.BroilerBatch', on_delete=models.PROTECT, null=True, blank=True,
                                   related_name='stock_transfers_out')

    to_location_type = models.CharField(max_length=10, choices=LOCATION_TYPE_CHOICES, default='warehouse')
    to_warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, null=True, blank=True,
                                     related_name='stock_transfers_in')
    to_farm = models.ForeignKey('broiler.BroilerFarm', on_delete=models.PROTECT, null=True, blank=True,
                                related_name='stock_transfers_in')
    # Only meaningful when to_location_type == 'farm' — which of that farm's
    # batches this stock is being received into.
    to_batch = models.ForeignKey('broiler.BroilerBatch', on_delete=models.PROTECT, null=True, blank=True,
                                 related_name='stock_transfers_in')

    # Reference-only: the hatchery chicks actually originated from, for
    # transfers recorded via Broiler > Chicks Placement — the transfer
    # itself is still Warehouse -> Farm; this doesn't change that flow.
    source_hatchery = models.ForeignKey('hatchery_master.Hatchery', on_delete=models.SET_NULL, null=True, blank=True,
                                        related_name='stock_transfers_sourced')

    vehicle_no = models.CharField(max_length=50, blank=True)
    driver_name = models.CharField(max_length=100, blank=True)
    remarks = models.CharField(max_length=255, blank=True)

    created_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='stock_transfers_created')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-id']

    def __str__(self):
        return f"{self.trnum} ({self.from_location} -> {self.to_location})"

    @property
    def from_location(self):
        return self.from_farm if self.from_location_type == 'farm' else self.from_warehouse

    @property
    def to_location(self):
        return self.to_farm if self.to_location_type == 'farm' else self.to_warehouse

    def _location_key(self, side):
        """(location_type, location_id) for 'from' or 'to' — the identity a
        transfer's source/destination is chained/compared on, regardless of
        whether it's a Warehouse or a Farm."""
        location_type = getattr(self, f"{side}_location_type")
        warehouse_id = getattr(self, f"{side}_warehouse_id")
        farm_id = getattr(self, f"{side}_farm_id")
        return location_type, (farm_id if location_type == 'farm' else warehouse_id)

    def clean(self):
        if self.from_location_type == 'warehouse' and not self.from_warehouse_id:
            raise ValidationError("From Location (Warehouse) is required.")
        if self.from_location_type == 'farm' and not self.from_farm_id:
            raise ValidationError("From Location (Farm) is required.")
        if self.to_location_type == 'warehouse' and not self.to_warehouse_id:
            raise ValidationError("To Location (Warehouse) is required.")
        if self.to_location_type == 'farm' and not self.to_farm_id:
            raise ValidationError("To Location (Farm) is required.")
        if self._location_key('from') == self._location_key('to'):
            raise ValidationError("From Location and To Location must be different.")

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.trnum:
            self.trnum = self._next_trnum(self.date)
            super().save(update_fields=["trnum"])

    @classmethod
    def _next_trnum(cls, on_date=None):
        current_date = on_date or now().date()
        start_year = current_date.year if current_date.month >= 4 else current_date.year - 1
        fy = f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"
        prefix = f"ST-{fy}-"
        max_num = 0
        for existing in cls.objects.filter(trnum__startswith=prefix).values_list("trnum", flat=True):
            match = re.match(rf"^{re.escape(prefix)}(\d+)$", existing or "")
            if match:
                max_num = max(max_num, int(match.group(1)))
        return f"{prefix}{max_num + 1:04d}"

    @staticmethod
    def previous_stock(location_type, location_id, item_id, before_date, before_id):
        """Closing stock of the most recent prior transfer out of this
        source location (Warehouse or Farm) for this item, ordered by date
        then id (0 if none)."""
        if not location_type or not location_id or not item_id:
            return 0
        filters = {"from_location_type": location_type, "item_id": item_id}
        filters["from_farm_id" if location_type == "farm" else "from_warehouse_id"] = location_id
        if before_id:
            date_filter = models.Q(date__lt=before_date) | (models.Q(date=before_date) & models.Q(id__lt=before_id))
        else:
            date_filter = models.Q(date__lte=before_date)
        row = (StockTransfer.objects.filter(**filters)
               .filter(date_filter).order_by('-date', '-id').first())
        return row.stock if row else 0


class MedicineTransfer(models.Model):
    """One dispatch of medicine/vaccine items from one location to another —
    Office/Warehouse or Broiler Farm, in any combination — via Inventory >
    Transactions > Medicine Vaccine Transfer. A single header can carry
    several item lines (see MedicineTransferItem), each with its own running
    closing-stock balance at the shared source location."""

    LOCATION_TYPE_CHOICES = [
        ('warehouse', 'Warehouse'),
        ('farm', 'Farm'),
    ]

    trnum = models.CharField(max_length=30, unique=True, editable=False, blank=True,
                             help_text="Auto-generated transfer number, e.g. MT-2627-0001")
    date = models.DateField(default=now)
    dc_no = models.CharField(max_length=100, blank=True)

    from_location_type = models.CharField(max_length=10, choices=LOCATION_TYPE_CHOICES, default='warehouse')
    from_warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, null=True, blank=True,
                                       related_name='medicine_transfers_out')
    from_farm = models.ForeignKey('broiler.BroilerFarm', on_delete=models.PROTECT, null=True, blank=True,
                                  related_name='medicine_transfers_out')
    # Only meaningful when from_location_type == 'farm'.
    from_batch = models.ForeignKey('broiler.BroilerBatch', on_delete=models.PROTECT, null=True, blank=True,
                                   related_name='medicine_transfers_out')

    to_location_type = models.CharField(max_length=10, choices=LOCATION_TYPE_CHOICES, default='warehouse')
    to_warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, null=True, blank=True,
                                     related_name='medicine_transfers_in')
    to_farm = models.ForeignKey('broiler.BroilerFarm', on_delete=models.PROTECT, null=True, blank=True,
                                related_name='medicine_transfers_in')
    # Only meaningful when to_location_type == 'farm'.
    to_batch = models.ForeignKey('broiler.BroilerBatch', on_delete=models.PROTECT, null=True, blank=True,
                                 related_name='medicine_transfers_in')

    vehicle_no = models.CharField(max_length=50, blank=True)
    driver_name = models.CharField(max_length=100, blank=True)
    transport_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    paid_by = models.ForeignKey('account.ChartOfAccount', on_delete=models.SET_NULL, null=True, blank=True,
                                related_name='medicine_transfers_paid')

    created_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='medicine_transfers_created')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-id']

    def __str__(self):
        return f"{self.trnum} ({self.from_location} -> {self.to_location})"

    @property
    def from_location(self):
        return self.from_farm if self.from_location_type == 'farm' else self.from_warehouse

    @property
    def to_location(self):
        return self.to_farm if self.to_location_type == 'farm' else self.to_warehouse

    def _location_key(self, side):
        location_type = getattr(self, f"{side}_location_type")
        warehouse_id = getattr(self, f"{side}_warehouse_id")
        farm_id = getattr(self, f"{side}_farm_id")
        return location_type, (farm_id if location_type == 'farm' else warehouse_id)

    def clean(self):
        if self.from_location_type == 'warehouse' and not self.from_warehouse_id:
            raise ValidationError("From Location (Warehouse) is required.")
        if self.from_location_type == 'farm' and not self.from_farm_id:
            raise ValidationError("From Location (Farm) is required.")
        if self.to_location_type == 'warehouse' and not self.to_warehouse_id:
            raise ValidationError("To Location (Warehouse) is required.")
        if self.to_location_type == 'farm' and not self.to_farm_id:
            raise ValidationError("To Location (Farm) is required.")
        if self._location_key('from') == self._location_key('to'):
            raise ValidationError("From Location and To Location must be different.")

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.trnum:
            self.trnum = self._next_trnum(self.date)
            super().save(update_fields=["trnum"])

    @classmethod
    def _next_trnum(cls, on_date=None):
        current_date = on_date or now().date()
        start_year = current_date.year if current_date.month >= 4 else current_date.year - 1
        fy = f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"
        prefix = f"MT-{fy}-"
        max_num = 0
        for existing in cls.objects.filter(trnum__startswith=prefix).values_list("trnum", flat=True):
            match = re.match(rf"^{re.escape(prefix)}(\d+)$", existing or "")
            if match:
                max_num = max(max_num, int(match.group(1)))
        return f"{prefix}{max_num + 1:04d}"


class MedicineTransferItem(models.Model):
    """One item line within a MedicineTransfer header, with a running
    closing-stock balance for that item at the header's shared source
    location."""

    transfer = models.ForeignKey(MedicineTransfer, on_delete=models.CASCADE, related_name='items')
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name='medicine_transfer_items')
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    rate = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    remarks = models.CharField(max_length=255, blank=True)
    stock = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False,
                                help_text="Running closing stock of the item at the transfer's source location after this line")

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"{self.transfer.trnum} - {self.item}"

    @staticmethod
    def previous_stock(location_type, location_id, item_id, before_date, before_id):
        """Closing stock of the most recent prior line moved out of this
        source location (Warehouse or Farm) for this item, ordered by the
        header's date then this line's id (0 if none)."""
        if not location_type or not location_id or not item_id:
            return 0
        filters = {"transfer__from_location_type": location_type, "item_id": item_id}
        filters["transfer__from_farm_id" if location_type == "farm" else "transfer__from_warehouse_id"] = location_id
        if before_id:
            date_filter = (models.Q(transfer__date__lt=before_date)
                           | (models.Q(transfer__date=before_date) & models.Q(id__lt=before_id)))
        else:
            date_filter = models.Q(transfer__date__lte=before_date)
        row = (MedicineTransferItem.objects.filter(**filters)
               .filter(date_filter).order_by('-transfer__date', '-id').first())
        return row.stock if row else 0


class InventoryAdjustment(models.Model):
    """One stock correction at a single Location — Office/Warehouse or
    Broiler Farm — Inventory > Transactions > Inventory Adjustment. A single
    header (one Location, one Chart of Account) can carry several item
    lines, each independently adding to or deducting from that location's
    running stock."""

    LOCATION_TYPE_CHOICES = [
        ('warehouse', 'Warehouse'),
        ('farm', 'Farm'),
    ]

    trnum = models.CharField(max_length=30, unique=True, editable=False, blank=True,
                             help_text="Auto-generated invoice number, e.g. IA-2627-0001")
    date = models.DateField(default=now)
    bill_no = models.CharField(max_length=100, blank=True)

    location_type = models.CharField(max_length=10, choices=LOCATION_TYPE_CHOICES, default='warehouse')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, null=True, blank=True,
                                  related_name='inventory_adjustments')
    farm = models.ForeignKey('broiler.BroilerFarm', on_delete=models.PROTECT, null=True, blank=True,
                             related_name='inventory_adjustments')
    # Only meaningful when location_type == 'farm'.
    batch = models.ForeignKey('broiler.BroilerBatch', on_delete=models.PROTECT, null=True, blank=True,
                              related_name='inventory_adjustments')

    chart_of_account = models.ForeignKey('account.ChartOfAccount', on_delete=models.PROTECT,
                                         related_name='inventory_adjustments')

    created_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='inventory_adjustments_created')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-id']

    def __str__(self):
        return f"{self.trnum} ({self.location})"

    @property
    def location(self):
        return self.farm if self.location_type == 'farm' else self.warehouse

    def clean(self):
        if self.location_type == 'warehouse' and not self.warehouse_id:
            raise ValidationError("Location (Warehouse) is required.")
        if self.location_type == 'farm' and not self.farm_id:
            raise ValidationError("Location (Farm) is required.")

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.trnum:
            self.trnum = self._next_trnum(self.date)
            super().save(update_fields=["trnum"])

    @classmethod
    def _next_trnum(cls, on_date=None):
        current_date = on_date or now().date()
        start_year = current_date.year if current_date.month >= 4 else current_date.year - 1
        fy = f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"
        prefix = f"IA-{fy}-"
        max_num = 0
        for existing in cls.objects.filter(trnum__startswith=prefix).values_list("trnum", flat=True):
            match = re.match(rf"^{re.escape(prefix)}(\d+)$", existing or "")
            if match:
                max_num = max(max_num, int(match.group(1)))
        return f"{prefix}{max_num + 1:04d}"


class InventoryAdjustmentItem(models.Model):
    """One item line within an InventoryAdjustment header — either adds to
    or deducts from the item's running stock at the header's Warehouse."""

    ADJUSTMENT_TYPE_CHOICES = [
        ('Add', 'Add'),
        ('Deduct', 'Deduct'),
    ]

    adjustment = models.ForeignKey(InventoryAdjustment, on_delete=models.CASCADE, related_name='items')
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name='inventory_adjustment_items')
    adjustment_type = models.CharField(max_length=10, choices=ADJUSTMENT_TYPE_CHOICES)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    rate = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    remarks = models.CharField(max_length=255, blank=True)
    stock = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False,
                                help_text="Running closing stock of the item at the adjustment's location after this line")

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"{self.adjustment.trnum} - {self.item} ({self.adjustment_type})"

    def save(self, *args, **kwargs):
        self.amount = self.quantity * self.rate
        super().save(*args, **kwargs)

    @property
    def signed_quantity(self):
        return self.quantity if self.adjustment_type == 'Add' else -self.quantity

    @staticmethod
    def previous_stock(location_type, location_id, item_id, before_date, before_id):
        """Closing stock of the most recent prior line at this location
        (Warehouse or Farm) for this item, ordered by the header's date
        then this line's id (0 if none)."""
        if not location_type or not location_id or not item_id:
            return 0
        filters = {"adjustment__location_type": location_type, "item_id": item_id}
        filters["adjustment__farm_id" if location_type == "farm" else "adjustment__warehouse_id"] = location_id
        if before_id:
            date_filter = (models.Q(adjustment__date__lt=before_date)
                           | (models.Q(adjustment__date=before_date) & models.Q(id__lt=before_id)))
        else:
            date_filter = models.Q(adjustment__date__lte=before_date)
        row = (InventoryAdjustmentItem.objects.filter(**filters)
               .filter(date_filter).order_by('-adjustment__date', '-id').first())
        return row.stock if row else 0


class StockIssue(models.Model):
    """One issue of stock for use/consumption — Inventory > Transactions >
    Stock Issued. A single header (one Date, one Chart of Account) can carry
    several item lines, each issued to its own Location (Warehouse or Farm).
    Purely a record/audit trail — unlike Stock Transfer, Medicine Vaccine
    Transfer, and Inventory Adjustment, it does not track a running stock
    balance (matches the Add form/list, which have no Stock column)."""

    trnum = models.CharField(max_length=30, unique=True, editable=False, blank=True,
                             help_text="Auto-generated invoice number, e.g. SI-2627-0001")
    date = models.DateField(default=now)
    chart_of_account = models.ForeignKey('account.ChartOfAccount', on_delete=models.PROTECT,
                                         related_name='stock_issues')

    created_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='stock_issues_created')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-id']

    def __str__(self):
        return self.trnum

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.trnum:
            self.trnum = self._next_trnum(self.date)
            super().save(update_fields=["trnum"])

    @classmethod
    def _next_trnum(cls, on_date=None):
        current_date = on_date or now().date()
        start_year = current_date.year if current_date.month >= 4 else current_date.year - 1
        fy = f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"
        prefix = f"SI-{fy}-"
        max_num = 0
        for existing in cls.objects.filter(trnum__startswith=prefix).values_list("trnum", flat=True):
            match = re.match(rf"^{re.escape(prefix)}(\d+)$", existing or "")
            if match:
                max_num = max(max_num, int(match.group(1)))
        return f"{prefix}{max_num + 1:04d}"


class StockIssueItem(models.Model):
    """One item line within a StockIssue header, issued to its own Location
    (Warehouse or Farm), with an optional Batch when that Location is a
    Farm."""

    LOCATION_TYPE_CHOICES = [
        ('warehouse', 'Warehouse'),
        ('farm', 'Farm'),
    ]

    issue = models.ForeignKey(StockIssue, on_delete=models.CASCADE, related_name='items')
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name='stock_issue_items')
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    rate = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)

    location_type = models.CharField(max_length=10, choices=LOCATION_TYPE_CHOICES, default='warehouse')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, null=True, blank=True,
                                  related_name='stock_issue_items')
    farm = models.ForeignKey('broiler.BroilerFarm', on_delete=models.PROTECT, null=True, blank=True,
                             related_name='stock_issue_items')
    # Only meaningful when location_type == 'farm'.
    batch = models.ForeignKey('broiler.BroilerBatch', on_delete=models.PROTECT, null=True, blank=True,
                              related_name='stock_issue_items')

    remarks = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"{self.issue.trnum} - {self.item}"

    @property
    def location(self):
        return self.farm if self.location_type == 'farm' else self.warehouse

    def clean(self):
        if self.location_type == 'warehouse' and not self.warehouse_id:
            raise ValidationError("Location (Warehouse) is required.")
        if self.location_type == 'farm' and not self.farm_id:
            raise ValidationError("Location (Farm) is required.")

    def save(self, *args, **kwargs):
        self.amount = self.quantity * self.rate
        super().save(*args, **kwargs)


class StockReceive(models.Model):
    """One receipt of stock — Inventory > Transactions > Stock Received. A
    single header (one Date, one Chart of Account) can carry several item
    lines, each received from its own Location (Warehouse or Farm). Purely a
    record/audit trail, mirroring StockIssue — no running stock balance."""

    trnum = models.CharField(max_length=30, unique=True, editable=False, blank=True,
                             help_text="Auto-generated invoice number, e.g. SR-2627-0001")
    date = models.DateField(default=now)
    chart_of_account = models.ForeignKey('account.ChartOfAccount', on_delete=models.PROTECT,
                                         related_name='stock_receives')

    created_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='stock_receives_created')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-id']

    def __str__(self):
        return self.trnum

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.trnum:
            self.trnum = self._next_trnum(self.date)
            super().save(update_fields=["trnum"])

    @classmethod
    def _next_trnum(cls, on_date=None):
        current_date = on_date or now().date()
        start_year = current_date.year if current_date.month >= 4 else current_date.year - 1
        fy = f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"
        prefix = f"SR-{fy}-"
        max_num = 0
        for existing in cls.objects.filter(trnum__startswith=prefix).values_list("trnum", flat=True):
            match = re.match(rf"^{re.escape(prefix)}(\d+)$", existing or "")
            if match:
                max_num = max(max_num, int(match.group(1)))
        return f"{prefix}{max_num + 1:04d}"


class StockReceiveItem(models.Model):
    """One item line within a StockReceive header, received from its own
    Location (Warehouse or Farm), with an optional Batch when that Location
    is a Farm."""

    LOCATION_TYPE_CHOICES = [
        ('warehouse', 'Warehouse'),
        ('farm', 'Farm'),
    ]

    receive = models.ForeignKey(StockReceive, on_delete=models.CASCADE, related_name='items')
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name='stock_receive_items')
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    rate = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)

    location_type = models.CharField(max_length=10, choices=LOCATION_TYPE_CHOICES, default='warehouse')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, null=True, blank=True,
                                  related_name='stock_receive_items')
    farm = models.ForeignKey('broiler.BroilerFarm', on_delete=models.PROTECT, null=True, blank=True,
                             related_name='stock_receive_items')
    # Only meaningful when location_type == 'farm'.
    batch = models.ForeignKey('broiler.BroilerBatch', on_delete=models.PROTECT, null=True, blank=True,
                              related_name='stock_receive_items')

    remarks = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"{self.receive.trnum} - {self.item}"

    @property
    def location(self):
        return self.farm if self.location_type == 'farm' else self.warehouse

    def clean(self):
        if self.location_type == 'warehouse' and not self.warehouse_id:
            raise ValidationError("Location (Warehouse) is required.")
        if self.location_type == 'farm' and not self.farm_id:
            raise ValidationError("Location (Farm) is required.")

    def save(self, *args, **kwargs):
        self.amount = self.quantity * self.rate
        super().save(*args, **kwargs)
