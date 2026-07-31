"""API shapes for the bell, the centre and the dashboard widget.

The serializer flattens everything a card needs into one object — priority
colour, module icon, place, relative time, read state — so the front end never
has to join two payloads or hold a lookup table that can drift from the server's.
"""
from __future__ import annotations

from rest_framework import serializers

from .constants import MODULE_ICON, PRIORITY_COLOR, PRIORITY_TONE
from .models import Notification, NotificationPreference


class NotificationSerializer(serializers.ModelSerializer):
    is_read = serializers.SerializerMethodField()
    read_at = serializers.SerializerMethodField()
    module_label = serializers.CharField(source="get_module_display", read_only=True)
    priority_label = serializers.CharField(
        source="get_priority_display", read_only=True
    )
    tone = serializers.SerializerMethodField()
    color = serializers.SerializerMethodField()
    icon = serializers.SerializerMethodField()
    place = serializers.CharField(source="scope_label", read_only=True)
    branch_name = serializers.CharField(
        source="branch.branch_name", read_only=True, default=""
    )
    farm_name = serializers.CharField(
        source="farm.farm_name", read_only=True, default=""
    )
    warehouse_name = serializers.CharField(
        source="warehouse.name", read_only=True, default=""
    )
    detail_url = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            "id", "rule_key", "module", "module_label", "priority",
            "priority_label", "tone", "color", "icon", "title", "message",
            "place", "branch_name", "farm_name", "warehouse_name",
            "object_display", "voucher_no", "action_url", "detail_url",
            "measured_value", "threshold_value", "metadata",
            "is_read", "read_at", "created_at",
        ]

    # ``_recipient`` is annotated by the viewset via prefetch so these do not
    # cost a query per row; falling back to a lookup keeps the serializer
    # usable from anywhere else.
    def _recipient(self, obj):
        cached = getattr(obj, "_my_recipient", None)
        if cached is not None:
            return cached
        user = getattr(self.context.get("request"), "user", None)
        if user is None:
            return None
        return obj.recipients.filter(user=user).first()

    def get_is_read(self, obj) -> bool:
        recipient = self._recipient(obj)
        return bool(recipient and recipient.is_read)

    def get_read_at(self, obj):
        recipient = self._recipient(obj)
        return recipient.read_at if recipient else None

    def get_tone(self, obj) -> str:
        return PRIORITY_TONE.get(obj.priority, "secondary")

    def get_color(self, obj) -> str:
        return PRIORITY_COLOR.get(obj.priority, "#6b7280")

    def get_icon(self, obj) -> str:
        return MODULE_ICON.get(obj.module, "fa-solid fa-bell")

    def get_detail_url(self, obj) -> str:
        from django.urls import reverse

        return reverse("alerthub:notification_detail", args=[obj.pk])


class PreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = [
            "receive_in_app", "receive_email", "receive_sms", "receive_whatsapp",
            "sound_notification", "desktop_notification", "auto_mark_read",
            "min_priority",
        ]
