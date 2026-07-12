"""Editable SMS templates.

Each row is an admin-editable override of a catalogue template
(:mod:`notification.templates_catalog`). Storing templates in the database lets
operations staff adjust wording without a code deploy, while the code catalogue
remains the seed and the fallback.
"""

from django.db import models

from .constants import SMS_MODULE_CHOICES


class SmsTemplate(models.Model):
    """A configurable SMS message template scoped to an application module."""

    key = models.CharField(
        max_length=100,
        unique=True,
        help_text="Stable identifier used in code, e.g. 'user.otp'.",
    )
    module = models.CharField(
        max_length=30,
        choices=SMS_MODULE_CHOICES,
        db_index=True,
        help_text="Application module this template belongs to.",
    )
    name = models.CharField(max_length=150, help_text="Human-readable template name.")
    body = models.TextField(
        help_text="Message text. Use {placeholder} tokens, e.g. 'Your OTP is {otp}'.",
    )
    description = models.CharField(
        max_length=255,
        blank=True,
        help_text="What this template is used for.",
    )
    dlt_template_id = models.CharField(
        max_length=64,
        blank=True,
        help_text="DLT content template ID for this exact text (Indian traffic). "
                  "Overrides the global SMS_GATEWAYHUB_DLT_TEMPLATE_ID when set.",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Inactive templates fall back to the built-in default.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("module", "key")
        verbose_name = "SMS template"
        verbose_name_plural = "SMS templates"

    def __str__(self):
        return f"{self.key} ({self.get_module_display()})"
