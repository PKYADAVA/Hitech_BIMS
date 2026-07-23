import re

from django.db import models
from django.core.validators import RegexValidator, MinValueValidator, MaxValueValidator
from django.utils.translation import gettext_lazy as _
from django.utils.timezone import now
from django.core.exceptions import ValidationError
import os


class FarmerGroup(models.Model):
    """
    Represents an accounting group that farmers are assigned to, tying
    each group to the ledger accounts used for their payables/advances.
    """
    code = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
        blank=True,
        help_text=_("Auto-generated code for this farmer group")
    )
    description = models.CharField(
        max_length=150,
        help_text=_("Name of the farmer group")
    )
    pay_account = models.ForeignKey(
        'account.ChartOfAccount',
        on_delete=models.PROTECT,
        related_name='farmer_group_pay_accounts',
        help_text=_("Payable account for this group")
    )
    advance_account = models.ForeignKey(
        'account.ChartOfAccount',
        on_delete=models.PROTECT,
        related_name='farmer_group_advance_accounts',
        help_text=_("Advance account for this group")
    )
    is_active = models.BooleanField(
        default=True,
        help_text=_("Inactive groups are hidden from selection elsewhere")
    )
    is_locked = models.BooleanField(
        default=False,
        help_text=_("Locked records can't be edited or deleted")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Farmer Group")
        verbose_name_plural = _("Farmer Groups")
        ordering = ['code']

    def __str__(self):
        return f"{self.code} - {self.description}"

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.code:
            self.code = f"FGP-{self.pk:04d}"
            super().save(update_fields=['code'])


class Region(models.Model):
    """
    Represents a region (state) master used to categorize branches/farms.
    """
    code = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
        blank=True,
        help_text=_("Auto-generated code for this region")
    )
    description = models.CharField(
        max_length=100,
        help_text=_("Name of the region (state)")
    )
    is_active = models.BooleanField(
        default=True,
        help_text=_("Inactive regions are hidden from selection elsewhere")
    )
    is_locked = models.BooleanField(
        default=False,
        help_text=_("Locked records can't be edited or deleted")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Region")
        verbose_name_plural = _("Regions")
        ordering = ['code']

    def __str__(self):
        return f"{self.code} - {self.description}"

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.code:
            self.code = f"RGN-{self.pk:04d}"
            super().save(update_fields=['code'])


class Breed(models.Model):
    """
    Represents a broiler breed master (e.g. COBB 430 Y) used by the
    Growing Charges module.
    """
    code = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
        blank=True,
        help_text=_("Auto-generated code for this breed")
    )
    description = models.CharField(
        max_length=100,
        help_text=_("Name of the breed")
    )
    is_active = models.BooleanField(
        default=True,
        help_text=_("Inactive breeds are hidden from selection elsewhere")
    )
    is_locked = models.BooleanField(
        default=False,
        help_text=_("Locked records can't be edited or deleted")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Breed")
        verbose_name_plural = _("Breeds")
        ordering = ['code']

    def __str__(self):
        return f"{self.code} - {self.description}"

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.code:
            self.code = f"BRE-{self.pk:04d}"
            super().save(update_fields=['code'])


class BreedStandard(models.Model):
    """
    A single age-row of a breed's standard performance curve
    (body weight / feed intake / daily gain / FCR / cumulative feed by age).
    One record per (breed, age); the Breed Standard master holds the whole
    curve as a group of these rows.
    """
    code = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
        blank=True,
        help_text=_("Auto-generated code for this breed standard row")
    )
    breed = models.ForeignKey(
        Breed,
        on_delete=models.PROTECT,
        related_name='standards',
        help_text=_("Breed this standard row belongs to")
    )
    age = models.PositiveIntegerField(help_text=_("Age (day) of the standard row"))
    body_weight = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    feed_intake = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    avg_daily_gain = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    fcr = models.DecimalField(max_digits=10, decimal_places=3, default=0)
    cum_feed = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_active = models.BooleanField(
        default=True,
        help_text=_("Inactive rows are hidden from selection elsewhere")
    )
    is_locked = models.BooleanField(
        default=False,
        help_text=_("Locked records can't be edited or deleted")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Breed Standard")
        verbose_name_plural = _("Breed Standards")
        ordering = ['breed__code', 'age']
        unique_together = ('breed', 'age')

    def __str__(self):
        return f"{self.code} - {self.breed.description} (age {self.age})"

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.code:
            self.code = f"BS-{self.pk:04d}"
            super().save(update_fields=['code'])


class Branch(models.Model):
    """
    Represents a branch location in the broiler management system.
    """
    code = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
        blank=True,
        help_text=_("Auto-generated code for this branch")
    )
    branch_name = models.CharField(
        max_length=100,
        unique=True,
        help_text=_("Name of the branch")
    )
    region = models.ForeignKey(
        Region,
        on_delete=models.PROTECT,
        related_name='branches',
        help_text=_("Region this branch belongs to")
    )
    prefix = models.CharField(
        max_length=10,
        help_text=_("Short prefix code for this branch")
    )
    is_active = models.BooleanField(
        default=True,
        help_text=_("Inactive branches are hidden from selection elsewhere")
    )
    is_locked = models.BooleanField(
        default=False,
        help_text=_("Locked records can't be edited or deleted")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Branch")
        verbose_name_plural = _("Branches")
        ordering = ['code']

    def __str__(self):
        return f"{self.branch_name} ({self.region.description})"

    def get_farm_count(self):
        """Returns the number of farms in this branch."""
        return self.broilerfarm_set.count()

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.code:
            self.code = f"BRH-{self.pk:04d}"
            super().save(update_fields=['code'])


class Supervisor(models.Model):
    """
    Represents a supervisor who manages broiler farms.
    """
    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name='supervisors',
        help_text=_("Branch this supervisor belongs to")
    )
    employee = models.ForeignKey(
        'hr.Employee',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='broiler_supervisor_roles',
        help_text=_("HR employee record this supervisor is — name/phone/address are copied from here")
    )
    name = models.CharField(
        max_length=100,
        help_text=_("Full name of the supervisor")
    )
    phone_no = models.CharField(
        max_length=15,
        blank=True,
        validators=[
            RegexValidator(
                regex=r'^\+?1?\d{9,15}$',
                message=_("Phone number must be entered in the format: '+999999999'. Up to 15 digits allowed.")
            )
        ],
        help_text=_("Contact number of the supervisor")
    )
    address = models.TextField(blank=True, help_text=_("Residential address of the supervisor"))
    email = models.EmailField(blank=True, null=True, help_text=_("Email address of the supervisor"))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Supervisor")
        verbose_name_plural = _("Supervisors")
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.branch.branch_name})"


class BroilerLine(models.Model):
    """
    Represents a line (formerly "broiler place") within a branch/region
    where broiler farms are situated.
    """
    code = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
        blank=True,
        help_text=_("Auto-generated code for this line")
    )
    description = models.CharField(
        max_length=100,
        help_text=_("Name of the line")
    )
    region = models.ForeignKey(
        Region,
        on_delete=models.PROTECT,
        related_name='broiler_lines',
        help_text=_("Region this line belongs to")
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name='broiler_lines',
        help_text=_("Branch this line belongs to")
    )
    is_active = models.BooleanField(
        default=True,
        help_text=_("Inactive lines are hidden from selection elsewhere")
    )
    is_locked = models.BooleanField(
        default=False,
        help_text=_("Locked records can't be edited or deleted")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Broiler Line")
        verbose_name_plural = _("Broiler Lines")
        ordering = ['code']

    def __str__(self):
        return f"{self.code} - {self.description}"

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.code:
            self.code = f"LNS-{self.pk:04d}"
            super().save(update_fields=['code'])


class Farmer(models.Model):
    """
    Represents a farmer who owns or operates broiler farms.
    """
    farmer_name = models.CharField(
        max_length=150,
        help_text=_("Full name of the farmer")
    )
    phone_no = models.CharField(
        max_length=15,
        blank=True,
        null=True,
        help_text=_("Landline/phone number of the farmer")
    )
    mobile_no = models.CharField(
        max_length=15,
        blank=True,
        null=True,
        help_text=_("Primary mobile number of the farmer")
    )
    mobile_2 = models.CharField(
        max_length=15,
        blank=True,
        null=True,
        help_text=_("Secondary mobile number of the farmer")
    )
    farmer_photo = models.ImageField(
        upload_to='farmer/photos/',
        blank=True,
        null=True,
        help_text=_("Photograph of the farmer")
    )
    pan_no = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        help_text=_("PAN number of the farmer")
    )
    aadhar_no = models.CharField(
        max_length=12,
        blank=True,
        null=True,
        help_text=_("Aadhar number of the farmer")
    )
    national_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text=_("National ID of the farmer")
    )
    pan_upload = models.FileField(
        upload_to='farmer/pan/',
        blank=True,
        null=True,
        help_text=_("Uploaded copy of PAN card")
    )
    aadhar_upload_front = models.FileField(
        upload_to='farmer/aadhar/',
        blank=True,
        null=True,
        help_text=_("Uploaded copy of Aadhar card (front)")
    )
    aadhar_upload_back = models.FileField(
        upload_to='farmer/aadhar/',
        blank=True,
        null=True,
        help_text=_("Uploaded copy of Aadhar card (back)")
    )
    usc = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text=_("USC of the farmer")
    )
    service_no = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text=_("Service number of the farmer")
    )
    farmer_group = models.ForeignKey(
        FarmerGroup,
        on_delete=models.PROTECT,
        related_name='farmers',
        null=True,
        help_text=_("Group the farmer belongs to")
    )
    tds_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        blank=True,
        null=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text=_("TDS percentage applicable to the farmer")
    )
    account_holder_name = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        help_text=_("Name on the bank account")
    )
    acc_no = models.CharField(
        max_length=30,
        blank=True,
        null=True,
        help_text=_("Bank account number")
    )
    ifsc_code = models.CharField(
        max_length=15,
        blank=True,
        null=True,
        help_text=_("Bank IFSC code")
    )
    bank_name = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text=_("Name of the bank")
    )
    bank_branch = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text=_("Bank branch")
    )
    address = models.TextField(
        blank=True,
        null=True,
        help_text=_("Residential address of the farmer")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Farmer")
        verbose_name_plural = _("Farmers")
        ordering = ['farmer_name']

    def __str__(self):
        return self.farmer_name

    def get_farm_count(self):
        """Returns the number of farms belonging to this farmer."""
        return self.broiler_farms.count()


class BroilerFarm(models.Model):
    """
    Represents a broiler farm with its details and location.
    """
    FARM_TYPES = [
        ('own', _('Own')),
        ('ec_shed', _('Ec Shed')),
        ('integration', _('Integration')),
    ]

    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name='broiler_farms',
        help_text=_("Branch this farm belongs to")
    )
    supervisor = models.ForeignKey(
        Supervisor,
        on_delete=models.CASCADE,
        related_name='broiler_farms',
        help_text=_("Supervisor managing this farm")
    )
    farmer = models.ForeignKey(
        Farmer,
        on_delete=models.CASCADE,
        related_name='broiler_farms',
        help_text=_("Farmer who owns/operates this farm")
    )
    region = models.CharField(
        max_length=100,
        help_text=_("Region of the farm")
    )
    line = models.CharField(
        max_length=100,
        help_text=_("Line for this farm")
    )
    farm_code = models.CharField(
        max_length=50,
        unique=True,
        editable=False,
        blank=True,
        help_text=_("Auto-generated code, e.g. AKB-0203 — <branch prefix>-<branch code suffix><farm serial>")
    )
    farm_name = models.CharField(
        max_length=100,
        help_text=_("Name of the farm")
    )
    farm_pincode = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        help_text=_("Pincode of the farm")
    )
    farm_capacity = models.PositiveIntegerField(
        help_text=_("Bird capacity of the farm")
    )
    farm_type = models.CharField(
        max_length=50,
        choices=FARM_TYPES,
        default='own',
        help_text=_("Type of farm operation")
    )
    state = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text=_("State where the farm is located")
    )
    district = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text=_("District where the farm is located")
    )
    area = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text=_("Area where the farm is located")
    )
    farm_address = models.TextField(
        blank=True,
        null=True,
        help_text=_("Detailed address of the farm")
    )
    farm_latitude = models.FloatField(
        blank=True,
        null=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
        help_text=_("Latitude coordinate of the farm")
    )
    farm_longitude = models.FloatField(
        blank=True,
        null=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
        help_text=_("Longitude coordinate of the farm")
    )
    agreement_start_date = models.DateField(
        blank=True,
        null=True,
        help_text=_("Agreement start date")
    )
    agreement_end_date = models.DateField(
        blank=True,
        null=True,
        help_text=_("Agreement end date")
    )
    agreement_months = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text=_("Duration of the agreement in months")
    )
    agreement_copy = models.FileField(
        upload_to='farm/agreements/',
        blank=True,
        null=True,
        help_text=_("Uploaded copy of the agreement")
    )
    other_documents = models.FileField(
        upload_to='farm/documents/',
        blank=True,
        null=True,
        help_text=_("Other supporting documents")
    )
    farm_sqft = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text=_("Farm area in square feet")
    )
    cheque_1_no = models.CharField(max_length=30, blank=True, help_text=_("Security cheque 1 number"))
    cheque_1_file = models.FileField(upload_to='farm/cheques/', blank=True, null=True, help_text=_("Security cheque 1 scan"))
    cheque_2_no = models.CharField(max_length=30, blank=True, help_text=_("Security cheque 2 number"))
    cheque_2_file = models.FileField(upload_to='farm/cheques/', blank=True, null=True, help_text=_("Security cheque 2 scan"))
    cheque_3_no = models.CharField(max_length=30, blank=True, help_text=_("Security cheque 3 number"))
    cheque_3_file = models.FileField(upload_to='farm/cheques/', blank=True, null=True, help_text=_("Security cheque 3 scan"))
    cheque_4_no = models.CharField(max_length=30, blank=True, help_text=_("Security cheque 4 number"))
    cheque_4_file = models.FileField(upload_to='farm/cheques/', blank=True, null=True, help_text=_("Security cheque 4 scan"))
    remarks = models.TextField(
        blank=True,
        null=True,
        help_text=_("Additional remarks about the farm/shed information")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Broiler Farm")
        verbose_name_plural = _("Broiler Farms")
        ordering = ['farm_name']
        unique_together = ['farm_code', 'branch']

    def __str__(self):
        return f"{self.farm_name} ({self.farm_code})"

    def get_batch_count(self):
        """Returns the number of batches in this farm."""
        return self.broilerbatch_set.count()

    def clean(self):
        """Validate that the supervisor belongs to the selected branch."""
        if self.supervisor.branch != self.branch:
            raise ValidationError({
                'supervisor': _('Selected supervisor does not belong to the selected branch.')
            })

    @classmethod
    def next_farm_code(cls, branch):
        """<branch prefix>-<branch code suffix><per-branch serial>, e.g.
        the 3rd farm of branch AKB (code BRH-0002) is AKB-0203."""
        match = re.match(r"^BRH-(\d+)$", branch.code or "")
        branch_suffix = f"{int(match.group(1)):02d}" if match else f"{branch.pk:02d}"
        prefix = f"{branch.prefix}-{branch_suffix}"
        serials = []
        for existing in cls.objects.filter(farm_code__startswith=prefix).values_list("farm_code", flat=True):
            code_match = re.match(rf"^{re.escape(prefix)}(\d+)$", existing or "")
            if code_match:
                serials.append(int(code_match.group(1)))
        return f"{prefix}{max(serials, default=0) + 1:02d}"

    def save(self, *args, **kwargs):
        if self._state.adding and not self.farm_code and self.branch_id:
            self.farm_code = self.next_farm_code(self.branch)
        super().save(*args, **kwargs)


class BroilerFarmShed(models.Model):
    """
    Represents a shed within a broiler farm.
    """
    farm = models.ForeignKey(
        BroilerFarm,
        on_delete=models.CASCADE,
        related_name='sheds',
        help_text=_("Farm this shed belongs to")
    )
    shed_no = models.CharField(
        max_length=50,
        help_text=_("Shed number/identifier")
    )
    dimensions = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text=_("Dimensions of the shed")
    )
    sq_feet = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text=_("Area of the shed in square feet")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Broiler Farm Shed")
        verbose_name_plural = _("Broiler Farm Sheds")
        ordering = ['shed_no']

    def __str__(self):
        return f"Shed {self.shed_no} ({self.farm.farm_name})"


class BroilerFarmImage(models.Model):
    """
    Represents a picture uploaded for a broiler farm.
    """
    farm = models.ForeignKey(
        BroilerFarm,
        on_delete=models.CASCADE,
        related_name='images',
        help_text=_("Farm this picture belongs to")
    )
    image = models.ImageField(
        upload_to='farm/pictures/',
        help_text=_("Farm picture")
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Broiler Farm Image")
        verbose_name_plural = _("Broiler Farm Images")
        ordering = ['-created_at']

    def __str__(self):
        return f"Image for {self.farm.farm_name}"


class BroilerBatch(models.Model):
    """
    Represents a batch of broilers in a farm.
    """
    broiler_farm = models.ForeignKey(
        BroilerFarm, 
        on_delete=models.CASCADE,
        related_name='broiler_batches',
        help_text=_("Farm this batch belongs to")
    )
    batch_name = models.CharField(
        max_length=50,
        blank=True,
        help_text=_("Auto-generated per farm, e.g. BAH-0201-1")
    )
    book_number = models.CharField(
        max_length=50,
        blank=True,
        help_text=_("Grower book number for this batch")
    )
    lot_no = models.CharField(
        max_length=50,
        blank=True,
        help_text=_("Lot number for this batch")
    )
    start_date = models.DateField(
        blank=True, 
        null=True,
        help_text=_("Date when the batch was started")
    )
    end_date = models.DateField(
        blank=True,
        null=True,
        help_text=_("Expected end date for the batch")
    )
    # Set when a Growing Charge Settlement closes the batch (batch closing).
    is_closed = models.BooleanField(default=False, help_text=_("Closed by a Growing Charge settlement"))
    closed_on = models.DateField(blank=True, null=True, help_text=_("Date the batch was closed/settled"))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Broiler Batch")
        verbose_name_plural = _("Broiler Batches")
        ordering = ['-created_at']
        unique_together = ['broiler_farm', 'batch_name']

    def __str__(self):
        return f"{self.batch_name} ({self.broiler_farm.farm_name})"

    def get_disease_count(self):
        """Returns the number of diseases recorded for this batch."""
        return self.broilerdisease_set.count()

    @classmethod
    def next_batch_name(cls, farm):
        """<farm code>-<n>, serial per farm — e.g. the 2nd batch of farm
        BAH-0201 is BAH-0201-2. removeprefix keeps batches short for farms
        created while codes still carried the old "FRM/" prefix."""
        prefix = f"{farm.farm_code.removeprefix('FRM/')}-"
        serials = []
        for existing in cls.objects.filter(broiler_farm=farm, batch_name__startswith=prefix).values_list("batch_name", flat=True):
            match = re.match(rf"^{re.escape(prefix)}(\d+)$", existing or "")
            if match:
                serials.append(int(match.group(1)))
        return f"{prefix}{max(serials, default=0) + 1}"

    def save(self, *args, **kwargs):
        if self._state.adding and not self.batch_name and self.broiler_farm_id:
            self.batch_name = self.next_batch_name(self.broiler_farm)
        super().save(*args, **kwargs)


class BroilerDisease(models.Model):
    """
    Represents a disease that can affect broiler batches.
    """
    batch = models.ForeignKey(
        BroilerBatch,
        on_delete=models.CASCADE,
        related_name='broiler_diseases',
        null=True,
        blank=True,
        help_text=_("Batch affected by this disease")
    )
    disease_code = models.CharField(
        max_length=50,
        help_text=_("Code or identifier for the disease")
    )
    disease_name = models.CharField(
        max_length=100,
        help_text=_("Name of the disease")
    )
    symptoms = models.TextField(help_text=_("Symptoms observed"))
    diagnosis = models.TextField(help_text=_("Diagnosis and treatment details"))
    image = models.ImageField(
        upload_to='disease_images/',
        blank=True,
        null=True,
        help_text=_("Image related to the disease")
    )
    diagnosed_date = models.DateField(
        auto_now_add=True,
        help_text=_("Date when the disease was diagnosed")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Broiler Disease")
        verbose_name_plural = _("Broiler Diseases")
        ordering = ['-diagnosed_date']

    def __str__(self):
        return f"{self.disease_name} ({self.batch.batch_name})"

    def get_batch_name(self):
        """Returns the name of the batch affected by this disease."""
        return self.batch.batch_name

    def image_filename(self):
        """Returns the filename of the uploaded image."""
        return os.path.basename(self.image.name) if self.image else None




class DailyEntry(models.Model):
    """A single day's record for one Farm/Batch — mortality, culls, feed
    consumption (up to two feed items with a running stock balance) and
    average bird weight (Broiler > Transactions > Daily Entry)."""

    entry_no = models.CharField(max_length=30, unique=True, editable=False, blank=True,
                                help_text="Auto-generated transaction number, e.g. DE-2627-0001")
    date = models.DateField(default=now)
    supervisor = models.ForeignKey(Supervisor, on_delete=models.PROTECT, related_name='daily_entries')
    farm = models.ForeignKey(BroilerFarm, on_delete=models.PROTECT, related_name='daily_entries')
    batch = models.ForeignKey(BroilerBatch, on_delete=models.PROTECT, null=True, blank=True,
                              related_name='daily_entries',
                              help_text="Auto-set to the farm's active batch at the time of entry")
    age_days = models.PositiveIntegerField(default=0, editable=False,
                                           help_text="Days since the batch's start date")
    mortality = models.PositiveIntegerField(default=0)
    culls = models.PositiveIntegerField(default=0)

    feed_1 = models.ForeignKey('inventory.Item', on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='daily_entry_feed_1')
    feed_1_qty = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Kgs fed")
    feed_1_stock = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False,
                                       help_text="Running closing stock after this entry")

    feed_2 = models.ForeignKey('inventory.Item', on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='daily_entry_feed_2')
    feed_2_qty = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Kgs fed")
    feed_2_stock = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False,
                                       help_text="Running closing stock after this entry")

    avg_weight_gms = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    remarks = models.CharField(max_length=255, blank=True)

    entry_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='broiler_daily_entries')
    entry_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Daily Entry")
        verbose_name_plural = _("Daily Entries")
        ordering = ['-date', '-id']

    def __str__(self):
        return f"{self.entry_no} ({self.farm.farm_name})"

    @property
    def is_batch_active(self):
        return bool(self.batch and self.batch.end_date is None)

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.entry_no:
            self.entry_no = self._next_entry_no(self.date)
            super().save(update_fields=["entry_no"])

    @classmethod
    def _next_entry_no(cls, on_date=None):
        current_date = on_date or now().date()
        start_year = current_date.year if current_date.month >= 4 else current_date.year - 1
        fy = f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"
        prefix = f"DE-{fy}-"
        max_num = 0
        for existing in cls.objects.filter(entry_no__startswith=prefix).values_list("entry_no", flat=True):
            match = re.match(rf"^{re.escape(prefix)}(\d+)$", existing or "")
            if match:
                max_num = max(max_num, int(match.group(1)))
        return f"{prefix}{max_num + 1:04d}"

    @staticmethod
    def previous_stock(farm_id, item_id, before_date, before_id):
        """Closing stock of the most recent prior entry for this farm+feed
        item, ordered by date then id (0 if there's no earlier entry).

        ``before_id`` is the row's own pk when editing an existing entry (so
        same-date rows saved after it are correctly excluded); it's None for
        a brand-new row, which has no id yet to compare against, so any
        same-date row already saved earlier in the same submission still
        counts as "previous" — restricting to date alone is correct there.
        """
        if not item_id:
            return 0
        if before_id:
            date_filter = models.Q(date__lt=before_date) | (models.Q(date=before_date) & models.Q(id__lt=before_id))
        else:
            date_filter = models.Q(date__lte=before_date)
        qs = DailyEntry.objects.filter(farm_id=farm_id).filter(date_filter).order_by('-date', '-id')
        for row in qs:
            if row.feed_1_id == item_id:
                return row.feed_1_stock
            if row.feed_2_id == item_id:
                return row.feed_2_stock
        return 0


class MedicineVaccineEntry(models.Model):
    """A medicine/vaccine issued to one Farm/Batch on a given day, with a
    running closing-stock balance for that item at that farm (Broiler >
    Transactions > Medicine Vaccine Consumption)."""

    entry_no = models.CharField(max_length=30, unique=True, editable=False, blank=True,
                                help_text="Auto-generated transaction number, e.g. MV-2627-0001")
    date = models.DateField(default=now)
    supervisor = models.ForeignKey(Supervisor, on_delete=models.PROTECT, related_name='medicine_entries')
    farm = models.ForeignKey(BroilerFarm, on_delete=models.PROTECT, related_name='medicine_entries')
    batch = models.ForeignKey(BroilerBatch, on_delete=models.PROTECT, null=True, blank=True,
                              related_name='medicine_entries',
                              help_text="Auto-set to the farm's active batch at the time of entry")
    age_days = models.PositiveIntegerField(default=0, editable=False,
                                           help_text="Days since the batch's start date")

    item = models.ForeignKey('inventory.Item', on_delete=models.PROTECT, related_name='medicine_entries')
    qty = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    stock = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False,
                                help_text="Running closing stock after this entry")

    remarks = models.CharField(max_length=255, blank=True)

    entry_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='broiler_medicine_entries')
    entry_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Medicine/Vaccine Entry")
        verbose_name_plural = _("Medicine/Vaccine Entries")
        ordering = ['-date', '-id']

    def __str__(self):
        return f"{self.entry_no} ({self.farm.farm_name})"

    @property
    def is_batch_active(self):
        return bool(self.batch and self.batch.end_date is None)

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.entry_no:
            self.entry_no = self._next_entry_no(self.date)
            super().save(update_fields=["entry_no"])

    @classmethod
    def _next_entry_no(cls, on_date=None):
        current_date = on_date or now().date()
        start_year = current_date.year if current_date.month >= 4 else current_date.year - 1
        fy = f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"
        prefix = f"MV-{fy}-"
        max_num = 0
        for existing in cls.objects.filter(entry_no__startswith=prefix).values_list("entry_no", flat=True):
            match = re.match(rf"^{re.escape(prefix)}(\d+)$", existing or "")
            if match:
                max_num = max(max_num, int(match.group(1)))
        return f"{prefix}{max_num + 1:04d}"

    @staticmethod
    def previous_stock(farm_id, item_id, before_date, before_id):
        """Closing stock of the most recent prior entry for this farm+item,
        ordered by date then id (0 if there's no earlier entry). See
        DailyEntry.previous_stock for the before_id/date-filter rationale."""
        if not item_id:
            return 0
        if before_id:
            date_filter = models.Q(date__lt=before_date) | (models.Q(date=before_date) & models.Q(id__lt=before_id))
        else:
            date_filter = models.Q(date__lte=before_date)
        row = (MedicineVaccineEntry.objects.filter(farm_id=farm_id, item_id=item_id)
               .filter(date_filter).order_by('-date', '-id').first())
        return row.stock if row else 0


class BirdSale(models.Model):
    """One sale of grown/live birds from a Farm/Batch to a Customer or a
    Farmer (Broiler > Transactions > Bird Sale). A record/audit document
    like Inventory's Stock Issue — it does not track a running live-bird
    balance on the batch."""

    SALE_TYPE_CHOICES = [
        ('customer', 'Customer Sale'),
        ('farmer', 'Farmer Sale'),
    ]

    sale_no = models.CharField(max_length=30, unique=True, editable=False, blank=True,
                               help_text="Auto-generated transaction number, e.g. BS-2627-0001")
    date = models.DateField(default=now)
    doc_no = models.CharField(max_length=100, blank=True, help_text="External/reference document number")

    sale_type = models.CharField(max_length=10, choices=SALE_TYPE_CHOICES, default='customer')
    customer = models.ForeignKey('sales.Customer', on_delete=models.PROTECT, null=True, blank=True,
                                 related_name='bird_sales')
    farmer = models.ForeignKey(Farmer, on_delete=models.PROTECT, null=True, blank=True,
                               related_name='bird_sales')

    farm = models.ForeignKey(BroilerFarm, on_delete=models.PROTECT, related_name='bird_sales')
    batch = models.ForeignKey(BroilerBatch, on_delete=models.PROTECT, null=True, blank=True,
                              related_name='bird_sales',
                              help_text="Auto-set to the farm's active batch at the time of sale")

    birds = models.PositiveIntegerField(default=0)
    net_weight = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Net weight in Kgs")
    avg_weight = models.DecimalField(max_digits=10, decimal_places=2, default=0, editable=False,
                                     help_text="Net weight / Birds")
    rate = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Rate per Kg")
    round_off = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False,
                                 help_text="Net weight x Rate + RoundOff")

    lifting_supervisor = models.ForeignKey(Supervisor, on_delete=models.SET_NULL, null=True, blank=True,
                                           related_name='bird_sales')
    vehicle = models.CharField(max_length=50, blank=True)
    driver = models.CharField(max_length=100, blank=True)
    remarks = models.CharField(max_length=255, blank=True)

    entry_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='broiler_bird_sales')
    entry_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Bird Sale")
        verbose_name_plural = _("Bird Sales")
        ordering = ['-date', '-id']

    def __str__(self):
        return self.sale_no

    @property
    def is_batch_active(self):
        return bool(self.batch and self.batch.end_date is None)

    def clean(self):
        if self.sale_type == 'customer' and not self.customer_id:
            raise ValidationError("Customer is required for a Customer Sale.")
        if self.sale_type == 'farmer' and not self.farmer_id:
            raise ValidationError("Farmer is required for a Farmer Sale.")

    def save(self, *args, **kwargs):
        self.avg_weight = round(self.net_weight / self.birds, 2) if self.birds else 0
        self.amount = (self.net_weight or 0) * (self.rate or 0) + (self.round_off or 0)
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.sale_no:
            self.sale_no = self._next_sale_no(self.date)
            super().save(update_fields=["sale_no"])

    @classmethod
    def _next_sale_no(cls, on_date=None):
        current_date = on_date or now().date()
        start_year = current_date.year if current_date.month >= 4 else current_date.year - 1
        fy = f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"
        prefix = f"BS-{fy}-"
        max_num = 0
        for existing in cls.objects.filter(sale_no__startswith=prefix).values_list("sale_no", flat=True):
            match = re.match(rf"^{re.escape(prefix)}(\d+)$", existing or "")
            if match:
                max_num = max(max_num, int(match.group(1)))
        return f"{prefix}{max_num + 1:04d}"


class BirdSaleReceipt(models.Model):
    """A payment received from a Bird Sale customer or farmer, booked
    against a cost centre (Broiler > Transactions > Receipt). Reduces that
    buyer's outstanding balance — not linked to one specific Bird Sale
    row, mirroring Purchase's Supplier Payment."""

    MODE_CHOICES = [
        ('Cash', 'Cash'), ('Bank Transfer', 'Bank Transfer'),
        ('Cheque', 'Cheque'), ('UPI', 'UPI'), ('Card', 'Card'),
    ]

    receipt_no = models.CharField(max_length=30, unique=True, editable=False, blank=True,
                                  help_text="Auto-generated transaction number, e.g. RC-2627-0001")
    date = models.DateField(default=now)
    location = models.ForeignKey('inventory.Warehouse', on_delete=models.PROTECT,
                                 related_name='bird_sale_receipts')

    sale_type = models.CharField(max_length=10, choices=BirdSale.SALE_TYPE_CHOICES, default='customer')
    customer = models.ForeignKey('sales.Customer', on_delete=models.PROTECT, null=True, blank=True,
                                 related_name='bird_sale_receipts')
    farmer = models.ForeignKey(Farmer, on_delete=models.PROTECT, null=True, blank=True,
                               related_name='bird_sale_receipts')

    mode = models.CharField(max_length=20, choices=MODE_CHOICES, default='Cash')
    receipt_account = models.ForeignKey('account.ChartOfAccount', on_delete=models.PROTECT,
                                        related_name='bird_sale_receipts')
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    reference_no = models.CharField(max_length=100, blank=True)
    remarks = models.CharField(max_length=255, blank=True)

    entry_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='broiler_bird_sale_receipts')
    entry_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Bird Sale Receipt")
        verbose_name_plural = _("Bird Sale Receipts")
        ordering = ['-date', '-id']

    def __str__(self):
        return self.receipt_no

    def clean(self):
        if self.sale_type == 'customer' and not self.customer_id:
            raise ValidationError("Customer is required for a Customer receipt.")
        if self.sale_type == 'farmer' and not self.farmer_id:
            raise ValidationError("Farmer is required for a Farmer receipt.")

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.receipt_no:
            self.receipt_no = self._next_receipt_no(self.date)
            super().save(update_fields=["receipt_no"])

    @classmethod
    def _next_receipt_no(cls, on_date=None):
        current_date = on_date or now().date()
        start_year = current_date.year if current_date.month >= 4 else current_date.year - 1
        fy = f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"
        prefix = f"RC-{fy}-"
        max_num = 0
        for existing in cls.objects.filter(receipt_no__startswith=prefix).values_list("receipt_no", flat=True):
            match = re.match(rf"^{re.escape(prefix)}(\d+)$", existing or "")
            if match:
                max_num = max(max_num, int(match.group(1)))
        return f"{prefix}{max_num + 1:04d}"

    @staticmethod
    def balance_due(location_id, sale_type, customer_id, farmer_id, exclude_id=None):
        """Total sold to this buyer minus total received from them, rolled
        up across every Farm/Location sharing the given Location's Branch
        (a cost centre has no direct Farm link, only a shared Branch)."""
        from inventory.models import Warehouse
        if not location_id or not (customer_id or farmer_id):
            return 0
        location = Warehouse.objects.filter(id=location_id).first()
        if not location or not location.branch_id:
            return 0
        branch_id = location.branch_id
        buyer_filter = {"farmer_id": farmer_id} if sale_type == 'farmer' else {"customer_id": customer_id}
        total_sold = (BirdSale.objects.filter(farm__branch_id=branch_id, sale_type=sale_type, **buyer_filter)
                      .aggregate(total=models.Sum('amount'))['total'] or 0)
        receipts = BirdSaleReceipt.objects.filter(location__branch_id=branch_id, sale_type=sale_type, **buyer_filter)
        if exclude_id:
            receipts = receipts.exclude(id=exclude_id)
        total_received = receipts.aggregate(total=models.Sum('amount'))['total'] or 0
        return total_sold - total_received


class GrowingChargeScheme(models.Model):
    """
    Rearing / Growing Charge scheme master, modelled field-for-field on the
    "Rearing Charge" screen: a header (region/branch/validity/schema name), the
    Standard Growing Charge block, and the incentive / decentive / shortage /
    FCR-recovery / farmer-classification rules captured as nested rows.
    """

    class MedicineCostBasis(models.TextChoices):
        ACTUAL = 'actual', _('Actual')
        MASTER = 'master', _('Master')
        FIXED = 'fixed', _('Fixed')

    class ShortageBasis(models.TextChoices):
        STD_PRODUCTION_COST = 'std_production_cost', _('Std Production Cost')
        PRODUCTION_COST = 'production_cost', _('Production Cost')
        AVG_SALE_RATE = 'avg_sale_rate', _('Avg. Sale Rate')
        MAX_SALE_RATE = 'max_sale_rate', _('Max. Sale Rate')
        WHICH_IS_HIGHER = 'which_is_higher', _('Which is Higher')

    scheme_code = models.CharField(
        max_length=20, unique=True, editable=False, blank=True,
        help_text=_("Auto-generated code, e.g. GCS-0001")
    )
    # --- Header ---
    region = models.ForeignKey(
        Region, on_delete=models.PROTECT, related_name='growing_charge_schemes',
        help_text=_("Region this scheme applies to")
    )
    branch = models.ForeignKey(
        Branch, on_delete=models.PROTECT, related_name='growing_charge_schemes',
        blank=True, null=True, help_text=_("Branch; blank = all branches")
    )
    from_date = models.DateField(help_text=_("Applicable from date"))
    to_date = models.DateField(help_text=_("Applicable to date"))
    schema_name = models.CharField(max_length=150, help_text=_("Scheme / schema name"))

    # --- Standard Growing Charge ---
    chick_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    feed_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    medicine_cost_basis = models.CharField(
        max_length=10, choices=MedicineCostBasis.choices, default=MedicineCostBasis.ACTUAL
    )
    medicine_cost = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text=_("Fixed medicine cost value (used when basis = Fixed)")
    )
    farmer_admin_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    management_admin_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    std_production_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    standard_gc_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    minimum_gc_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    standard_fcr = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    standard_mortality = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unloading_charges = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # --- Sales Incentives (single fields alongside the rows) ---
    maximum_prod_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    maximum_rate_incentive = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # --- Mortality Decentives (single header fields above the rows) ---
    mort_dec_first_week_exceeds = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    mort_dec_overall_above = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    mort_dec_first_week_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # --- Shortage ---
    shortage_basis = models.CharField(
        max_length=20, choices=ShortageBasis.choices, default=ShortageBasis.WHICH_IS_HIGHER,
        help_text=_("Which value is used for shortage recovery")
    )

    is_active = models.BooleanField(default=True)
    is_locked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Growing Charge Scheme")
        verbose_name_plural = _("Growing Charge Schemes")
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.scheme_code} - {self.schema_name}"

    def clean(self):
        if self.from_date and self.to_date and self.to_date < self.from_date:
            raise ValidationError({'to_date': _("'To Date' can't be before 'From Date'.")})

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.scheme_code:
            self.scheme_code = f"GCS-{self.pk:04d}"
            super().save(update_fields=['scheme_code'])


class GCProductionCostIncentive(models.Model):
    """Production Cost Incentives row: From/To Production Cost + Rate %."""
    scheme = models.ForeignKey(GrowingChargeScheme, on_delete=models.CASCADE, related_name='production_cost_incentives')
    from_production_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    to_production_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    rate_pct = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ['id']


class GCSalesIncentive(models.Model):
    """Sales Incentives row: Sale Rate From/To + Sales Incentive."""
    scheme = models.ForeignKey(GrowingChargeScheme, on_delete=models.CASCADE, related_name='sales_incentives')
    sale_rate_from = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sale_rate_to = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sales_incentive = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ['id']


class GCMortalityIncentive(models.Model):
    """Mortality Incentives row: From/To Mortality % + Incentive Value."""
    scheme = models.ForeignKey(GrowingChargeScheme, on_delete=models.CASCADE, related_name='mortality_incentives')
    from_mortality_pct = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    to_mortality_pct = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    incentive_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ['id']


class GCFCRIncentive(models.Model):
    """FCR Incentives row: CFCR Limit + Body Weight + Incentive Value."""
    scheme = models.ForeignKey(GrowingChargeScheme, on_delete=models.CASCADE, related_name='fcr_incentives')
    cfcr_limit = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    body_weight = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    incentive_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ['id']


class GCSummerIncentive(models.Model):
    """Summer Incentives row: Min/Max Production Cost, Incentive On, From/To Production Cost, Incentive Rate."""

    class IncentiveOn(models.TextChoices):
        SOLD_BIRDS = 'sold_birds', _('Sold Birds')
        PLACED_BIRDS = 'placed_birds', _('Placed Birds')
        LIVE_BIRDS = 'live_birds', _('Live Birds')

    scheme = models.ForeignKey(GrowingChargeScheme, on_delete=models.CASCADE, related_name='summer_incentives')
    min_production_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    max_production_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    incentive_on = models.CharField(max_length=15, choices=IncentiveOn.choices, default=IncentiveOn.SOLD_BIRDS)
    from_production_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    to_production_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    incentive_rate = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ['id']


class GCProductionCostDecentive(models.Model):
    """Production Cost Decentives row: From/To Production Cost + Rate %."""
    scheme = models.ForeignKey(GrowingChargeScheme, on_delete=models.CASCADE, related_name='production_cost_decentives')
    from_production_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    to_production_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    rate_pct = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ['id']


class GCMortalityDecentive(models.Model):
    """Mortality Decentives row: From/To Mortality % + Decentive Value."""
    scheme = models.ForeignKey(GrowingChargeScheme, on_delete=models.CASCADE, related_name='mortality_decentives')
    from_mortality_pct = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    to_mortality_pct = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    decentive_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ['id']


class GCFCRRecovery(models.Model):
    """FCR Recovery row: CFCR Limit + Production Limit + Recovery Rate."""
    scheme = models.ForeignKey(GrowingChargeScheme, on_delete=models.CASCADE, related_name='fcr_recoveries')
    cfcr_limit = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    production_limit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    recovery_rate = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ['id']


class GCFarmerClassification(models.Model):
    """Farmer Classifications row: Production Cost From/To + Grade."""
    scheme = models.ForeignKey(GrowingChargeScheme, on_delete=models.CASCADE, related_name='farmer_classifications')
    production_cost_from = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    production_to = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    grade = models.CharField(max_length=5, blank=True)

    class Meta:
        ordering = ['id']


class GrowingChargeSettlement(models.Model):
    """Farmer Growing Charge settlement / batch-closing transaction — the
    "Add Rearing Charges" screen. One per Batch (closing it). Auto-loaded from
    the batch's real records + the applicable scheme's slabs, then persisted as
    a permanent snapshot of every figure shown on the form. Does NOT post to
    accounting (deferred); it does close the batch (BroilerBatch.is_closed)."""

    _M = dict(max_digits=14, decimal_places=2, default=0)   # money / weight
    _P = dict(max_digits=8, decimal_places=2, default=0)    # percentages
    _R = dict(max_digits=8, decimal_places=3, default=0)    # ratios (FCR/CFCR)

    settlement_code = models.CharField(max_length=20, unique=True, editable=False, blank=True,
                                       help_text=_("Auto-generated, e.g. GCST-0001"))
    batch = models.OneToOneField(BroilerBatch, on_delete=models.CASCADE, related_name='gc_settlement')
    farm = models.ForeignKey(BroilerFarm, on_delete=models.PROTECT, related_name='gc_settlements')
    scheme = models.ForeignKey(GrowingChargeScheme, on_delete=models.PROTECT, null=True, blank=True,
                               related_name='settlements')

    gc_date = models.DateField(default=now)
    placement_date = models.DateField(null=True, blank=True)
    liquidation_date = models.DateField(null=True, blank=True)

    # --- Bird details ---
    placed_birds = models.IntegerField(default=0)
    mortality = models.IntegerField(default=0)
    sold_birds = models.IntegerField(default=0)
    sold_weight = models.DecimalField(**_M)
    excess = models.IntegerField(default=0)
    shortage = models.IntegerField(default=0)
    sale_amount = models.DecimalField(**_M)
    sale_rate = models.DecimalField(**_M)
    age = models.DecimalField(**_P)

    # --- Performance ---
    first_week_mortality_pct = models.DecimalField(**_P)
    days30_mortality_pct = models.DecimalField(**_P)
    after30_mortality_pct = models.DecimalField(**_P)
    total_mortality_pct = models.DecimalField(**_P)
    fcr = models.DecimalField(**_R)
    cfcr = models.DecimalField(**_R)
    avg_weight = models.DecimalField(**_M)
    mean_age = models.DecimalField(**_P)
    day_gain = models.DecimalField(**_M)
    eef = models.DecimalField(**_M)
    grade = models.CharField(max_length=5, blank=True)

    # --- Feed / medicine details (KGS; bags derived at display) ---
    feed_in = models.DecimalField(**_M)
    feed_consumption = models.DecimalField(**_M)
    feed_out = models.DecimalField(**_M)
    feed_balance = models.DecimalField(**_M)
    med_transfer_in = models.DecimalField(**_M)
    med_consumption = models.DecimalField(**_M)
    med_transfer_out = models.DecimalField(**_M)
    med_closing = models.DecimalField(**_M)

    # --- Costing (amount + per-unit) ---
    chick_cost = models.DecimalField(**_M)
    chick_cost_per_unit = models.DecimalField(**_M)
    feed_cost = models.DecimalField(**_M)
    feed_cost_per_unit = models.DecimalField(**_M)
    admin_cost = models.DecimalField(**_M)
    admin_cost_per_unit = models.DecimalField(**_M)
    medicine_cost = models.DecimalField(**_M)
    medicine_cost_per_unit = models.DecimalField(**_M)
    total_cost = models.DecimalField(**_M)
    total_cost_per_unit = models.DecimalField(**_M)
    standard_production_cost = models.DecimalField(**_M)
    actual_production_cost = models.DecimalField(**_M)

    # --- Rearing charges (incentives) ---
    standard_growing_charges = models.DecimalField(**_M)
    gc_incentive_decentive = models.DecimalField(**_M)   # Standard + this = Actual
    actual_growing_charges = models.DecimalField(**_M)
    gc_paid_per_kg = models.DecimalField(**_M)
    sales_incentives = models.DecimalField(**_M)
    mortality_incentives = models.DecimalField(**_M)
    fcr_incentives = models.DecimalField(**_M)
    summer_incentives = models.DecimalField(**_M)
    other_incentives = models.DecimalField(**_M)
    ifft_charges = models.DecimalField(**_M)
    total_incentives = models.DecimalField(**_M)

    # --- Decentives (deductions) ---
    birds_shortage_rate = models.DecimalField(**_M)
    birds_shortage_amount = models.DecimalField(**_M)
    fcr_deduction = models.DecimalField(**_M)
    mortality_deduction = models.DecimalField(**_M)
    total_deduction = models.DecimalField(**_M)
    amount_payable = models.DecimalField(**_M)
    farmer_sales_deduction = models.DecimalField(**_M)
    feed_transfer_charges = models.DecimalField(**_M)
    vaccinator_charges = models.DecimalField(**_M)
    transportation_charges = models.DecimalField(**_M)
    other_deductions = models.DecimalField(**_M)
    total_amount_payable = models.DecimalField(**_M)
    tds = models.DecimalField(**_M)
    equipment_charges = models.DecimalField(**_M)
    advance_deductions = models.DecimalField(**_M)
    farmer_payable = models.DecimalField(**_M)
    per_bird_cost = models.DecimalField(**_M)
    remarks = models.TextField(blank=True)

    created_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='gc_settlements_created')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Growing Charge Settlement")
        verbose_name_plural = _("Growing Charge Settlements")
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.settlement_code} - {self.batch}"

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.settlement_code:
            self.settlement_code = f"GCST-{self.pk:04d}"
            super().save(update_fields=['settlement_code'])
