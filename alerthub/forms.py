"""Forms for the Alert Configuration master and user preferences."""
from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.contrib.auth.models import Group

from .catalog import BY_KEY, rule_key_choices
from .constants import Module, Priority
from .models import AlertRule, NotificationPreference


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


class ManualNotificationForm(forms.Form):
    """Compose one notification and send it to chosen people.

    Users *or* groups, because both are how the office thinks about it — "the
    Bahraich supervisors" is a group, "Amrendra" is a user, and demanding one
    shape would mean ticking twelve boxes to reach a team.
    """

    title = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={"class": "form-control",
                                      "placeholder": "e.g. Feed delivery delayed to Monday"}),
    )
    message = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 4,
                                     "placeholder": "The detail people need. Kept short — a phone shows the first line or two."}),
    )
    priority = forms.ChoiceField(
        choices=Priority.choices, initial=Priority.MEDIUM,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    module = forms.ChoiceField(
        choices=Module.choices, initial=Module.SYSTEM,
        widget=forms.Select(attrs={"class": "form-select"}),
        help_text="Only decides the icon and how it files in the centre.",
    )
    groups = forms.ModelMultipleChoiceField(
        queryset=Group.objects.order_by("name"), required=False,
        widget=forms.SelectMultiple(attrs={"class": "form-select", "size": 8}),
    )
    users = forms.ModelMultipleChoiceField(
        queryset=None, required=False,
        widget=forms.SelectMultiple(attrs={"class": "form-select", "size": 8}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        User = get_user_model()
        # Inactive accounts are not offered: a notification addressed to one is
        # a row nobody will ever read.
        self.fields["users"].queryset = User.objects.filter(is_active=True).order_by("username")

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("groups") and not cleaned.get("users"):
            raise forms.ValidationError(
                "Choose at least one group or user to send this to."
            )
        return cleaned

    def recipients(self):
        """Every active user named directly or through a group, de-duplicated."""
        User = get_user_model()
        chosen = self.cleaned_data
        qs = User.objects.filter(is_active=True).filter(
            Q(pk__in=chosen.get("users") or [])
            | Q(groups__in=chosen.get("groups") or [])
        ).distinct()
        return list(qs)
