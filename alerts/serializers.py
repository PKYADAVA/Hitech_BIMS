"""DRF serializers for the alert feed and audit trail."""
from __future__ import annotations

from rest_framework import serializers

from .models import Alert, AuditLog


class AlertSerializer(serializers.ModelSerializer):
    performed_by_username = serializers.CharField(
        source="performed_by.username", read_only=True, default=""
    )
    severity_display = serializers.CharField(source="get_severity_display", read_only=True)
    action_display = serializers.CharField(source="get_action_display", read_only=True)

    class Meta:
        model = Alert
        fields = [
            "id",
            "event_type",
            "action",
            "action_display",
            "severity",
            "severity_display",
            "model_name",
            "object_id",
            "object_display",
            "title",
            "message",
            "performed_by",
            "performed_by_username",
            "actor_label",
            "ip_address",
            "browser",
            "os",
            "device",
            "changed_fields",
            "metadata",
            "is_read",
            "read_at",
            "created_at",
        ]
        read_only_fields = fields  # feed rows are produced by the system, not the API


class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = [
            "id",
            "event_type",
            "action",
            "model_name",
            "object_id",
            "object_display",
            "performed_by",
            "actor_label",
            "before",
            "after",
            "changed_fields",
            "reason",
            "ip_address",
            "request_id",
            "metadata",
            "created_at",
        ]
        read_only_fields = fields
