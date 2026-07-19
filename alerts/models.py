"""Persistence layer: the alert feed and the immutable audit trail.

Two tables, two jobs:

* :class:`Alert` — a user-facing *notification* row (read/unread, severity,
  message). Denormalised for cheap listing and filtering.
* :class:`AuditLog` — an append-only forensic record of a single change,
  including full before/after snapshots. Guarded against edit/delete at the
  model level so history stays trustworthy.

Both reference the target object generically (model label + object id string)
rather than via ``GenericForeignKey`` so a row survives its target's deletion
and never needs the target's ContentType to still exist.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from .constants import Action, EventType, Severity


class AlertQuerySet(models.QuerySet):
    def unread(self) -> "AlertQuerySet":
        return self.filter(is_read=False)

    def for_user(self, user) -> "AlertQuerySet":
        """Alerts a given user is allowed to see (see permissions.scope_alerts)."""
        from .permissions import scope_alerts

        return scope_alerts(self, user)

    def with_related(self) -> "AlertQuerySet":
        """select_related to kill the N+1 on ``performed_by`` in list views."""
        return self.select_related("performed_by")


class Alert(models.Model):
    """A single notification in the alert feed."""

    # --- classification --------------------------------------------------
    event_type = models.CharField(max_length=64, db_index=True)
    action = models.CharField(max_length=32, choices=Action.choices, db_index=True)
    severity = models.CharField(
        max_length=16, choices=Severity.choices, default=Severity.INFO, db_index=True
    )

    # --- target ----------------------------------------------------------
    model_name = models.CharField(max_length=120, blank=True, db_index=True)
    object_id = models.CharField(max_length=64, blank=True, db_index=True)
    object_display = models.CharField(max_length=255, blank=True)

    # --- content ---------------------------------------------------------
    title = models.CharField(max_length=255)
    message = models.TextField(blank=True)

    # --- actor / environment --------------------------------------------
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="alerts_performed",
    )
    actor_label = models.CharField(max_length=150, blank=True)  # frozen username/system
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    browser = models.CharField(max_length=64, blank=True)
    device = models.CharField(max_length=64, blank=True)
    os = models.CharField(max_length=64, blank=True)
    session_id = models.CharField(max_length=64, blank=True)
    request_id = models.CharField(max_length=64, blank=True)

    # --- payload ---------------------------------------------------------
    changed_fields = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    # --- read state ------------------------------------------------------
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    objects = AlertQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["model_name", "object_id"]),
            models.Index(fields=["performed_by", "-created_at"]),
            models.Index(fields=["is_read", "-created_at"]),
        ]
        verbose_name = "Alert"
        verbose_name_plural = "Alerts"

    def __str__(self) -> str:
        return f"[{self.severity}] {self.title}"

    def mark_read(self, *, commit: bool = True) -> None:
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            if commit:
                self.save(update_fields=["is_read", "read_at"])


class AuditLog(models.Model):
    """Immutable before/after record of one change. Append-only by contract."""

    event_type = models.CharField(max_length=64, db_index=True)
    action = models.CharField(max_length=32, choices=Action.choices, db_index=True)

    model_name = models.CharField(max_length=120, db_index=True)
    object_id = models.CharField(max_length=64, blank=True, db_index=True)
    object_display = models.CharField(max_length=255, blank=True)

    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_entries",
    )
    actor_label = models.CharField(max_length=150, blank=True)

    # Full snapshots — the forensic value of the audit log.
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    changed_fields = models.JSONField(default=dict, blank=True)

    reason = models.CharField(max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    request_id = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["model_name", "object_id", "-created_at"])]
        verbose_name = "Audit Log"
        verbose_name_plural = "Audit Logs"

    def __str__(self) -> str:
        return f"{self.action} {self.model_name}#{self.object_id} @ {self.created_at:%Y-%m-%d %H:%M}"

    # -- immutability guards ------------------------------------------------
    def save(self, *args, **kwargs):
        if self.pk is not None:
            # Allow no-op re-saves from bulk tooling only if truly unchanged.
            raise ValueError("AuditLog rows are immutable and cannot be modified.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("AuditLog rows are immutable and cannot be deleted.")
