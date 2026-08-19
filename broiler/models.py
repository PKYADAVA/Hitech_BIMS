import re
from decimal import ROUND_HALF_UP, Decimal

from django.db import models
from django.core.validators import RegexValidator, MinValueValidator, MaxValueValidator
from django.utils.translation import gettext_lazy as _
from django.utils.timezone import now
from django.core.exceptions import ValidationError
import os

from Hitech_BIMS.storage_backends import private_media_storage


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
    bird_category = models.ForeignKey(
        'BirdCategory', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='breeds', help_text=_("Bird category this breed belongs to")
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
    #: Where the branch office is. The Farm Map & Route Planner starts a
    #: supervisor's day here — "Head Office" on the route — so a branch with
    #: no pin cannot be a starting point and the planner says so rather than
    #: routing from (0, 0), which is in the Atlantic.
    latitude = models.FloatField(
        blank=True, null=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
        help_text=_("Latitude of the branch office"))
    longitude = models.FloatField(
        blank=True, null=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
        help_text=_("Longitude of the branch office"))
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
    employee = models.OneToOneField(
        'hr.Employee',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='broiler_supervisor_role',
        help_text=_("HR employee record this supervisor is (one-to-one) — name/phone/address are copied from here")
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
        storage=private_media_storage,
        blank=True,
        null=True,
        help_text=_("Uploaded copy of PAN card")
    )
    aadhar_upload_front = models.FileField(
        upload_to='farmer/aadhar/',
        storage=private_media_storage,
        blank=True,
        null=True,
        help_text=_("Uploaded copy of Aadhar card (front)")
    )
    aadhar_upload_back = models.FileField(
        upload_to='farmer/aadhar/',
        storage=private_media_storage,
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
    status = models.CharField(
        max_length=12, default="active", blank=True,
        choices=[("active", "Active"), ("inactive", "Inactive")],
        help_text=_("Whether this farmer is currently dealt with"))

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
    #: How good the reading was, in metres, and when it was taken. A pin is
    #: only as trustworthy as its accuracy: a fix good to 2 km will route a
    #: supervisor to the wrong village, and one taken two years ago may point
    #: at a shed that has since moved. Both are filled from the latest Farm
    #: Location Capture (see FarmLocationCapture.sync_farm_from_latest) rather
    #: than typed, so there is one place a coordinate comes from.
    gps_accuracy = models.FloatField(
        blank=True, null=True,
        validators=[MinValueValidator(0)],
        help_text=_("Accuracy of the GPS reading, in metres"))
    location_captured_at = models.DateField(
        blank=True, null=True,
        help_text=_("Date of the location capture this pin came from"))
    location_verified = models.BooleanField(
        default=False,
        help_text=_("Somebody has confirmed this pin is where the farm is"))
    #: What the Route Planner does with the farm when the route is being
    #: ordered by priority rather than by distance alone. Normal is the
    #: default and the ordinary case; the other two pull a farm earlier in the
    #: day at some cost in kilometres.
    PRIORITY_NORMAL, PRIORITY_HIGH, PRIORITY_CRITICAL = "normal", "high", "critical"
    VISIT_PRIORITY_CHOICES = [
        (PRIORITY_NORMAL, _("Normal")),
        (PRIORITY_HIGH, _("High")),
        (PRIORITY_CRITICAL, _("Critical")),
    ]
    visit_priority = models.CharField(
        max_length=10, choices=VISIT_PRIORITY_CHOICES, default=PRIORITY_NORMAL,
        db_index=True,
        help_text=_("How urgently this farm needs to be visited"))
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
        storage=private_media_storage,
        blank=True,
        null=True,
        help_text=_("Uploaded copy of the agreement")
    )
    other_documents = models.FileField(
        upload_to='farm/documents/',
        storage=private_media_storage,
        blank=True,
        null=True,
        help_text=_("Other supporting documents")
    )
    # Facts the Farm Report asks for that the master did not hold. Kept
    # optional: they are surveyed on a visit, not known when a farm is first
    # entered, so a farm with blanks here is normal rather than incomplete.
    own_or_lease = models.CharField(
        max_length=10, blank=True,
        choices=[("own", "Own"), ("lease", "Lease")],
        help_text=_("Whether the farmer owns the land or leases it"))
    water_ph = models.DecimalField(
        max_digits=4, decimal_places=2, null=True, blank=True,
        help_text=_("Water pH from the last test"))
    water_tds = models.PositiveIntegerField(
        null=True, blank=True, help_text=_("Water TDS in ppm from the last test"))
    farm_status = models.CharField(
        max_length=12, default="active", blank=True,
        choices=[("active", "Active"), ("inactive", "Inactive"),
                 ("closed", "Closed")],
        help_text=_("Whether the farm is currently in use"))

    farm_sqft = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text=_("Farm area in square feet")
    )
    cheque_1_no = models.CharField(max_length=30, blank=True, help_text=_("Security cheque 1 number"))
    cheque_1_file = models.FileField(upload_to='farm/cheques/', storage=private_media_storage, blank=True, null=True, help_text=_("Security cheque 1 scan"))
    cheque_2_no = models.CharField(max_length=30, blank=True, help_text=_("Security cheque 2 number"))
    cheque_2_file = models.FileField(upload_to='farm/cheques/', storage=private_media_storage, blank=True, null=True, help_text=_("Security cheque 2 scan"))
    cheque_3_no = models.CharField(max_length=30, blank=True, help_text=_("Security cheque 3 number"))
    cheque_3_file = models.FileField(upload_to='farm/cheques/', storage=private_media_storage, blank=True, null=True, help_text=_("Security cheque 3 scan"))
    cheque_4_no = models.CharField(max_length=30, blank=True, help_text=_("Security cheque 4 number"))
    cheque_4_file = models.FileField(upload_to='farm/cheques/', storage=private_media_storage, blank=True, null=True, help_text=_("Security cheque 4 scan"))
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
    Represents a shed within a broiler farm (Broiler > Master > Farm Shed).
    Organization Centre / Branch / Company are auto-derived from the farm.
    """

    SHED_TYPE_CHOICES = [
        ("broiler", _("Broiler")),
        ("breeder", _("Breeder")),
        ("layer", _("Layer")),
        ("grower", _("Grower")),
        ("quarantine", _("Quarantine")),
    ]

    farm = models.ForeignKey(
        BroilerFarm,
        on_delete=models.CASCADE,
        related_name='sheds',
        help_text=_("Farm this shed belongs to")
    )
    shed_code = models.CharField(
        max_length=30, unique=True, editable=False, blank=True,
        help_text=_("Auto-generated code, e.g. SHED-0001")
    )
    shed_name = models.CharField(
        max_length=100, blank=True,
        help_text=_("Descriptive name of the shed")
    )
    shed_type = models.CharField(
        max_length=20, choices=SHED_TYPE_CHOICES, default="broiler",
        help_text=_("Type of shed")
    )
    unit_no = models.PositiveIntegerField(
        default=0, editable=False,
        help_text=_("Auto-assigned running unit number within the farm (1,2,3…)")
    )
    organization_centre = models.ForeignKey(
        'account.OrganizationCentre', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='farm_sheds',
        help_text=_("Cost/Organization Centre — auto-set from the farm's branch")
    )
    is_active = models.BooleanField(default=True)

    shed_no = models.CharField(
        max_length=50, blank=True,
        help_text=_("Legacy shed number/identifier")
    )
    length = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        help_text=_("Shed length in feet")
    )
    width = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        help_text=_("Shed width in feet")
    )
    dimensions = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text=_("Auto-composed 'L x W ft' from length & width")
    )
    sq_feet = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text=_("Auto-calculated area (length x width) in square feet")
    )
    capacity = models.PositiveIntegerField(
        default=0, help_text=_("Bird holding capacity of the shed")
    )
    occupied = models.PositiveIntegerField(
        default=0, help_text=_("Birds currently housed in the shed")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def free_space(self):
        return max(self.capacity - self.occupied, 0)

    @property
    def utilization_pct(self):
        return round(self.occupied / self.capacity * 100) if self.capacity else 0

    class Meta:
        verbose_name = _("Broiler Farm Shed")
        verbose_name_plural = _("Broiler Farm Sheds")
        ordering = ['farm__farm_code', 'unit_no', 'shed_no']

    def __str__(self):
        return f"{self.shed_code or self.shed_name or self.shed_no} ({self.farm.farm_name})"

    @staticmethod
    def _next_shed_code():
        prefix = "SHED-"
        max_num = 0
        for code in (BroilerFarmShed.objects
                     .filter(shed_code__startswith=prefix)
                     .values_list("shed_code", flat=True)):
            m = re.match(rf"^{re.escape(prefix)}(\d+)$", code or "")
            if m:
                max_num = max(max_num, int(m.group(1)))
        return f"{prefix}{max_num + 1:04d}"

    def save(self, *args, **kwargs):
        if not self.shed_code:
            self.shed_code = self._next_shed_code()
        if not self.unit_no:
            existing = (BroilerFarmShed.objects.filter(farm=self.farm)
                        .exclude(pk=self.pk).aggregate(m=models.Max("unit_no"))["m"] or 0)
            self.unit_no = existing + 1
        # Shed name defaults to "<Farm Name> Shed <unit no>" but stays editable —
        # only auto-filled when left blank.
        if self.farm_id and not (self.shed_name or "").strip():
            self.shed_name = f"{self.farm.farm_name} Shed {self.unit_no}"
        if self.shed_name:
            self.shed_no = self.shed_name
        # Auto-derive the cost/organization centre from the farm's branch.
        if self.farm_id and not self.organization_centre_id:
            from account.models import OrganizationCentre
            self.organization_centre = (OrganizationCentre.objects
                                        .filter(branch_id=self.farm.branch_id).first())
        # Status is occupancy-driven: a shed is Active once chicks are placed in
        # it (occupied > 0), otherwise inactive/vacant. Occupied itself is filled
        # from chicks placement, so Status follows automatically.
        self.is_active = (self.occupied or 0) > 0
        # Auto-calculate area & dimension string from length x width.
        if self.length and self.width:
            def _fmt(v):
                v = Decimal(str(v))
                return str(v.quantize(Decimal("1")) if v == v.to_integral_value() else v.normalize())
            area = (Decimal(str(self.length)) * Decimal(str(self.width)))
            self.sq_feet = _fmt(area)
            self.dimensions = f"{_fmt(self.length)} x {_fmt(self.width)} ft"
        super().save(*args, **kwargs)


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
    shed = models.ForeignKey(
        BroilerFarmShed,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='broiler_batches',
        help_text=_("Shed / unit within the farm this batch is housed in")
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
    breed = models.ForeignKey(
        'Breed',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='batches',
        help_text=_("Breed of this flock — used for standard performance comparison"),
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

    # Field-capture attachments & geo-tag — populated by the mobile app when a
    # supervisor records the day at the farm; optional (blank until captured).
    mort_image = models.ImageField(upload_to='daily_entry/mort/', null=True, blank=True,
                                   help_text="Photo evidence of the day's mortality")
    cull_image = models.ImageField(upload_to='daily_entry/cull/', null=True, blank=True,
                                   help_text="Photo evidence of the day's culls")
    feed_image = models.ImageField(upload_to='daily_entry/feed/', null=True, blank=True,
                                   help_text="Photo of feed stock/consumption")
    entry_latitude = models.FloatField(null=True, blank=True,
                                       help_text="GPS latitude where the entry was recorded")
    entry_longitude = models.FloatField(null=True, blank=True,
                                        help_text="GPS longitude where the entry was recorded")

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

    def feed_shortfalls(self):
        """Feed this entry would take that the farm does not have.

        ``[(item, wanted, available)]`` — empty when the entry fits inside what
        has been delivered. Both slots are weighed together against the same
        balance: a day that puts one feed through Primary and Optional has
        taken the sum of the two out of one pile, and checking them separately
        let a farm feed twice what it held.

        ``previous_stock`` is the balance *available to this row* — it already
        leaves out the row's own consumption, so editing a saved entry is
        measured against the stock without it rather than failing on itself.
        """
        if not self.farm_id or not self.date:
            return []
        wanted = {}
        for slot in ("feed_1", "feed_2"):
            item_id = getattr(self, f"{slot}_id")
            qty = Decimal(str(getattr(self, f"{slot}_qty") or 0))
            if item_id and qty > 0:
                wanted[item_id] = wanted.get(item_id, Decimal("0")) + qty

        short = []
        for item_id, qty in wanted.items():
            available = Decimal(str(
                self.previous_stock(self.farm_id, item_id, self.date, self.pk)))
            if qty > available:
                item = self.feed_1 if self.feed_1_id == item_id else self.feed_2
                short.append((item, qty, available))
        return short

    def clean(self):
        """Refuse an entry that feeds more than the farm has been sent.

        The Stock column has shown the shortfall for a while; it was still
        possible to save through it, and the balance then carried the error
        forward into every later entry on that farm — which is how a feed
        ledger ends up reading minus twenty-five kilograms.
        """
        super().clean()
        short = self.feed_shortfalls()
        if short:
            raise ValidationError({
                "feed_1_qty": [
                    "%s: only %s kg is at this farm on %s, and this entry feeds %s."
                    % (item, available, self.date.strftime("%d.%m.%Y") if self.date else "",
                       qty)
                    for item, qty, available in short
                ]
            })

    @staticmethod
    def previous_stock(farm_id, item_id, before_date, before_id):
        """Feed of this item at this farm, before this row is counted.

        What has been delivered, less what earlier entries have already fed.
        It used to chain from an opening balance of zero, reading only prior
        daily entries — so a farm with 2,337 kg of Starter delivered showed 0,
        and the column drifted further negative every day it was fed. What it
        displayed was cumulative consumption with a minus sign, not a balance.

        ``before_id`` is the row's own pk when editing an existing entry (so
        same-date rows saved after it are correctly excluded); it's None for
        a brand-new row, which has no id yet to compare against, so any
        same-date row already saved earlier in the same submission still
        counts as "previous" — restricting to date alone is correct there.
        """
        if not item_id:
            return 0
        from inventory.services.item_summary import farm_receipts_balance

        if before_id:
            date_filter = models.Q(date__lt=before_date) | (models.Q(date=before_date) & models.Q(id__lt=before_id))
        else:
            date_filter = models.Q(date__lte=before_date)
        used = Decimal("0")
        for row in DailyEntry.objects.filter(farm_id=farm_id).filter(date_filter):
            if row.feed_1_id == item_id:
                used += row.feed_1_qty or 0
            if row.feed_2_id == item_id:
                used += row.feed_2_qty or 0
        return farm_receipts_balance(farm_id, item_id, before_date) - used


class DailyEntryPhoto(models.Model):
    """Photo evidence attached to a Daily Entry — several per category.

    ``DailyEntry`` carries one ``mort_image`` / ``cull_image`` / ``feed_image``
    each, which is one picture per category and no more. A bad mortality day is
    not one photograph, so the extras live here, keyed by which category they
    evidence.

    The single fields on ``DailyEntry`` are kept, not replaced: every saved
    entry already populates them and both Day Record reports render them. The
    first photo of a category is mirrored into its legacy field (see ``save``),
    so existing records and existing reports carry on working untouched while
    the phone uploads as many as it needs.
    """

    KIND_MORTALITY = "mortality"
    KIND_CULLS = "culls"
    KIND_FEED = "feed"
    #: The second feed slot photographs separately. A day can be fed two
    #: different feeds and one picture cannot evidence both.
    KIND_FEED_2 = "feed_2"
    KIND_CHOICES = [
        (KIND_MORTALITY, _("Mortality")),
        (KIND_CULLS, _("Culls")),
        (KIND_FEED, _("Feed")),
        (KIND_FEED_2, _("Feed 2")),
    ]

    #: Cap per entry per category. Field photos travel over rural mobile data,
    #: and an uncapped set is how a save stops finishing at all.
    MAX_PER_KIND = 5

    #: Which single field on the parent each category's first photo mirrors
    #: into. KIND_FEED_2 is absent on purpose: the parent carries one
    #: ``feed_image`` and mirroring the second slot into it would overwrite the
    #: evidence for the first. ``save`` already returns for an unmapped kind.
    LEGACY_FIELD = {
        KIND_MORTALITY: "mort_image",
        KIND_CULLS: "cull_image",
        KIND_FEED: "feed_image",
    }

    entry = models.ForeignKey(
        DailyEntry, on_delete=models.CASCADE, related_name="photos",
        help_text=_("Daily Entry this photo evidences"),
    )
    kind = models.CharField(
        max_length=20, choices=KIND_CHOICES,
        help_text=_("What the photo is evidence of"),
    )
    image = models.ImageField(
        upload_to="daily_entry/photos/%Y/%m/",
        help_text=_("The photograph"),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Daily Entry Photo")
        verbose_name_plural = _("Daily Entry Photos")
        ordering = ["kind", "id"]
        indexes = [models.Index(fields=["entry", "kind"])]

    def __str__(self):
        return f"{self.entry.entry_no} — {self.get_kind_display()}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Mirror into the parent's single field when that field is still empty,
        # so the Day Record reports keep showing a thumbnail without knowing
        # this table exists. Written with .update() rather than entry.save():
        # re-saving the parent would re-run its entry-number logic for nothing.
        field = self.LEGACY_FIELD.get(self.kind)
        if not field:
            return
        parent = DailyEntry.objects.filter(pk=self.entry_id).values_list(field, flat=True).first()
        if not parent:
            DailyEntry.objects.filter(pk=self.entry_id).update(**{field: self.image.name})


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
        """Medicine of this item at this farm, before this row is counted.

        Same correction as DailyEntry.previous_stock, and for the same reason:
        it chained from zero over prior entries, so what a farm had actually
        been sent never entered the figure. See the note there.
        """
        if not item_id:
            return 0
        from inventory.services.item_summary import farm_medicine_balance

        if before_id:
            date_filter = models.Q(date__lt=before_date) | (models.Q(date=before_date) & models.Q(id__lt=before_id))
        else:
            date_filter = models.Q(date__lte=before_date)
        used = (MedicineVaccineEntry.objects
                .filter(farm_id=farm_id, item_id=item_id).filter(date_filter)
                .aggregate(total=models.Sum("qty"))["total"] or Decimal("0"))
        return farm_medicine_balance(farm_id, item_id, before_date) - used


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
    round_off = models.DecimalField(max_digits=8, decimal_places=2, default=0, editable=False,
                                    help_text="What rounding the total to the rupee added or took off")
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False,
                                 help_text="Net weight x Rate, rounded to the rupee")

    # The person who supervised the lifting/weighment — any employee (branch
    # manager, line supervisor, accountant, weighment operator, etc.), not
    # restricted to the broiler Supervisor master.
    lifting_supervisor = models.ForeignKey('hr.Employee', on_delete=models.SET_NULL, null=True, blank=True,
                                           related_name='lifting_bird_sales')
    vehicle = models.CharField(max_length=50, blank=True)
    driver = models.CharField(max_length=100, blank=True)
    remarks = models.CharField(max_length=255, blank=True)

    # Where the lifting was weighed, stamped by the phone that recorded it.
    # Nullable and never required by the model: the same sale is also raised at
    # a desk from a slip brought back from the field, and that desk has no GPS.
    # The phone form asks for it because the phone is standing there.
    lift_latitude = models.FloatField(null=True, blank=True,
                                      help_text="GPS latitude where the lifting was recorded")
    lift_longitude = models.FloatField(null=True, blank=True,
                                       help_text="GPS longitude where the lifting was recorded")
    lift_place = models.CharField(max_length=200, blank=True,
                                  help_text="Human-readable place for the GPS pin")

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
        # Round off is derived, not typed. A lifting is billed to the rupee, so
        # the paise fall off the total and `round_off` records what that cost
        # or gained — it used to be an editable box the user filled in, which
        # made the same weighment come to a different figure depending on who
        # entered it.
        # Coerced rather than used as they arrive: `or 0` hands back a plain
        # int for an empty weight, and a form posts these as strings.
        raw = Decimal(str(self.net_weight or 0)) * Decimal(str(self.rate or 0))
        self.amount = raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        self.round_off = self.amount - raw
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

    @property
    def has_location(self):
        return self.lift_latitude is not None and self.lift_longitude is not None


class BirdSalePhoto(models.Model):
    """Photo evidence of a lifting — the truck, the birds, the weighbridge slip.

    A lifting is the one broiler transaction nobody at the desk witnesses: the
    birds leave the farm, and what the branch is billed for is whatever the
    slip says. These are the pictures that make the slip checkable, so they are
    taken on site by the phone raising the sale.

    Modelled as rows rather than three fields on ``BirdSale`` for the same
    reason as ``DailyEntryPhoto``: a lifting is often more than one truckload
    and more than one weighment, and a fixed field can hold exactly one of
    each. ``kind`` says what a picture shows; ``KIND_OTHER`` carries the
    "Add More" ones that evidence nothing in particular.
    """

    KIND_TRUCK = "truck"
    KIND_BIRDS = "birds"
    KIND_WEIGHBRIDGE = "weighbridge"
    KIND_OTHER = "other"
    KIND_CHOICES = [
        (KIND_TRUCK, _("Truck Photo")),
        (KIND_BIRDS, _("Birds Photo")),
        (KIND_WEIGHBRIDGE, _("Weighbridge Slip")),
        (KIND_OTHER, _("Other")),
    ]

    #: The three a lifting is expected to carry, in the order the form asks.
    REQUIRED_KINDS = [KIND_TRUCK, KIND_BIRDS, KIND_WEIGHBRIDGE]

    #: Cap per sale per kind — field photos travel over rural mobile data, and
    #: an uncapped set is how a save stops finishing at all.
    MAX_PER_KIND = 5

    sale = models.ForeignKey(BirdSale, on_delete=models.CASCADE, related_name="photos",
                             help_text=_("Bird Sale this photo evidences"))
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default=KIND_OTHER,
                            help_text=_("What the photo shows"))
    image = models.ImageField(upload_to="bird_sale/photos/%Y/%m/",
                              help_text=_("The photograph"))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Bird Sale Photo")
        verbose_name_plural = _("Bird Sale Photos")
        ordering = ["kind", "id"]
        indexes = [models.Index(fields=["sale", "kind"])]

    def __str__(self):
        return f"{self.sale.sale_no} - {self.get_kind_display()}"

    def delete(self, *args, **kwargs):
        # Drop the file with the row. A cascade from the sale skips this, which
        # is why the register's Delete goes through the model rather than a
        # bulk queryset delete.
        image = self.image
        super().delete(*args, **kwargs)
        if image:
            image.storage.delete(image.name)


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
    # Distinct from medicine_cost above, which is only meaningful when
    # medicine_cost_basis is "Fixed" and otherwise sits at its unused default
    # of 0 — every scheme in practice runs Actual or Master basis, so that
    # field carries no real number for most schemes. This one is what the
    # Standard column of the GC Realization Report always shows for medicine
    # cost per bird, independent of whichever basis this scheme runs.
    standard_medicine_cost = models.DecimalField(
        max_digits=12, decimal_places=2, default=3,
        help_text=_("Standard medicine cost per bird shown on the GC Realization "
                    "Report's Standard column — read regardless of Medicine Cost Basis.")
    )
    # Same reasoning as standard_medicine_cost just above: the Breed Standard
    # curve gives an age-matched body weight, but the GC Realization Report's
    # Standard column wants one flat number for the scheme, editable in place
    # on that report — not dependent on this batch's breed having a curve row
    # at exactly this age.
    standard_avg_weight = models.DecimalField(
        max_digits=12, decimal_places=2, default=2,
        help_text=_("Standard avg. live weight per bird (kg) shown on the GC "
                    "Realization Report's Standard column.")
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


class FeedPhaseMaster(models.Model):
    """Header for a feeding program (Broiler > Master > Feed Phase Master):
    a program for a bird type / breed, valid over an effective window, with a
    set of feed-phase line items (Pre-Starter, Starter, Grower, Finisher…)."""

    STATUS_CHOICES = [("active", _("Active")), ("inactive", _("Inactive"))]

    program = models.CharField(max_length=100, help_text=_("Feeding program name, e.g. Cobb 430 Standard"))
    bird_category = models.ForeignKey('BirdCategory', on_delete=models.SET_NULL, null=True, blank=True,
                                      related_name='feed_phase_masters',
                                      help_text=_("Bird category this program is for"))
    breed = models.ForeignKey('Breed', on_delete=models.SET_NULL, null=True, blank=True,
                              related_name='feed_phase_masters')
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="active")
    description = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Feed Phase Master")
        verbose_name_plural = _("Feed Phase Masters")
        ordering = ['-created_at']

    def __str__(self):
        cat = self.bird_category.name if self.bird_category_id else "—"
        return f"{self.program} ({cat})"

    @property
    def is_active(self):
        return self.status == "active"


class FeedPhaseLine(models.Model):
    """One feed-phase row within a Feed Phase Master."""
    master = models.ForeignKey(FeedPhaseMaster, on_delete=models.CASCADE, related_name='lines')
    seq_no = models.PositiveIntegerField(default=1)
    from_age = models.PositiveIntegerField(default=0, help_text=_("From age in days"))
    to_age = models.PositiveIntegerField(null=True, blank=True,
                                         help_text=_("To age in days — leave blank for 'and above' (open-ended)"))
    category = models.ForeignKey('inventory.ItemCategory', on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='feed_phase_lines',
                                 help_text=_("Item category — filters the feed item choices"))
    feed_item = models.ForeignKey('inventory.Item', on_delete=models.PROTECT, null=True, blank=True,
                                  related_name='feed_phase_lines',
                                  help_text=_("Item (of the selected category) for this phase"))
    phase_code = models.CharField(max_length=20, blank=True, help_text=_("e.g. PS, ST, GR, FN1"))
    max_feed_qty = models.DecimalField(max_digits=12, decimal_places=3, default=0,
                                       help_text=_("Max feed per bird for this phase, in Kg"))
    priority = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=10, choices=FeedPhaseMaster.STATUS_CHOICES, default="active")

    class Meta:
        verbose_name = _("Feed Phase Line")
        verbose_name_plural = _("Feed Phase Lines")
        ordering = ['seq_no', 'id']

    def __str__(self):
        name = self.feed_item.description if self.feed_item_id else "Feed"
        span = f"{self.from_age}+" if self.to_age is None else f"{self.from_age}-{self.to_age}"
        return f"{name} ({span}d)"

    @property
    def is_active(self):
        return self.status == "active"


class BirdCategory(models.Model):
    """Bird category master (Broiler > Growing Charges) — e.g. Broiler, Layer,
    Breeder, Parent Stock, etc. Simple lookup used to classify birds/flocks."""
    name = models.CharField(max_length=100, unique=True, help_text=_("Category name, e.g. Broiler"))
    sort_order = models.PositiveIntegerField(default=0, help_text=_("Display order"))
    is_active = models.BooleanField(default=True, help_text=_("Inactive categories are hidden from selection"))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Bird Category")
        verbose_name_plural = _("Bird Categories")
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name


class FarmLocationCapture(models.Model):
    """A dated visit that records where a farm is and what it looks like —
    Broiler > Transactions > Farm Location & Photos.

    The farm master keeps only the *current* location and picture set. This is
    the trail behind it: who captured what, when. Saving writes the latest
    capture through to the farm (see ``sync_farm``), so the master always shows
    the most recent visit while older captures stay for reference.

    The farmer is not stored again — it is read from ``farm.farmer``, so a farm
    changing hands can never leave a capture pointing at the wrong person.
    """

    capture_no = models.CharField(
        max_length=30, unique=True, editable=False, blank=True,
        help_text=_("Auto-generated, e.g. FLC-2627-0001"))
    date = models.DateField(default=now)
    farm = models.ForeignKey(
        BroilerFarm, on_delete=models.CASCADE, related_name="location_captures",
        help_text=_("Farm this capture belongs to; the farmer comes from it"))
    latitude = models.FloatField(
        null=True, blank=True, validators=[MinValueValidator(-90), MaxValueValidator(90)],
        help_text=_("Decimal degrees, -90 to 90"))
    longitude = models.FloatField(
        null=True, blank=True, validators=[MinValueValidator(-180), MaxValueValidator(180)],
        help_text=_("Decimal degrees, -180 to 180"))
    gps_accuracy = models.FloatField(
        blank=True, null=True,
        validators=[MinValueValidator(0)],
        help_text=_("Accuracy of the reading in metres, as the phone reported it"))
    state = models.CharField(max_length=100, blank=True)
    district = models.CharField(max_length=100, blank=True)
    area = models.CharField(max_length=100, blank=True)
    address = models.TextField(blank=True, help_text=_("Address as found on the visit"))
    remarks = models.TextField(blank=True)
    captured_by = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name="farm_location_captures")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Farm Location Capture")
        verbose_name_plural = _("Farm Location Captures")
        ordering = ["-date", "-id"]

    def __str__(self):
        return self.capture_no or f"(unsaved capture for {self.farm})"

    @property
    def farmer(self):
        """Read through to the farm's farmer rather than storing a second copy."""
        return self.farm.farmer if self.farm_id else None

    @property
    def has_location(self):
        return self.latitude is not None and self.longitude is not None

    def clean(self):
        # Half a coordinate pair is worse than none: it looks like a location
        # but cannot be plotted, and would overwrite a good one on the farm.
        if (self.latitude is None) != (self.longitude is None):
            raise ValidationError(_("Enter both latitude and longitude, or neither."))

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.capture_no:
            self.capture_no = self._next_no(self.date)
            super().save(update_fields=["capture_no"])
        self.sync_farm()

    def delete(self, *args, **kwargs):
        farm = self.farm
        # Delete the files one by one rather than letting the cascade take them:
        # a cascade is a bulk delete, so FarmCaptureFile.delete() never runs and
        # the mirrored farm pictures would be orphaned and the master documents
        # left pointing at this capture's files.
        for attachment in list(self.files.all()):
            attachment.delete()
        super().delete(*args, **kwargs)
        # The farm should fall back to whatever capture is now the latest.
        FarmLocationCapture.sync_farm_from_latest(farm)

    @classmethod
    def _next_no(cls, on_date=None):
        current_date = on_date or now().date()
        start_year = current_date.year if current_date.month >= 4 else current_date.year - 1
        fy = f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"
        prefix = f"FLC-{fy}-"
        max_num = 0
        for existing in cls.objects.filter(capture_no__startswith=prefix).values_list("capture_no", flat=True):
            match = re.match(rf"^{re.escape(prefix)}(\d+)$", existing or "")
            if match:
                max_num = max(max_num, int(match.group(1)))
        return f"{prefix}{max_num + 1:04d}"

    def sync_farm(self):
        """Push this capture onto the farm master — but only if it is the
        latest one, so editing an old visit cannot undo a newer reading."""
        FarmLocationCapture.sync_farm_from_latest(self.farm)

    @staticmethod
    def sync_farm_from_latest(farm):
        """Set the farm's current location from its most recent capture that
        has one. With no captures left the farm keeps what was typed on the
        master directly — this only ever overwrites with a real reading."""
        if farm is None:
            return
        latest = (FarmLocationCapture.objects
                  .filter(farm=farm, latitude__isnull=False, longitude__isnull=False)
                  .order_by("-date", "-id").first())
        if latest is None:
            return
        fields = []
        if farm.farm_latitude != latest.latitude:
            farm.farm_latitude = latest.latitude
            fields.append("farm_latitude")
        if farm.farm_longitude != latest.longitude:
            farm.farm_longitude = latest.longitude
            fields.append("farm_longitude")
        # How good the reading was and when it was taken travel with it. The
        # Route Planner shows both against the pin, because a fix good to two
        # kilometres routes somebody to the wrong village and a two-year-old
        # one may point at a shed that has moved.
        if farm.gps_accuracy != latest.gps_accuracy:
            farm.gps_accuracy = latest.gps_accuracy
            fields.append("gps_accuracy")
        if farm.location_captured_at != latest.date:
            farm.location_captured_at = latest.date
            fields.append("location_captured_at")
        # The written parts only overwrite when the capture actually has them —
        # a visit that recorded a pin but no address must not wipe the master's.
        for capture_field, farm_field in (("address", "farm_address"),
                                          ("state", "state"),
                                          ("district", "district"),
                                          ("area", "area")):
            value = getattr(latest, capture_field)
            if value and getattr(farm, farm_field) != value:
                setattr(farm, farm_field, value)
                fields.append(farm_field)
        if fields:
            farm.save(update_fields=fields)


class FarmCaptureFile(models.Model):
    """One photo or document attached to a location capture.

    Photos are mirrored into BroilerFarmImage so they show up on the farm
    master exactly like pictures uploaded there directly; the mirror is removed
    again when the file is cleared or the capture deleted.
    """

    KIND_PHOTO = "photo"
    KIND_DOCUMENT = "document"
    KIND_CHOICES = [
        (KIND_PHOTO, _("Farm Picture")),
        ("farmer_photo", _("Farmer Photo")),
        ("pan", _("PAN Card")),
        ("aadhar_front", _("Aadhar (Front)")),
        ("aadhar_back", _("Aadhar (Back)")),
        ("agreement", _("Agreement Copy")),
        ("cheque_1", _("Security Cheque 1")),
        ("cheque_2", _("Security Cheque 2")),
        ("cheque_3", _("Security Cheque 3")),
        ("cheque_4", _("Security Cheque 4")),
        (KIND_DOCUMENT, _("Other Document")),
    ]

    # Where each slot lands on the masters. "farmer"/"farm" says which record,
    # then the field on it. Farm pictures are the odd one out: many are allowed,
    # so they mirror into BroilerFarmImage instead of overwriting one field.
    SLOT_TARGETS = {
        "farmer_photo": ("farmer", "farmer_photo"),
        "pan": ("farmer", "pan_upload"),
        "aadhar_front": ("farmer", "aadhar_upload_front"),
        "aadhar_back": ("farmer", "aadhar_upload_back"),
        "agreement": ("farm", "agreement_copy"),
        "cheque_1": ("farm", "cheque_1_file"),
        "cheque_2": ("farm", "cheque_2_file"),
        "cheque_3": ("farm", "cheque_3_file"),
        "cheque_4": ("farm", "cheque_4_file"),
        KIND_DOCUMENT: ("farm", "other_documents"),
    }

    capture = models.ForeignKey(
        FarmLocationCapture, on_delete=models.CASCADE, related_name="files")
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default=KIND_PHOTO)
    # Mirrors farm KYC/cheque/document scans (see FILE_MAP above), so it lives
    # in private storage with signed URLs.
    file = models.FileField(upload_to="farm/captures/%Y/%m/", storage=private_media_storage)
    caption = models.CharField(max_length=150, blank=True)
    # The mirrored farm picture, so clearing a capture can take it back out.
    farm_image = models.OneToOneField(
        BroilerFarmImage, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="capture_file", editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Farm Capture File")
        verbose_name_plural = _("Farm Capture Files")
        ordering = ["id"]

    def __str__(self):
        return f"{self.get_kind_display()} for {self.capture}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.kind == self.KIND_PHOTO and self.farm_image_id is None and self.file:
            image = BroilerFarmImage.objects.create(
                farm=self.capture.farm, image=self.file.name)
            FarmCaptureFile.objects.filter(pk=self.pk).update(farm_image=image)
            self.farm_image_id = image.pk
        FarmCaptureFile.sync_slot(self.capture, self.kind)

    def delete(self, *args, **kwargs):
        image = self.farm_image
        capture, kind = self.capture, self.kind
        super().delete(*args, **kwargs)
        if image is not None:
            image.delete()
        FarmCaptureFile.sync_slot(capture, kind)

    @staticmethod
    def sync_slot(capture, kind):
        """Point the master's field at the newest capture that filled this slot.

        Same rule as the location: the master shows the latest visit, so editing
        or deleting an older capture cannot disturb it. With no captures left
        holding this slot the master keeps whatever it already had — a file
        uploaded on the master directly is never blanked from here.
        """
        target = FarmCaptureFile.SLOT_TARGETS.get(kind)
        if target is None or capture is None or capture.farm_id is None:
            return
        owner_kind, field = target
        owner = capture.farm.farmer if owner_kind == "farmer" else capture.farm
        if owner is None:
            return
        latest = (FarmCaptureFile.objects
                  .filter(capture__farm_id=capture.farm_id, kind=kind)
                  .exclude(file="")
                  .order_by("-capture__date", "-capture__id", "-id").first())
        if latest is None or not latest.file:
            return
        if getattr(owner, field) != latest.file.name:
            setattr(owner, field, latest.file.name)
            owner.save(update_fields=[field])


class FarmerFarmSetupRequest(models.Model):
    """A field supervisor's on-site submission to create a brand-new Farmer +
    BroilerFarm — Broiler > Transactions > Farmer & Farm Setup Request.

    This is a staging record, not a master: the GPS pin, KYC scans and shed
    details captured here describe a farm that does not exist in the system
    yet. Nothing here is real until a reviewer approves it — only then does
    :meth:`approve` create the actual ``Farmer``/``BroilerFarm``/
    ``BroilerFarmShed`` rows, mirroring the same "share the stored file,
    don't duplicate the bytes" approach ``FarmCaptureFile.sync_slot`` already
    uses for KYC scans elsewhere in this file.

    Kept deliberately separate from ``hatchery.ChangeRequest``: that model
    requires an existing ``object_id`` to attach an edit/delete to, and has
    nowhere to stage files pending approval — neither fits "there is no row
    yet, and there are half a dozen documents attached to the row that
    doesn't exist yet."
    """

    SHED_TYPES = [
        ("open", _("Open Shed")),
        ("closed", _("Closed Shed")),
        ("ec", _("Environmental Controlled")),
    ]

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        PENDING = "pending", _("Pending")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")

    request_no = models.CharField(
        max_length=30, unique=True, editable=False, blank=True,
        help_text=_("Auto-generated, e.g. FFR-2627-0001"))
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.DRAFT)
    branch = models.ForeignKey(
        Branch, on_delete=models.PROTECT,
        related_name='farmer_farm_setup_requests',
        help_text=_("Branch this request was raised for; drives numbering and who can review it"))
    supervisor = models.ForeignKey(
        Supervisor, on_delete=models.PROTECT, null=True, blank=True,
        related_name='farmer_farm_setup_requests',
        help_text=_("Who takes ownership of the farm on approval; required to submit, not to draft"))

    # --- workflow / audit --------------------------------------------------
    submitted_by = models.ForeignKey(
        'auth.User', on_delete=models.PROTECT,
        related_name='farmer_farm_setup_requests_submitted')
    submitted_at = models.DateTimeField(null=True, blank=True,
        help_text=_("Set when the request moves from Draft to Pending"))
    reviewed_by = models.ForeignKey(
        'auth.User', on_delete=models.PROTECT, null=True, blank=True,
        related_name='farmer_farm_setup_requests_reviewed')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    # SET_NULL, not PROTECT: this is only a backward pointer for the audit
    # trail ("this request became that record"). The request keeps its own
    # captured data regardless, so a master-data cleanup deleting the Farmer
    # or Farm it produced must not be blocked by a request from months ago —
    # it only loses the link, not the history.
    created_farmer = models.ForeignKey(
        Farmer, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='setup_requests',
        help_text=_("Set on approval — the real Farmer this request became"))
    created_farm = models.ForeignKey(
        BroilerFarm, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='setup_requests',
        help_text=_("Set on approval — the real BroilerFarm this request became"))

    # --- 1. Farm Location & GPS --------------------------------------------
    latitude = models.FloatField(
        null=True, blank=True, validators=[MinValueValidator(-90), MaxValueValidator(90)])
    longitude = models.FloatField(
        null=True, blank=True, validators=[MinValueValidator(-180), MaxValueValidator(180)])
    gps_accuracy_m = models.FloatField(null=True, blank=True)
    gps_captured_at = models.DateTimeField(null=True, blank=True)
    state = models.CharField(max_length=100, blank=True)
    district = models.CharField(max_length=100, blank=True)
    village_area = models.CharField(max_length=100, blank=True)
    # Free text, matching BroilerFarm.line's own convention — not FK to
    # BroilerLine, so a request reads the same way the farm it becomes will.
    line = models.CharField(max_length=100, blank=True)
    full_address = models.TextField(blank=True)

    # --- 2. Farmer Profile & Contact ---------------------------------------
    # blank=True here (and on every other "required-looking" field below)
    # even though the mockup marks them with an asterisk: a Draft is allowed
    # to be genuinely incomplete, so nothing here is enforced by full_clean.
    # REQUIRED_FOR_SUBMIT below is what actually enforces the asterisks, and
    # only at the point of submit() — the one place "incomplete" must stop
    # meaning something.
    farmer_name = models.CharField(max_length=150, blank=True)
    father_spouse_name = models.CharField(max_length=150, blank=True)
    primary_mobile = models.CharField(max_length=15, blank=True)
    whatsapp_number = models.CharField(max_length=15, blank=True)
    alternate_mobile = models.CharField(max_length=15, blank=True)
    email = models.EmailField(blank=True)
    # Where the farmer actually lives — distinct from full_address (the
    # farm's own GPS-captured location in Section 1); the two are often not
    # the same place, so approve() no longer falls back to one for the other
    # once this has something in it.
    farmer_address = models.TextField(blank=True)
    farmer_photo = models.ImageField(upload_to='farmer_farm_requests/photos/', blank=True, null=True)

    # --- 3. Farm & Shed Details ---------------------------------------------
    farm_name = models.CharField(max_length=100, blank=True)
    farm_type = models.CharField(
        max_length=50, choices=BroilerFarm.FARM_TYPES, default='own')
    farmer_group = models.ForeignKey(
        FarmerGroup, on_delete=models.PROTECT, null=True, blank=True,
        related_name='farmer_farm_setup_requests')
    capacity_birds = models.PositiveIntegerField(null=True, blank=True)
    shed_type = models.CharField(max_length=10, choices=SHED_TYPES, default="open")
    remarks = models.TextField(blank=True)

    # --- 4. KYC & Documents --------------------------------------------------
    aadhaar_number = models.CharField(max_length=12, blank=True)
    pan_card = models.CharField(max_length=10, blank=True)
    pan_upload = models.FileField(
        upload_to='farmer_farm_requests/kyc/', storage=private_media_storage, blank=True, null=True)
    aadhaar_front = models.FileField(
        upload_to='farmer_farm_requests/kyc/', storage=private_media_storage, blank=True, null=True)
    aadhaar_back = models.FileField(
        upload_to='farmer_farm_requests/kyc/', storage=private_media_storage, blank=True, null=True)
    agreement_copy = models.FileField(
        upload_to='farmer_farm_requests/kyc/', storage=private_media_storage, blank=True, null=True)
    security_cheque = models.FileField(
        upload_to='farmer_farm_requests/kyc/', storage=private_media_storage, blank=True, null=True)
    physically_verified = models.BooleanField(
        default=False,
        help_text=_("Field supervisor confirms the farmer, farm location and basic farm details have been physically verified"))

    # --- 5. Bank Details (optional; not enforced by REQUIRED_FOR_SUBMIT) ----
    # Same names as Farmer's own bank fields, so approve() can pass them
    # straight across without a translation table.
    account_holder_name = models.CharField(max_length=150, blank=True)
    acc_no = models.CharField(max_length=30, blank=True)
    ifsc_code = models.CharField(max_length=15, blank=True)
    bank_name = models.CharField(max_length=100, blank=True)
    bank_branch = models.CharField(max_length=100, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Farmer & Farm Setup Request")
        verbose_name_plural = _("Farmer & Farm Setup Requests")
        ordering = ["-created_at"]

    def __str__(self):
        return self.request_no or f"(unsaved request for {self.farmer_name})"

    @classmethod
    def next_request_no(cls, on_date=None):
        """FY-scoped, same shape as FarmLocationCapture._next_no — e.g. the
        1st request of FY2026-27 is FFR-2627-0001."""
        current_date = on_date or now().date()
        start_year = current_date.year if current_date.month >= 4 else current_date.year - 1
        fy = f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"
        prefix = f"FFR-{fy}-"
        max_num = 0
        for existing in cls.objects.filter(request_no__startswith=prefix).values_list("request_no", flat=True):
            match = re.match(rf"^{re.escape(prefix)}(\d+)$", existing or "")
            if match:
                max_num = max(max_num, int(match.group(1)))
        return f"{prefix}{max_num + 1:04d}"

    def save(self, *args, **kwargs):
        if self._state.adding and not self.request_no:
            self.request_no = self.next_request_no()
        super().save(*args, **kwargs)

    #: (field, label) pairs the mockup marks with a red asterisk — enforced
    #: only here, at the draft->pending transition, not by full_clean on
    #: every save (a draft is allowed to be genuinely incomplete).
    REQUIRED_FOR_SUBMIT = [
        ("state", _("State")), ("district", _("District")), ("line", _("Line / Route")),
        ("village_area", _("Village / Area")), ("full_address", _("Full Farm Address")),
        ("farmer_name", _("Farmer Name")), ("primary_mobile", _("Primary Mobile")),
        ("farmer_photo", _("Farmer Photo")), ("supervisor", _("Supervisor")),
        ("farm_name", _("Farm Name")), ("capacity_birds", _("Capacity (Birds)")),
    ]

    def submit(self):
        """Draft -> Pending: the point this enters the review queue."""
        if self.status != self.Status.DRAFT:
            raise ValidationError(_("Only a draft can be submitted for approval."))
        missing = [str(label) for field, label in self.REQUIRED_FOR_SUBMIT if not getattr(self, field)]
        if not self.physically_verified:
            missing.append(str(_("Physical verification confirmation")))
        if not self.sheds.exists():
            missing.append(str(_("At least one Shed row")))
        if missing:
            raise ValidationError(
                _("Fill in before submitting: %(fields)s") % {"fields": ", ".join(missing)})
        self.status = self.Status.PENDING
        self.submitted_at = now()
        self.save(update_fields=["status", "submitted_at", "updated_at"])

    def reject(self, reviewer, note=""):
        if self.status != self.Status.PENDING:
            raise ValidationError(_("Only a pending request can be rejected."))
        self.status = self.Status.REJECTED
        self.reviewed_by = reviewer
        self.reviewed_at = now()
        self.review_note = note
        self.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note", "updated_at"])

    def approve(self, reviewer, note=""):
        """Creates the real Farmer + BroilerFarm + shed rows, then shares
        (not copies) each uploaded file onto its matching master field — the
        same convention FarmCaptureFile.sync_slot already uses, since both
        this model's files and the masters' KYC fields sit on the same
        private storage backend."""
        if self.status != self.Status.PENDING:
            raise ValidationError(_("Only a pending request can be approved."))
        from django.db import transaction
        with transaction.atomic():
            farmer = Farmer(
                farmer_name=self.farmer_name,
                mobile_no=self.primary_mobile,
                mobile_2=self.whatsapp_number or self.alternate_mobile,
                pan_no=self.pan_card,
                aadhar_no=self.aadhaar_number,
                farmer_group=self.farmer_group,
                address=self.farmer_address or self.full_address,
                account_holder_name=self.account_holder_name,
                acc_no=self.acc_no,
                ifsc_code=self.ifsc_code,
                bank_name=self.bank_name,
                bank_branch=self.bank_branch,
            )
            if self.farmer_photo:
                farmer.farmer_photo = self.farmer_photo.name
            if self.aadhaar_front:
                farmer.aadhar_upload_front = self.aadhaar_front.name
            if self.aadhaar_back:
                farmer.aadhar_upload_back = self.aadhaar_back.name
            if self.pan_upload:
                farmer.pan_upload = self.pan_upload.name
            # farmer_group is nullable but not blank=True on Farmer itself (a
            # pre-existing quirk of that model) — excluded here too, since
            # it's genuinely optional on this request (no asterisk in the
            # mockup) and a request without one must still be approvable.
            farmer.full_clean(exclude=["farmer_photo", "aadhar_upload_front", "aadhar_upload_back",
                                       "pan_upload", "farmer_group"])
            farmer.save()

            # submit() already refused to queue this without one — Supervisor
            # is picked by the field supervisor themselves now, not guessed
            # from the branch's own records.
            if self.supervisor_id is None:
                raise ValidationError(_("This request has no Supervisor set."))

            farm = BroilerFarm(
                branch=self.branch,
                supervisor=self.supervisor,
                farmer=farmer,
                region=self.state,
                line=self.line,
                farm_name=self.farm_name or self.farmer_name,
                farm_capacity=self.capacity_birds or 0,
                farm_type=self.farm_type,
                state=self.state,
                district=self.district,
                area=self.village_area,
                farm_address=self.full_address,
                farm_latitude=self.latitude,
                farm_longitude=self.longitude,
                remarks=self.remarks,
            )
            if self.agreement_copy:
                farm.agreement_copy = self.agreement_copy.name
            if self.security_cheque:
                farm.cheque_1_file = self.security_cheque.name
            farm.full_clean(exclude=["farm_code", "agreement_copy", "other_documents",
                                     "cheque_1_file", "cheque_2_file", "cheque_3_file", "cheque_4_file"])
            farm.save()

            shed_rows = list(self.sheds.all())
            sheds = max(len(shed_rows), 1)
            per_shed_capacity = (self.capacity_birds or 0) // sheds
            shed_type_label = dict(self.SHED_TYPES).get(self.shed_type, self.shed_type)
            for i, row in enumerate(shed_rows or [None]):
                # BroilerFarmShed.shed_type is a different axis (bird type:
                # broiler/breeder/layer/…) from this request's shed_type
                # (construction: open/closed/EC) — left at its own default
                # rather than force-mapped; the construction type is folded
                # into the shed name instead, since the model has no field
                # for it.
                BroilerFarmShed.objects.create(
                    farm=farm,
                    shed_name=f"{shed_type_label} Shed {i + 1}",
                    capacity=per_shed_capacity,
                    length=row.length if row else None,
                    width=row.width if row else None,
                )

            self.status = self.Status.APPROVED
            self.reviewed_by = reviewer
            self.reviewed_at = now()
            self.review_note = note
            self.created_farmer = farmer
            self.created_farm = farm
            self.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note",
                                     "created_farmer", "created_farm", "updated_at"])
        return farmer, farm


class FarmerFarmSetupRequestShed(models.Model):
    """One prospective shed row on a Farmer & Farm Setup Request — its own
    dimensions, added/removed on the form the same way Farm Location &
    Photos' picture rows are. Becomes one real BroilerFarmShed per row on
    approval (see FarmerFarmSetupRequest.approve)."""

    request = models.ForeignKey(
        FarmerFarmSetupRequest, on_delete=models.CASCADE, related_name='sheds')
    length = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    width = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    class Meta:
        verbose_name = _("Farmer & Farm Setup Request Shed")
        verbose_name_plural = _("Farmer & Farm Setup Request Sheds")
        ordering = ["id"]

    def __str__(self):
        return f"{self.length or '?'} x {self.width or '?'} ft ({self.request_id})"

    @property
    def area_sqft(self):
        if self.length is None or self.width is None:
            return None
        return self.length * self.width


class FarmerFarmSetupRequestPhoto(models.Model):
    """One of any number of farm pictures attached to a request, added or
    removed on the form the same way the shed rows are.

    Kept as evidence for the reviewer only — unlike the KYC/master slots and
    the shed rows, nothing on BroilerFarm mirrors these; the farm itself has
    no photo gallery of its own to copy them onto."""

    request = models.ForeignKey(
        FarmerFarmSetupRequest, on_delete=models.CASCADE, related_name='photos')
    photo = models.ImageField(upload_to='farmer_farm_requests/photos/')

    class Meta:
        verbose_name = _("Farmer & Farm Setup Request Photo")
        verbose_name_plural = _("Farmer & Farm Setup Request Photos")
        ordering = ["id"]

    def __str__(self):
        return f"Photo for {self.request_id}"


class BatchOtherEntry(models.Model):
    """A cost or income the ERP has no transaction for, entered against a batch.

    Labour, electricity, depreciation, litter and manure sales: real money, and
    nothing in this system records them. Until each has a transaction of its
    own, the Production P&L would either omit them — making every flock look
    more profitable than it was — or wait for modules that may be a year away.

    So the report lets someone type them in. Deliberately narrow: one amount per
    head per batch, no dates, no ledger, no posting. It is a note on a statement,
    not an accounting entry, and it is stored where the statement can find it
    rather than pretending to be a voucher.

    Replaced by the real thing whenever a head gets a transaction behind it —
    at which point its rows here should be migrated, not left to double-count.
    """

    class Kind(models.TextChoices):
        COST = "cost", _("Cost")
        REVENUE = "revenue", _("Revenue")

    batch = models.ForeignKey(BroilerBatch, on_delete=models.CASCADE,
                              related_name="other_entries")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    #: The head as the report names it, e.g. "Labour". Free text rather than a
    #: choice field: the list lives in services/production_pl.py, and a second
    #: copy here would be one more thing to keep in step.
    head = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    entered_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL,
                                   null=True, blank=True,
                                   related_name='batch_other_entries')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Batch Other Entry")
        verbose_name_plural = _("Batch Other Entries")
        constraints = [
            models.UniqueConstraint(fields=["batch", "kind", "head"],
                                    name="uniq_batch_other_entry"),
        ]

    def __str__(self):
        return f"{self.batch} / {self.head}: {self.amount}"


def _route_today():
    """A callable default, so the date is the day a route is made rather than
    the day the process booted."""
    from django.utils.timezone import localdate
    return localdate()


def format_minutes(minutes):
    """Minutes as "6h 42m" — the one way a duration is written in this module,
    on the summary card, the visit list and the saved-route table alike."""
    minutes = int(minutes or 0)
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours}h {mins:02d}m"
    return f"{hours}h" if hours else f"{mins}m"


class FarmRoute(models.Model):
    """A planned round of farm visits: where it starts, which farms, in what
    order, and how far the road between them actually runs.

    The plan, not the journey. What actually happened is recorded on
    ``hr.SupervisorTrip`` and its visits, which already carry the odometer,
    the photographs and the GPS stamps — this is what those get compared
    against, and creating a trip from a route is what joins the two. A route
    with no trip is a plan nobody drove; a trip with no route is a day's work
    nobody planned. Both are legitimate, so neither side is mandatory.

    Distances and times are the road network's, from
    ``broiler.services.routing`` — never a straight line between two pins,
    which understates a hill road by half. Where the provider could not be
    reached the row says so in ``distance_basis`` rather than passing an
    estimate off as a measurement.
    """

    STATUS_DRAFT, STATUS_PLANNED, STATUS_STARTED = "draft", "planned", "started"
    STATUS_COMPLETED, STATUS_CANCELLED = "completed", "cancelled"
    STATUS_CHOICES = [
        (STATUS_DRAFT, _("Draft")),
        (STATUS_PLANNED, _("Planned")),
        (STATUS_STARTED, _("Started")),
        (STATUS_COMPLETED, _("Completed")),
        (STATUS_CANCELLED, _("Cancelled")),
    ]

    MODE_DISTANCE, MODE_TIME = "distance", "time"
    MODE_PRIORITY, MODE_SUPERVISOR = "priority", "supervisor"
    MODE_CHOICES = [
        (MODE_DISTANCE, _("Shortest Distance")),
        (MODE_TIME, _("Shortest Travel Time")),
        (MODE_PRIORITY, _("Priority Route")),
        (MODE_SUPERVISOR, _("Supervisor Daily Route")),
    ]

    #: How the kilometres were arrived at. "road" is a routing provider's
    #: answer and the only one anybody should settle a travel claim against;
    #: "straight" is the great-circle fallback used when no provider could be
    #: reached, kept visible so a screen can label it an estimate rather than
    #: quietly present it as a measurement.
    BASIS_ROAD, BASIS_STRAIGHT = "road", "straight"
    BASIS_CHOICES = [(BASIS_ROAD, _("Road network")),
                     (BASIS_STRAIGHT, _("Straight line (estimate)"))]

    route_no = models.CharField(max_length=40, unique=True, editable=False, blank=True)
    name = models.CharField(max_length=150, blank=True)
    date = models.DateField(default=_route_today)
    branch = models.ForeignKey("broiler.Branch", on_delete=models.PROTECT,
                               null=True, blank=True, related_name="farm_routes")
    supervisor = models.ForeignKey("broiler.Supervisor", on_delete=models.PROTECT,
                                   null=True, blank=True, related_name="farm_routes")

    #: Where the day begins and ends. Held as a label and a pin rather than a
    #: foreign key because a start point is not always a row in this ERP — it
    #: is a branch office, a warehouse, or wherever the supervisor slept.
    start_label = models.CharField(max_length=150, blank=True)
    start_latitude = models.FloatField(null=True, blank=True)
    start_longitude = models.FloatField(null=True, blank=True)
    end_label = models.CharField(max_length=150, blank=True)
    end_latitude = models.FloatField(null=True, blank=True)
    end_longitude = models.FloatField(null=True, blank=True)
    #: Most rounds come back to where they started, which is the difference
    #: between a 280 km day and a 140 km one.
    returns_to_start = models.BooleanField(default=True)

    mode = models.CharField(max_length=12, choices=MODE_CHOICES, default=MODE_DISTANCE)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES,
                              default=STATUS_DRAFT, db_index=True)
    distance_basis = models.CharField(max_length=10, choices=BASIS_CHOICES,
                                      default=BASIS_ROAD)
    provider = models.CharField(max_length=40, blank=True,
                                help_text=_("Routing provider that answered"))

    planned_distance_km = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    planned_minutes = models.PositiveIntegerField(default=0)
    #: The drawn line, as an encoded polyline or a list of points, exactly as
    #: the provider returned it. Stored so a saved route redraws without
    #: paying for the call again — see the caching note in the service.
    geometry = models.JSONField(null=True, blank=True)

    #: The trip this route was driven as, once somebody starts it. One route,
    #: one trip: re-planning a day makes a new route rather than rewriting the
    #: one whose journey is already recorded against it.
    trip = models.OneToOneField("hr.SupervisorTrip", on_delete=models.SET_NULL,
                                null=True, blank=True, related_name="planned_route")

    created_by = models.ForeignKey("auth.User", on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="farm_routes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["date", "supervisor"])]

    def __str__(self):
        return self.route_no or f"Route {self.pk}"

    def save(self, *args, **kwargs):
        if not self.route_no:
            self.route_no = self._next_route_no()
        super().save(*args, **kwargs)

    def _next_route_no(self):
        """RT-YYYYMMDD-NNNN, dated so a day's routes sort together.

        Tolerates a string date, as SupervisorTrip._next_no already does and
        for the same reason: Django only coerces a field on full_clean or on
        the way to the database, so anything assigning a date from JSON — an
        endpoint, an importer, a shell — reaches here with a str and would
        otherwise fail asking it for strftime.
        """
        on_date = self.date or _route_today()
        if isinstance(on_date, str):
            from django.utils.dateparse import parse_date
            on_date = parse_date(on_date) or _route_today()
        stamp = on_date.strftime("%Y%m%d")
        prefix = f"RT-{stamp}-"
        last = (FarmRoute.objects.filter(route_no__startswith=prefix)
                .order_by("-route_no").values_list("route_no", flat=True).first())
        nxt = int(last.rsplit("-", 1)[1]) + 1 if last else 1
        return f"{prefix}{nxt:04d}"

    @property
    def farm_count(self):
        return self.stops.filter(farm__isnull=False).count()

    @property
    def duration_label(self):
        """"6h 42m" — the way every screen in this module shows a duration."""
        return format_minutes(self.planned_minutes)


class FarmRouteStop(models.Model):
    """One call on a route, in the order the optimiser put it.

    ``farm`` is null for the start and the end, which are places rather than
    farms. The leg figures are *from the previous stop*, so the first row
    carries nothing and the cumulative columns are running totals — the shape
    the visit-sequence panel and the farm list both read straight off.
    """

    KIND_START, KIND_FARM, KIND_END = "start", "farm", "end"
    KIND_CHOICES = [(KIND_START, _("Start")), (KIND_FARM, _("Farm")),
                    (KIND_END, _("End"))]

    route = models.ForeignKey(FarmRoute, on_delete=models.CASCADE, related_name="stops")
    sequence = models.PositiveIntegerField()
    kind = models.CharField(max_length=6, choices=KIND_CHOICES, default=KIND_FARM)
    farm = models.ForeignKey("broiler.BroilerFarm", on_delete=models.PROTECT,
                             null=True, blank=True, related_name="route_stops")
    label = models.CharField(max_length=150, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    leg_distance_km = models.DecimalField(max_digits=9, decimal_places=2, default=0)
    leg_minutes = models.PositiveIntegerField(default=0)
    cumulative_distance_km = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cumulative_minutes = models.PositiveIntegerField(default=0)
    #: Why this stop sits where it does when the route was ordered by priority
    #: — the explanation section 14 asks for, so a route that is not the
    #: shortest can say what it traded the kilometres for.
    priority = models.CharField(max_length=10, blank=True)

    #: Filled when the round is actually driven, from the trip's own visit
    #: row. Kept here as well so planned and actual sit side by side without a
    #: join for every comparison the deviation report makes.
    visited_at = models.DateTimeField(null=True, blank=True)
    actual_sequence = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["route_id", "sequence"]
        constraints = [
            models.UniqueConstraint(fields=["route", "sequence"],
                                    name="uniq_route_stop_sequence"),
        ]

    def __str__(self):
        return f"{self.route_id}#{self.sequence} {self.label or self.farm_id}"

    @property
    def is_deviation(self):
        """True when the round reached this stop out of its planned turn."""
        return (self.actual_sequence is not None
                and self.actual_sequence != self.sequence)
