"""API shapes for the bell, the centre and the dashboard widget.

The serializer flattens everything a card needs into one object — priority
colour, module icon, place, relative time, read state — so the front end never
has to join two payloads or hold a lookup table that can drift from the server's.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from rest_framework import serializers

from .constants import (MODULE_ICON, PRIORITY_COLOR, PRIORITY_TONE,
                        SEVERITY_LABEL, STATUS_COLOR, AlertStatus)
from .models import AlertAction, Notification, NotificationPreference


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
    category_label = serializers.CharField(
        source="get_category_display", read_only=True, default=""
    )
    # A file the sender attached by hand. Absolute so the phone, which has no
    # notion of the site root, can open it directly.
    attachment_url = serializers.SerializerMethodField()
    attachment_name = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            "id", "rule_key", "module", "module_label", "priority",
            "priority_label", "category", "category_label",
            "tone", "color", "icon", "title", "message",
            "place", "branch_name", "farm_name", "warehouse_name",
            "object_display", "voucher_no", "action_url", "detail_url",
            "attachment_url", "attachment_name",
            "measured_value", "threshold_value", "metadata",
            "is_read", "read_at", "created_at",
        ]

    def get_attachment_url(self, obj) -> str:
        if not obj.attachment:
            return ""
        try:
            url = obj.attachment.url
        except ValueError:
            return ""
        request = self.context.get("request")
        return request.build_absolute_uri(url) if request else url

    def get_attachment_name(self, obj) -> str:
        return obj.attachment_name if obj.attachment else ""

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


def _grouped(value) -> str:
    """A measured value, grouped the way it is read here.

    Indian grouping — 2,45,000, not 245,000 — because the alert's own message
    sentence is written that way, and a row that says "2,45,000 outstanding"
    beside a figure reading "245,000" looks like two different numbers.

    Trailing zeros go: a threshold of 3 is "3 days", not "3.00 days". Whole
    numbers keep no decimal point at all, which is the difference from
    ``purchase.templatetags.purchase_extras.indian_currency`` — that one is
    formatting money, where two decimals are always wanted.
    """
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return str(value)

    sign = "-" if number < 0 else ""
    number = abs(number)
    whole = int(number)
    fraction = ("%.2f" % (number - whole)).split(".")[1].rstrip("0")

    digits = str(whole)
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        digits = ",".join(parts) + "," + tail

    return sign + digits + ("." + fraction if fraction else "")


class AlertActionSerializer(serializers.ModelSerializer):
    """One line of the audit trail."""

    actor_name = serializers.SerializerMethodField()
    action_label = serializers.CharField(source="get_action_display", read_only=True)

    class Meta:
        model = AlertAction
        fields = ["id", "action", "action_label", "actor_name", "note",
                  "from_status", "to_status", "notified", "created_at"]

    def get_actor_name(self, obj) -> str:
        # "System" rather than blank: an entry with no name against it reads
        # like the name failed to load, when in fact nobody typed it.
        if obj.actor is None:
            return "System"
        return obj.actor.get_full_name() or obj.actor.get_username()


class ActionAlertSerializer(NotificationSerializer):
    """An alert as the Action Required card needs it.

    Everything the base serializer gives the bell, plus the three things this
    card is built around: where the work has got to, what may be done next, and
    the one number that made it fire.

    ``available_actions`` is computed on the server from the same transition
    table the endpoints enforce. The card renders whatever comes back rather
    than deciding for itself which buttons make sense — two copies of that rule
    would drift, and the visible copy is the one that would be wrong.
    """

    severity_label = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    status_tone = serializers.CharField(read_only=True)
    status_color = serializers.SerializerMethodField()
    status_changed_by_name = serializers.SerializerMethodField()
    assigned_to_name = serializers.SerializerMethodField()
    available_actions = serializers.SerializerMethodField()
    reading = serializers.SerializerMethodField()
    reading_value = serializers.SerializerMethodField()
    reading_limit = serializers.SerializerMethodField()
    action_count = serializers.SerializerMethodField()
    more_like_this = serializers.SerializerMethodField()

    class Meta(NotificationSerializer.Meta):
        fields = NotificationSerializer.Meta.fields + [
            "severity_label", "status", "status_label", "status_tone", "status_color",
            "status_changed_at", "status_changed_by_name", "dismiss_reason",
            "assigned_to", "assigned_to_name", "assigned_at",
            "available_actions", "reading", "reading_value", "reading_limit",
            "action_count",
            "more_like_this",
        ]

    def get_severity_label(self, obj) -> str:
        return SEVERITY_LABEL.get(obj.priority, obj.get_priority_display())

    def get_status_color(self, obj) -> str:
        return STATUS_COLOR.get(obj.status, "#64748b")

    def get_status_changed_by_name(self, obj) -> str:
        person = obj.status_changed_by
        if person is None:
            return ""
        return person.get_full_name() or person.get_username()

    def get_assigned_to_name(self, obj) -> str:
        """Whose job this is, in the name the card shows.

        Blank rather than "Unassigned": the card writes its own words for the
        empty case, and a serializer that puts a label in a name field makes
        every caller check for that particular sentence.
        """
        person = obj.assigned_to
        if person is None:
            return ""
        return person.get_full_name() or person.get_username()

    def get_available_actions(self, obj) -> list:
        from .workflow import TRANSITIONS

        # One word each. Six buttons have to sit on one line in a card that is
        # half the dashboard wide, and "Mark Resolved" says nothing "Resolve"
        # does not — the second word was costing a whole row of card height.
        labels = {
            AlertStatus.ACKNOWLEDGED: ("acknowledge", "Acknowledge"),
            AlertStatus.IN_PROGRESS: ("start", "Start"),
            AlertStatus.RESOLVED: ("resolve", "Resolve"),
            AlertStatus.DISMISSED: ("dismiss", "Dismiss"),
            AlertStatus.OPEN: ("reopen", "Reopen"),
        }
        out = []
        for target in TRANSITIONS.get(obj.status, ()):
            key, label = labels[target]
            out.append({"key": key, "label": label, "to": str(target),
                        # Dismissal is the one that cannot be done from a
                        # single press, so the card knows to open the dialog.
                        "needs_reason": target == AlertStatus.DISMISSED})
        order = ["acknowledge", "start", "resolve", "dismiss", "reopen"]
        out.sort(key=lambda a: order.index(a["key"]))
        return out

    def get_reading(self, obj) -> str:
        """The measurement, in the unit the rule is written in.

        Built from the rule's own threshold wording rather than a format
        guessed per module, so a coverage rule reads "1.8 days / 3 days" and a
        weight rule "1,450 g / 1,700 g" without either of them being special
        cased here.
        """
        if obj.measured_value is None:
            return ""
        spec = obj.spec
        unit = ""
        if spec is not None and getattr(spec, "threshold", None) is not None:
            unit = getattr(spec.threshold, "unit", "") or ""

        def fmt(value):
            return _grouped(value)

        reading = fmt(obj.measured_value)
        if obj.threshold_value is not None:
            reading = "%s / %s" % (reading, fmt(obj.threshold_value))
        return ("%s %s" % (reading, unit)).strip()

    def _unit(self, obj) -> str:
        spec = obj.spec
        if spec is not None and getattr(spec, "threshold", None) is not None:
            return getattr(spec.threshold, "unit", "") or ""
        return ""

    @staticmethod
    def _with_unit(number: str, unit: str, last: bool) -> str:
        """Attach the unit the way that unit is written.

        A symbol closes up against its number and belongs on both halves of a
        comparison — "8.11% vs limit 5%". A word takes a space and is said
        once, on the second half, because "8.11 days vs limit 5 days" makes
        the pair read as two separate facts. "8.11 vs limit 5 %" is what came
        of treating both the same.
        """
        if not unit:
            return number
        if unit[0].isalpha():
            return ("%s %s" % (number, unit)) if last else number
        return number + unit

    def get_reading_value(self, obj) -> str:
        """What was measured, on its own.

        Split out of ``reading`` so the card can caption the figure
        truthfully. One combined string could only ever be labelled
        "measured / limit", and that is a lie on the rules with no limit to
        compare against: negative stock fired at -60 showed a lone "-60"
        under a caption promising two numbers. With the halves apart, a row
        with a threshold reads "8.11% / 5%" over "measured / limit" and one
        without reads "-60" over "measured".

        The unit rides on whichever half is last, so the pair says it once
        rather than twice.
        """
        if obj.measured_value is None:
            return ""
        return self._with_unit(_grouped(obj.measured_value), self._unit(obj),
                               last=obj.threshold_value is None)

    def get_reading_limit(self, obj) -> str:
        """The threshold it was judged against, where the rule has one."""
        if obj.measured_value is None or obj.threshold_value is None:
            return ""
        return self._with_unit(_grouped(obj.threshold_value), self._unit(obj),
                               last=True)

    def get_more_like_this(self, obj) -> int:
        """Open alerts from the same rule that the card left out.

        Attached by the view, which is the only place that knows what
        else it chose not to show. Zero anywhere else, which is honest:
        a serializer used outside the widget has nothing to compare to.
        """
        return getattr(obj, "_more_like_this", 0)

    def get_action_count(self, obj) -> int:
        return obj.actions.count()


class PreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = [
            "receive_in_app", "receive_email", "receive_sms", "receive_whatsapp",
            "sound_notification", "desktop_notification", "auto_mark_read",
            "min_priority",
        ]
