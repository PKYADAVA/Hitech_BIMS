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
    transaction = models.CharField(
        max_length=50,
        blank=True,
        db_index=True,
        help_text="Sub-transaction within the module (see SMS_MODULE_TRANSACTIONS); "
                  "blank = generic template for the whole module.",
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
    category = models.CharField(
        max_length=30,
        default="general",
        db_index=True,
        help_text="Business category (invoice, dispatch, payment reminder, ...).",
    )
    sms_type = models.CharField(
        max_length=15,
        choices=[("transactional", "Transactional"), ("promotional", "Promotional")],
        default="transactional",
    )
    sender_id = models.CharField(
        max_length=10,
        blank=True,
        help_text="Overrides the global sender ID when set.",
    )
    created_by = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="created_sms_templates",
    )
    modified_by = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="modified_sms_templates",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("module", "key")
        verbose_name = "SMS template"
        verbose_name_plural = "SMS templates"

    def __str__(self):
        return f"{self.key} ({self.get_module_display()})"


class SmsTemplateCategory:
    """Business categories for templates (spec-driven; extend freely)."""
    CHOICES = [
        ("invoice", "Invoice"),
        ("purchase", "Purchase"),
        ("payment_reminder", "Payment Reminder"),
        ("outstanding", "Outstanding"),
        ("delivery", "Delivery"),
        ("dispatch", "Dispatch"),
        ("order_confirmation", "Order Confirmation"),
        ("receipt", "Receipt"),
        ("general", "General"),
        ("otp", "OTP"),
        ("custom", "Custom"),
    ]


class SmsMessage(models.Model):
    """Permanent log of every SMS the ERP attempts to send.

    One row per attempt (retries create linked rows). Rows are never deleted;
    there is deliberately no delete endpoint for this model.
    """

    STATUS_CHOICES = [
        ("queued", "Queued"),
        ("accepted", "Accepted"),
        ("sent", "Sent"),
        ("delivered", "Delivered"),
        ("failed", "Failed"),
        ("rejected", "Rejected"),
        ("expired", "Expired"),
        ("invalid", "Invalid"),
        ("disabled", "Disabled"),
        ("mocked", "Mocked"),
        ("unknown", "Unknown"),
    ]
    PARTY_TYPE_CHOICES = [("customer", "Customer"), ("supplier", "Supplier")]

    party_type = models.CharField(max_length=10, choices=PARTY_TYPE_CHOICES, blank=True)
    party_id = models.PositiveIntegerField(null=True, blank=True)
    party_name = models.CharField(max_length=255, blank=True)
    mobile = models.CharField(max_length=20)
    module = models.CharField(max_length=30, blank=True, help_text="Document source key, e.g. 'sales'.")
    document_no = models.CharField(max_length=50, blank=True)
    template = models.ForeignKey(SmsTemplate, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="messages")
    template_name = models.CharField(max_length=150, blank=True)
    message = models.TextField()
    char_count = models.PositiveIntegerField(default=0)
    sms_parts = models.PositiveIntegerField(default=1)
    is_unicode = models.BooleanField(default=False)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="queued", db_index=True)
    gateway_message_id = models.CharField(max_length=100, blank=True)
    gateway_status = models.CharField(max_length=50, blank=True)
    gateway_response = models.JSONField(null=True, blank=True)
    api_request = models.JSONField(null=True, blank=True, help_text="Sanitized request context (no secrets).")
    error_message = models.TextField(blank=True)
    retry_of = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="retries")
    retry_count = models.PositiveIntegerField(default=0)
    sent_by = models.ForeignKey("auth.User", on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="sms_messages")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    delivery_time = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ("-id",)
        indexes = [
            models.Index(fields=["mobile", "created_at"]),
            models.Index(fields=["module", "document_no"]),
        ]

    def __str__(self):
        return f"SMS to {self.mobile} ({self.status})"


class SmsSettings(models.Model):
    """Singleton runtime SMS configuration (SMS Settings master).

    Overrides the ``.env``/settings values so operators can manage SMS from
    the UI without server restarts. Blank text fields fall back to the
    environment value; the API key is stored only if entered here (otherwise
    the env key keeps being used).
    """

    enabled = models.BooleanField(default=False, help_text="Master switch for all SMS sending.")
    mock = models.BooleanField(default=True, help_text="Mock mode: log sends without hitting the gateway.")
    sender_id = models.CharField(max_length=10, blank=True, help_text="DLT-approved sender/header, e.g. HTFARM.")
    api_key = models.CharField(max_length=200, blank=True, help_text="SMSGatewayHub API key (blank = use .env).")
    entity_id = models.CharField(max_length=30, blank=True, help_text="DLT principal entity ID.")
    default_country_code = models.CharField(max_length=5, default="91")
    modified_by = models.ForeignKey("auth.User", on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="sms_settings_changes")
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "SMS Settings"
        verbose_name_plural = "SMS Settings"

    def __str__(self):
        return "SMS Settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        from django.conf import settings as dj

        obj, _created = cls.objects.get_or_create(pk=1, defaults={
            "enabled": bool(getattr(dj, "SMS_ENABLED", False)),
            "mock": bool(getattr(dj, "SMS_MOCK", False)),
            "sender_id": getattr(dj, "SMS_GATEWAYHUB_SENDER_ID", ""),
            "entity_id": getattr(dj, "SMS_GATEWAYHUB_ENTITY_ID", ""),
            "default_country_code": str(getattr(dj, "SMS_DEFAULT_COUNTRY_CODE", "91")),
        })
        return obj
