from django.db import models
from django.core.exceptions import ValidationError

from .bindable_fields import BINDABLE_FIELD_LOOKUP
from .sources import PICKLIST_SOURCE_MODELS


class Picklist(models.Model):
    """A named list of values other model fields can bind to."""

    class SourceType(models.TextChoices):
        STATIC = "STATIC", "Static List"
        MODEL = "MODEL", "From Another Master"

    key = models.SlugField(max_length=50, unique=True, help_text="Stable identifier used by field bindings")
    name = models.CharField(max_length=150, help_text="Display name, e.g. 'Party Category'")
    source_type = models.CharField(max_length=10, choices=SourceType.choices, default=SourceType.STATIC)
    source_model_key = models.CharField(
        max_length=50, blank=True,
        help_text="Key into PICKLIST_SOURCE_MODELS; required when source_type=MODEL",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def clean(self):
        if self.source_type == self.SourceType.MODEL:
            if not self.source_model_key:
                raise ValidationError("Select a source master for a model-sourced picklist.")
            if self.source_model_key not in PICKLIST_SOURCE_MODELS:
                raise ValidationError("Unknown source master.")
        else:
            self.source_model_key = ""

    @property
    def source_label(self):
        if self.source_type == self.SourceType.MODEL and self.source_model_key in PICKLIST_SOURCE_MODELS:
            return PICKLIST_SOURCE_MODELS[self.source_model_key]["label"]
        return ""


class PicklistValue(models.Model):
    """A single option in a STATIC picklist."""

    picklist = models.ForeignKey(Picklist, on_delete=models.CASCADE, related_name="values")
    value = models.CharField(max_length=100, help_text="Stored value")
    label = models.CharField(max_length=150, blank=True, help_text="Display label; defaults to value")
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "label", "id"]
        constraints = [
            models.UniqueConstraint(fields=["picklist", "value"], name="uniq_picklist_value"),
        ]

    def __str__(self):
        return self.label or self.value

    def save(self, *args, **kwargs):
        if not self.label:
            self.label = self.value
        super().save(*args, **kwargs)


class FieldPicklistBinding(models.Model):
    """Binds one bindable model field to free text or a Picklist."""

    class Mode(models.TextChoices):
        FREE_TEXT = "FREE_TEXT", "Free Text"
        PICKLIST = "PICKLIST", "Picklist"

    app_label = models.CharField(max_length=50)
    model_name = models.CharField(max_length=100)
    field_name = models.CharField(max_length=100)
    mode = models.CharField(max_length=10, choices=Mode.choices, default=Mode.FREE_TEXT)
    picklist = models.ForeignKey(
        Picklist, on_delete=models.SET_NULL, null=True, blank=True, related_name="bindings"
    )
    is_required = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["app_label", "model_name", "field_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["app_label", "model_name", "field_name"], name="uniq_field_binding"
            ),
        ]

    def __str__(self):
        return f"{self.app_label}.{self.model_name}.{self.field_name}"

    @property
    def human_label(self):
        return BINDABLE_FIELD_LOOKUP.get((self.app_label, self.model_name, self.field_name), str(self))

    def clean(self):
        key = (self.app_label, self.model_name, self.field_name)
        if key not in BINDABLE_FIELD_LOOKUP:
            raise ValidationError("This field is not registered as bindable. Add it to BINDABLE_FIELDS first.")
        if self.mode == self.Mode.PICKLIST and not self.picklist_id:
            raise ValidationError("Select a picklist when mode is Picklist.")
        if self.mode == self.Mode.FREE_TEXT:
            self.picklist = None
