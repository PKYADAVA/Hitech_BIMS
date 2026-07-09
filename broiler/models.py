from django.db import models
from django.core.validators import RegexValidator, MinValueValidator, MaxValueValidator
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
import os


class Branch(models.Model):
    """
    Represents a branch location in the broiler management system.
    """
    state = models.CharField(
        max_length=100,
        help_text=_("State where the branch is located")
    )
    branch_name = models.CharField(
        max_length=100,
        unique=True,
        help_text=_("Name of the branch")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Branch")
        verbose_name_plural = _("Branches")
        ordering = ['state', 'branch_name']

    def __str__(self):
        return f"{self.branch_name} ({self.state})"

    def get_farm_count(self):
        """Returns the number of farms in this branch."""
        return self.broilerfarm_set.count()


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
    name = models.CharField(
        max_length=100,
        help_text=_("Full name of the supervisor")
    )
    phone_no = models.CharField(
        max_length=15,
        validators=[
            RegexValidator(
                regex=r'^\+?1?\d{9,15}$',
                message=_("Phone number must be entered in the format: '+999999999'. Up to 15 digits allowed.")
            )
        ],
        help_text=_("Contact number of the supervisor")
    )
    address = models.TextField(help_text=_("Residential address of the supervisor"))
    email = models.EmailField(blank=True, null=True, help_text=_("Email address of the supervisor"))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Supervisor")
        verbose_name_plural = _("Supervisors")
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.branch.branch_name})"

    def get_place_count(self):
        """Returns the number of places managed by this supervisor."""
        return self.broilerplace_set.count()


class BroilerPlace(models.Model):
    """
    Represents a location where broiler farms are situated.
    """
    supervisor = models.ForeignKey(
        Supervisor, 
        on_delete=models.CASCADE,
        related_name='broiler_places',
        help_text=_("Supervisor managing this place")
    )
    place_name = models.CharField(
        max_length=100,
        help_text=_("Name of the place")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Broiler Place")
        verbose_name_plural = _("Broiler Places")
        ordering = ['place_name']
        unique_together = ['supervisor', 'place_name']

    def __str__(self):
        return f"{self.place_name} ({self.supervisor.name})"


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
    farmer_group = models.CharField(
        max_length=100,
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
        help_text=_("Unique code for the farm")
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
        help_text=_("Agreement start date")
    )
    agreement_end_date = models.DateField(
        help_text=_("Agreement end date")
    )
    agreement_months = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text=_("Duration of the agreement in months")
    )
    agreement_copy = models.FileField(
        upload_to='farm/agreements/',
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
        help_text=_("Name or identifier for the batch")
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


class BroilerDisease(models.Model):
    """
    Represents a disease that can affect broiler batches.
    """
    batch = models.ForeignKey(
        BroilerBatch,
        on_delete=models.CASCADE,
        related_name='broiler_diseases',
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

