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

    def get_farm_count(self):
        """Returns the number of farms in this place."""
        return self.broilerfarm_set.count()


class BroilerFarm(models.Model):
    """
    Represents a broiler farm with its details and location.
    """
    FARM_TYPES = [
        ('commercial', _('Commercial')),
        ('contract', _('Contract')),
        ('own', _('Own')),
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
    broiler_place = models.ForeignKey(
        BroilerPlace, 
        on_delete=models.CASCADE,
        related_name='broiler_farms',
        help_text=_("Place where this farm is located")
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
    mobile_no = models.CharField(
        max_length=15,
        validators=[
            RegexValidator(
                regex=r'^\+?1?\d{9,15}$',
                message=_("Phone number must be entered in the format: '+999999999'. Up to 15 digits allowed.")
            )
        ],
        help_text=_("Contact number for the farm")
    )
    block_name = models.CharField(
        max_length=100,
        help_text=_("Block or area name within the place")
    )
    address = models.TextField(help_text=_("Detailed address of the farm"))
    farm_latitude = models.FloatField(
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
        help_text=_("Latitude coordinate of the farm")
    )
    farm_longitude = models.FloatField(
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
        help_text=_("Longitude coordinate of the farm")
    )
    farm_type = models.CharField(
        max_length=50,
        choices=FARM_TYPES,
        default='commercial',
        help_text=_("Type of farm operation")
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

