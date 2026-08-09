"""Forms for the Alert Configuration master and user preferences."""
from __future__ import annotations

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.contrib.auth.models import Group
from django.utils import timezone

from .catalog import BY_KEY, rule_key_choices
from .constants import Module, Priority
from .models import AlertRule, NotificationPreference, OutgoingNotification
from .recipients import delivery_preview, employee_queryset, sender_scope


class AlertRuleForm(forms.ModelForm):
    """Alert Configuration master.

    The notify-target lists are narrowed to what the *editing* user may see. An
    admin scoped to one branch configuring a rule should not be able to point it
    at another branch's farms — the config screen is not a way around the data
    scope the rest of the ERP enforces.
    """

    class Meta:
        model = AlertRule
        fields = [
            "name", "rule_key", "priority", "threshold", "operator",
            "notify_groups", "notify_branches", "notify_org_centres",
            "notify_farms", "notify_warehouses",
            "via_in_app", "via_push", "via_email", "via_sms", "via_whatsapp",
            "cooldown_hours", "is_active",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control",
                                           "placeholder": "e.g. High mortality — supervisors"}),
            "rule_key": forms.Select(attrs={"class": "form-select"}),
            "priority": forms.Select(attrs={"class": "form-select"}),
            "operator": forms.Select(attrs={"class": "form-select"}),
            "threshold": forms.NumberInput(attrs={"class": "form-control",
                                                  "step": "0.001"}),
            "cooldown_hours": forms.NumberInput(attrs={"class": "form-control",
                                                       "min": 0}),
            "notify_groups": forms.SelectMultiple(attrs={"class": "form-select"}),
            "notify_branches": forms.SelectMultiple(attrs={"class": "form-select"}),
            "notify_org_centres": forms.SelectMultiple(attrs={"class": "form-select"}),
            "notify_farms": forms.SelectMultiple(attrs={"class": "form-select"}),
            "notify_warehouses": forms.SelectMultiple(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["rule_key"].choices = [("", "— Select an alert —")] + list(
            rule_key_choices()
        )
        for name in ("via_in_app", "via_push", "via_email", "via_sms", "via_whatsapp",
                     "is_active"):
            self.fields[name].widget.attrs["class"] = "form-check-input"

        self.fields["notify_groups"].queryset = Group.objects.order_by("name")
        if user is not None:
            self._scope_targets(user)

    def _scope_targets(self, user):
        from account.models import OrganizationCentre
        from user.services.scoping import branches_for, farms_for, warehouses_for

        self.fields["notify_branches"].queryset = branches_for(user)
        self.fields["notify_farms"].queryset = farms_for(user)
        self.fields["notify_warehouses"].queryset = warehouses_for(user)
        self.fields["notify_org_centres"].queryset = (
            OrganizationCentre.objects.order_by("name")
        )

    def clean(self):
        data = super().clean()
        spec = BY_KEY.get(data.get("rule_key") or "")
        if spec is None:
            return data

        threshold = data.get("threshold")
        if spec.threshold is not None and threshold is None:
            self.add_error(
                "threshold",
                f"{spec.label} needs a {spec.threshold.label.lower()} "
                f"({spec.threshold.unit or 'value'}).",
            )
        # A threshold on a rule that has none is not an error worth blocking on
        # — it is simply ignored by the detector — but saying so beats letting
        # someone believe a number they typed is doing something.
        if spec.threshold is None and threshold is not None:
            self.add_error(
                "threshold",
                f"{spec.label} has no threshold; it fires on the condition "
                f"itself. Leave this blank.",
            )
        return data

    def clean_rule_key(self):
        key = self.cleaned_data["rule_key"]
        spec = BY_KEY.get(key)
        if spec is None:
            raise forms.ValidationError("Unknown alert type.")
        return key


class PreferenceForm(forms.ModelForm):
    """A user's own delivery preferences.

    ``receive_push`` is live — the mobile app registers a device token and
    alerthub sends through it. ``receive_email`` / ``receive_sms`` /
    ``receive_whatsapp`` are offered even though nothing sends on those channels
    yet: the setting is the user's standing answer, and asking everyone again on
    the day email is switched on would be worse than storing it now. The
    template labels those as coming soon.
    """

    class Meta:
        model = NotificationPreference
        fields = [
            "receive_in_app", "receive_push",
            "receive_email", "receive_sms", "receive_whatsapp",
            "sound_notification", "desktop_notification", "auto_mark_read",
            "min_priority",
        ]
        widgets = {
            "min_priority": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "form-check-input"


#: What an attachment may be, and how big. Mirrors what the page tells the
#: sender — a limit the form states and does not enforce is not a limit.
#:
#: Deliberately *not* read from ``FILE_UPLOAD_MAX_MEMORY_SIZE``: that setting is
#: the threshold at which Django spills an upload to a temp file, not a ceiling
#: on what may be uploaded, and quoting its 2.5 MB to the sender would refuse
#: files the ERP accepts everywhere else. ``ALERTHUB_ATTACHMENT_MAX_BYTES``
#: overrides it where a deployment wants a different number.
ATTACHMENT_EXTENSIONS = ["pdf", "jpg", "jpeg", "png", "docx"]
#: What the page shows. JPEG is accepted but not listed — naming both spellings
#: of one format reads as two.
ATTACHMENT_LABELS = ["PDF", "JPG", "PNG", "DOCX"]
ATTACHMENT_MAX_BYTES = getattr(
    settings, "ALERTHUB_ATTACHMENT_MAX_BYTES", 5 * 1024 * 1024
)


class ManualNotificationForm(forms.ModelForm):
    """Compose one notification and address it down the organisation.

    Two ways to name recipients, because both are how the office thinks about
    it: "the Bahraich supervisors" is a group and "Amrendra" is a person, and
    demanding one shape would mean ticking twelve boxes to reach a team.

    **The hierarchy selects are filters, not recipients.** Choosing a branch
    narrows who is *offered*; it never sends to a branch. That distinction is
    what stops a careless click reaching four hundred people: nothing goes to
    anyone who is not in ``users`` or a chosen group, and the sender saw and
    confirmed that list.

    **The sender's own scope bounds every choice.** Each queryset below comes
    from :func:`alerthub.recipients.sender_scope`, which reads the Employee
    Organization Access master. No permission is defined here — a sender
    attached to Akbarpur simply never sees Tulsipur in a dropdown, and
    :meth:`clean` re-checks the posted ids so a hand-made request cannot reach
    past the same boundary.
    """

    class Meta:
        model = OutgoingNotification
        fields = [
            "notification_type", "title", "message", "priority", "category",
            "attachment", "send_at",
            "companies", "branches", "farms", "warehouses", "departments",
            "designations", "groups", "users",
        ]
        widgets = {
            "notification_type": forms.Select(attrs={"class": "form-select"}),
            "priority": forms.Select(attrs={"class": "form-select"}),
            "category": forms.Select(attrs={"class": "form-select"}),
            "title": forms.TextInput(attrs={
                "class": "form-control", "maxlength": 100,
                "placeholder": "e.g. High Mortality Alert — Akbarpur Broiler Farm",
                "data-counter": "title-count",
            }),
            "message": forms.Textarea(attrs={
                "class": "form-control", "rows": 5, "maxlength": 500,
                "placeholder": "The detail people need. A phone's lock screen "
                               "shows the first line or two — put what matters "
                               "first.",
                "data-counter": "message-count",
            }),
            "send_at": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
        }

    #: Send Now vs Schedule for Later. Not a model field — the model records
    #: *when*, and "now" is simply the absence of a time. Asking the sender to
    #: express "now" as a timestamp would invite one typed in the past.
    schedule = forms.ChoiceField(
        choices=[("now", "Send Now"), ("later", "Schedule for Later")],
        initial="now", required=False, widget=forms.RadioSelect,
    )

    #: Which button was pressed. Send and Save as Draft post the same form —
    #: a draft is the same composition that has not gone out yet — so the
    #: action decides the resulting status rather than a separate view.
    action = forms.ChoiceField(
        choices=[("send", "Send"), ("draft", "Save as Draft")],
        initial="send", required=False, widget=forms.HiddenInput,
    )

    #: Placeholder wording per level, so an untouched dropdown says what
    #: leaving it alone means rather than sitting empty.
    PLACEHOLDERS = {
        "companies": "Companies", "branches": "Branches", "farms": "Farms",
        "warehouses": "Warehouses", "departments": "Departments",
        "designations": "Roles",
    }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

        scope = sender_scope(user) if user is not None else None

        # Every hierarchy level is optional and multi-valued, and each renders
        # as one searchable dropdown. Checkbox lists were the obvious reading of
        # "multi-select" and the wrong one: six scrolling lists stacked made the
        # column taller than the screen, so the recipient count it exists to
        # justify was never visible beside it.
        hierarchy = ("companies", "branches", "farms", "warehouses",
                     "departments", "designations")
        for name in hierarchy:
            field = self.fields[name]
            field.required = False
            if scope is not None:
                field.queryset = scope[name]
            field.widget = forms.SelectMultiple(attrs={
                "class": "form-select sn-hier",
                "data-placeholder": f"All {self.PLACEHOLDERS[name]}",
            })
            field.widget.choices = field.choices

        self.fields["groups"].required = False
        if scope is not None:
            self.fields["groups"].queryset = scope["groups"]

        User = get_user_model()
        # Inactive accounts are not offered: a notification addressed to one is
        # a row nobody will ever read. ``clean_users`` refuses them too, in case
        # someone deactivates an account between load and submit.
        self.fields["users"].queryset = User.objects.filter(is_active=True)
        self.fields["users"].required = False
        # Both recipient lists are driven by the chip UI. They stay real form
        # fields so validation, error redisplay and reopening a draft need no
        # special case.
        for name in ("groups", "users"):
            self.fields[name].widget = forms.SelectMultiple(
                attrs={"class": "js-recipient-source d-none"}
            )
            self.fields[name].widget.choices = self.fields[name].choices

        self.fields["send_at"].required = False
        self.fields["attachment"].required = False
        self.fields["message"].required = True
        self.fields["title"].required = True

    # -- validation --------------------------------------------------------

    def clean_attachment(self):
        f = self.cleaned_data.get("attachment")
        # A FieldFile that came back unchanged from an existing draft has no
        # freshly-uploaded content to check.
        if not f or not hasattr(f, "size"):
            return f
        if f.size > ATTACHMENT_MAX_BYTES:
            limit = ATTACHMENT_MAX_BYTES / 1024 / 1024
            raise forms.ValidationError(
                f"That file is {f.size / 1024 / 1024:.1f} MB. "
                f"The limit is {limit:.0f} MB."
            )
        ext = (f.name.rsplit(".", 1)[-1] if "." in f.name else "").lower()
        if ext not in ATTACHMENT_EXTENSIONS:
            raise forms.ValidationError(
                "Attachments must be PDF, JPG, PNG or DOCX."
            )
        return f

    def clean_users(self):
        """Refuse anyone the sender is not entitled to reach.

        The dropdowns already exclude them, so this only fires on a hand-made
        request or on a draft reopened after the sender's scope was narrowed.
        Either way the answer is the same, and it is checked against the same
        access master the picker reads — not against a second list kept here.
        """
        people = self.cleaned_data.get("users")
        if not people or self.user is None:
            return people

        from user.services.scoping import is_unscoped

        if is_unscoped(self.user):
            return people

        reachable = set(
            employee_queryset(self.user).values_list("user_id", flat=True)
        )
        outside = [u for u in people if u.pk not in reachable]
        if outside:
            names = ", ".join(u.get_full_name() or u.username for u in outside[:3])
            more = f" and {len(outside) - 3} more" if len(outside) > 3 else ""
            raise forms.ValidationError(
                f"{names}{more} are outside your organization access, so they "
                f"cannot be sent to."
            )
        return people

    def clean(self):
        cleaned = super().clean()
        action = cleaned.get("action") or "send"

        # A draft is allowed to be incomplete — that is the point of saving one
        # — so recipients and the schedule are only required on the way out.
        if action == "send":
            if not cleaned.get("groups") and not cleaned.get("users"):
                raise forms.ValidationError("No eligible recipients selected.")

            if cleaned.get("schedule") == "later":
                when = cleaned.get("send_at")
                if not when:
                    self.add_error("send_at", "Pick the date and time to send it.")
                elif when <= timezone.now():
                    # Silently sending it now would be the wrong kindness: the
                    # sender asked for a specific hour and needs to know they
                    # named one that has already passed.
                    self.add_error("send_at", "That time has already passed.")
            else:
                # Send Now wins over any stale time left in the field.
                cleaned["send_at"] = None

        return cleaned

    # -- what the view needs ----------------------------------------------

    @property
    def is_draft(self) -> bool:
        return (self.cleaned_data.get("action") or "send") == "draft"

    @property
    def is_scheduled(self) -> bool:
        return (
            self.cleaned_data.get("schedule") == "later"
            and bool(self.cleaned_data.get("send_at"))
        )

    def preview(self):
        """The counts the confirmation dialog quotes, from the same helper the
        send uses — so the number in the dialog is the number that goes out."""
        return delivery_preview(
            user_ids=self.cleaned_data.get("users") or [],
            group_ids=self.cleaned_data.get("groups") or [],
        )
