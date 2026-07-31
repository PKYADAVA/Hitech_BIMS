"""Persistence for business alerts.

Four tables, each with one job:

* :class:`AlertRule` — the Alert Configuration master. What to watch, at what
  threshold, at what priority, and who to tell.
* :class:`Notification` — one raised alert. Carries its own scope columns
  (branch / centre / farm / warehouse) so visibility can be decided in SQL
  without walking back to the source row, which may since have been deleted.
* :class:`NotificationRecipient` — the fan-out. One row per user who was told,
  holding *their* read state.
* :class:`NotificationPreference` — per-user delivery choices.

**Why recipients are a separate table.** Read state is per person: the same
"High Mortality" alert is unread for the supervisor and read for the manager,
and the history has to show who it went to and when each of them opened it. A
boolean on Notification could only ever describe one of them. It also makes the
unread badge a single indexed count over one user's rows.

The scope columns use ``SET_NULL``: a notification outlives the farm it was
about. Losing the link degrades the row to a less filterable notification rather
than deleting a piece of history — the same reasoning
:mod:`alerts.models` uses for storing targets as labels.
"""
from __future__ import annotations

from django.conf import settings
from django.contrib.auth.models import Group
from django.db import models
from django.utils import timezone

from .catalog import BY_KEY, rule_key_choices
from .constants import Channel, Module, Operator, Priority


class AlertRule(models.Model):
    """Alert Configuration master — one configured watch.

    Several rules may share a ``rule_key``: "High Mortality at 0.5% for the
    broiler team" and "High Mortality at 1.5%, critical, for the directors" are
    two rows, and both fire. That is deliberate — escalation tiers are the main
    thing operators want and a unique constraint on rule_key would forbid them.
    """

    name = models.CharField(
        max_length=150,
        help_text="What this watch is called in the config list, e.g. "
                  "'High mortality — broiler supervisors'.",
    )
    rule_key = models.CharField(
        max_length=64, choices=rule_key_choices(), db_index=True,
        help_text="Which catalogued alert this configures.",
    )
    module = models.CharField(
        max_length=20, choices=Module.choices, db_index=True, blank=True,
        help_text="Derived from the rule key on save; stored so the list can "
                  "filter and group without loading the catalogue.",
    )
    priority = models.CharField(
        max_length=10, choices=Priority.choices, default=Priority.MEDIUM,
        db_index=True,
    )

    # --- trigger condition ------------------------------------------------
    threshold = models.DecimalField(
        max_digits=14, decimal_places=3, null=True, blank=True,
        help_text="The number the measured value is compared against. Leave "
                  "blank for rules that have no threshold (e.g. Negative Stock).",
    )
    operator = models.CharField(
        max_length=4, choices=Operator.choices, default=Operator.GTE,
        help_text="How the measured value is compared with the threshold.",
    )

    # --- who to tell ------------------------------------------------------
    notify_groups = models.ManyToManyField(
        Group, blank=True, related_name="alert_rules",
        help_text="User Access Groups to notify. Empty means every group whose "
                  "data scope overlaps the alert.",
    )
    notify_branches = models.ManyToManyField(
        "broiler.Branch", blank=True, related_name="alert_rules",
        help_text="Restrict this rule to these branches. Empty means all.",
    )
    notify_org_centres = models.ManyToManyField(
        "account.OrganizationCentre", blank=True, related_name="alert_rules",
        help_text="Restrict to these organization / cost centres. Empty = all.",
    )
    notify_farms = models.ManyToManyField(
        "broiler.BroilerFarm", blank=True, related_name="alert_rules",
        help_text="Restrict to these farms. Empty means all.",
    )
    notify_warehouses = models.ManyToManyField(
        "inventory.Warehouse", blank=True, related_name="alert_rules",
        help_text="Restrict to these warehouses / offices. Empty means all.",
    )

    # --- delivery ---------------------------------------------------------
    # Stored per channel rather than as a set so the config form is a row of
    # checkboxes and a query can ask "which rules want email" directly.
    via_in_app = models.BooleanField(default=True, verbose_name="In-App")
    via_email = models.BooleanField(default=False, verbose_name="Email")
    via_sms = models.BooleanField(default=False, verbose_name="SMS")
    via_whatsapp = models.BooleanField(default=False, verbose_name="WhatsApp")

    is_active = models.BooleanField(
        default=True, db_index=True,
        help_text="Disabled rules are kept and simply never evaluated.",
    )

    # --- repeat control ---------------------------------------------------
    cooldown_hours = models.PositiveIntegerField(
        default=24,
        help_text="Do not raise the same alert for the same subject again "
                  "within this many hours. 0 raises it on every scan.",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        blank=True, related_name="alert_rules_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("module", "name")
        verbose_name = "Alert Configuration"
        verbose_name_plural = "Alert Configuration"
        indexes = [models.Index(fields=["is_active", "rule_key"])]

    def __str__(self) -> str:
        return self.name

    @property
    def spec(self):
        """The catalogue entry behind this rule, or None if the key is stale."""
        return BY_KEY.get(self.rule_key)

    @property
    def is_supported(self) -> bool:
        spec = self.spec
        return bool(spec and spec.supported)

    @property
    def channels(self) -> list[str]:
        chosen = [
            (Channel.IN_APP, self.via_in_app),
            (Channel.EMAIL, self.via_email),
            (Channel.SMS, self.via_sms),
            (Channel.WHATSAPP, self.via_whatsapp),
        ]
        return [channel for channel, on in chosen if on]

    def save(self, *args, **kwargs):
        spec = self.spec
        if spec:
            self.module = spec.module
        return super().save(*args, **kwargs)


class NotificationQuerySet(models.QuerySet):
    def unread_for(self, user):
        return self.filter(recipients__user=user, recipients__is_read=False)

    def for_user(self, user):
        from .scoping import visible_notifications

        return visible_notifications(self, user)

    def by_urgency(self):
        """Most urgent first, then most recent.

        Priority is a string in the database, so ordering by the column would
        sort alphabetically — critical, high, low, medium — which puts Low above
        Medium. The explicit case is the only correct ordering.
        """
        from django.db.models import Case, IntegerField, Value, When

        from .constants import PRIORITY_RANK

        ranking = Case(
            *[When(priority=p, then=Value(rank)) for p, rank in PRIORITY_RANK.items()],
            default=Value(99), output_field=IntegerField(),
        )
        return self.annotate(_rank=ranking).order_by("_rank", "-created_at")


class Notification(models.Model):
    """One raised business alert.

    ``dedupe_key`` is what stops a nightly scan re-raising the same thing
    forever. Detectors build it from the rule and the subject (batch, item,
    invoice), so "High Mortality on BR-26031 today" is one alert no matter how
    often the scanner runs.
    """

    rule = models.ForeignKey(
        AlertRule, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="notifications",
        help_text="The configuration that raised this. Null once that rule is "
                  "deleted — the alert itself stays.",
    )
    rule_key = models.CharField(max_length=64, db_index=True)
    module = models.CharField(max_length=20, choices=Module.choices, db_index=True)
    priority = models.CharField(
        max_length=10, choices=Priority.choices, default=Priority.MEDIUM,
        db_index=True,
    )

    title = models.CharField(max_length=200)
    message = models.TextField(blank=True)

    # --- scope: the security columns -------------------------------------
    branch = models.ForeignKey(
        "broiler.Branch", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="notifications",
    )
    org_centre = models.ForeignKey(
        "account.OrganizationCentre", on_delete=models.SET_NULL, null=True,
        blank=True, related_name="notifications",
    )
    farm = models.ForeignKey(
        "broiler.BroilerFarm", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="notifications",
    )
    warehouse = models.ForeignKey(
        "inventory.Warehouse", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="notifications",
    )

    # --- what it is about -------------------------------------------------
    # Stored as label + id rather than a GenericForeignKey, matching
    # alerts.models: the row must survive its subject being deleted.
    object_label = models.CharField(
        max_length=120, blank=True, db_index=True,
        help_text="app_label.ModelName of the subject, e.g. 'broiler.BroilerBatch'.",
    )
    object_id = models.CharField(max_length=64, blank=True, db_index=True)
    object_display = models.CharField(max_length=255, blank=True)
    voucher_no = models.CharField(max_length=60, blank=True)
    action_url = models.CharField(
        max_length=300, blank=True,
        help_text="Where the View button goes. Blank hides the button.",
    )

    #: measured value vs threshold, kept for the detail page and the history
    #: export so an old alert can still explain itself.
    measured_value = models.DecimalField(
        max_digits=14, decimal_places=3, null=True, blank=True
    )
    threshold_value = models.DecimalField(
        max_digits=14, decimal_places=3, null=True, blank=True
    )
    metadata = models.JSONField(default=dict, blank=True)

    dedupe_key = models.CharField(max_length=255, db_index=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        blank=True, related_name="notifications_raised",
        help_text="Null for scanner-raised alerts, which is most of them.",
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    objects = NotificationQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["rule_key", "-created_at"]),
            models.Index(fields=["priority", "-created_at"]),
            models.Index(fields=["dedupe_key", "-created_at"]),
            models.Index(fields=["module", "-created_at"]),
        ]
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"

    def __str__(self) -> str:
        return f"[{self.priority}] {self.title}"

    @property
    def spec(self):
        return BY_KEY.get(self.rule_key)

    @property
    def tone(self) -> str:
        from .constants import PRIORITY_TONE

        return PRIORITY_TONE.get(self.priority, "secondary")

    @property
    def icon(self) -> str:
        from .constants import MODULE_ICON

        return MODULE_ICON.get(self.module, "fa-solid fa-bell")

    @property
    def scope_label(self) -> str:
        """The place this alert is about, for the one-line card subtitle."""
        for value in (self.farm, self.warehouse, self.org_centre, self.branch):
            if value is not None:
                return str(value)
        return ""


class NotificationRecipient(models.Model):
    """One user's copy of a notification, and their read state.

    ``delivered_channels`` records what was actually sent, not what the rule
    asked for. With only in-app live today the two differ constantly, and the
    history has to show the truth.
    """

    notification = models.ForeignKey(
        Notification, on_delete=models.CASCADE, related_name="recipients"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="alert_notifications",
    )
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    delivered_channels = models.JSONField(
        default=list, blank=True,
        help_text="Channels this actually went out on.",
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        unique_together = ("notification", "user")
        ordering = ("-created_at",)
        indexes = [
            # The badge count: one user's unread rows, newest first.
            models.Index(fields=["user", "is_read", "-created_at"]),
        ]
        verbose_name = "Notification recipient"

    def __str__(self) -> str:
        return f"{self.user} · {self.notification_id}"

    def mark_read(self, *, commit: bool = True) -> None:
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            if commit:
                self.save(update_fields=["is_read", "read_at"])


class NotificationPreference(models.Model):
    """Per-user delivery and presentation choices.

    Channel toggles here can only ever *narrow* what a rule asked for — a user
    switching email off stops their own email, and no preference can add a
    channel the rule did not enable. In-app has no opt-out on purpose: it is
    the record that the user was told, and the history and audit depend on it
    existing. What the switch below controls is whether it also pops up.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="alert_preference",
    )
    receive_in_app = models.BooleanField(
        default=True, verbose_name="Receive In-App",
        help_text="Show alerts in the bell and notification centre.",
    )
    receive_email = models.BooleanField(default=False, verbose_name="Receive Email")
    receive_sms = models.BooleanField(default=False, verbose_name="Receive SMS")
    receive_whatsapp = models.BooleanField(
        default=False, verbose_name="Receive WhatsApp"
    )
    sound_notification = models.BooleanField(
        default=False, verbose_name="Sound Notification",
        help_text="Play a short tone when a new alert arrives.",
    )
    desktop_notification = models.BooleanField(
        default=False, verbose_name="Desktop Notification",
        help_text="Use the browser's notification popup. Needs permission.",
    )
    auto_mark_read = models.BooleanField(
        default=False, verbose_name="Auto Mark Read",
        help_text="Mark alerts read as soon as they are shown in the bell.",
    )
    min_priority = models.CharField(
        max_length=10, choices=Priority.choices, default=Priority.LOW,
        help_text="Hide anything less urgent than this. Low shows everything.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Notification preference"

    def __str__(self) -> str:
        return f"Alert preferences · {self.user}"

    @classmethod
    def for_user(cls, user):
        """Preferences for a user, creating the default row on first read."""
        obj, _ = cls.objects.get_or_create(user=user)
        return obj

    def allows(self, channel: str) -> bool:
        return {
            Channel.IN_APP: self.receive_in_app,
            Channel.EMAIL: self.receive_email,
            Channel.SMS: self.receive_sms,
            Channel.WHATSAPP: self.receive_whatsapp,
        }.get(channel, False)
