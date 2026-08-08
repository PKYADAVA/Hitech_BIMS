"""Pages: the notification centre, history, detail, config master, preferences.

The feed pages are shells — rows come from the API so the bell, the centre and
the dashboard widget all read one implementation of "what may this user see".
The config master and preferences are ordinary server-rendered forms, because
they are edited rarely and benefit from Django's validation and CSRF handling
rather than a hand-written fetch.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from .catalog import CATALOG, BY_KEY
from .constants import Module, Priority
from .forms import AlertRuleForm, ManualNotificationForm, PreferenceForm
from .models import AlertRule, Notification, NotificationPreference
from .engine import send_manual_notification
from .scoping import can_see


def _filter_options(user):
    """Dropdown contents for the centre and history filter bars.

    Only what the user is scoped to — a branch filter offering branches whose
    alerts they can never see is a dead option that makes the page look broken.
    """
    from user.services.scoping import branches_for, farms_for, warehouses_for

    return {
        "modules": Module.choices,
        "priorities": Priority.choices,
        "branches": branches_for(user),
        "farms": farms_for(user),
        "warehouses": warehouses_for(user),
    }


@login_required(login_url="login")
def notification_center(request):
    """Full-page feed with search, filters and grouping."""
    return render(request, "alerthub/notification_center.html", {
        "active_tab": "alerts",
        **_filter_options(request.user),
    })


@login_required(login_url="login")
def notification_history(request):
    """The audit-shaped view of the same data: one dense, filterable table."""
    return render(request, "alerthub/notification_history.html", {
        "active_tab": "alerts",
        **_filter_options(request.user),
    })


@login_required(login_url="login")
def notification_detail(request, pk):
    """One alert in full.

    Permission is re-checked here rather than trusted from the list that linked
    here: a detail url is guessable, and a notification id is not a capability.
    A refusal is a 404 rather than a 403 — telling someone that alert #412
    exists but belongs to another branch is itself a small leak.
    """
    notification = get_object_or_404(
        Notification.objects.select_related(
            "branch", "farm", "warehouse", "org_centre", "rule", "created_by"
        ),
        pk=pk,
    )
    if not can_see(request.user, notification):
        raise Http404

    recipient = notification.recipients.filter(user=request.user).first()
    if recipient and not recipient.is_read:
        recipient.mark_read()

    spec = notification.spec
    return render(request, "alerthub/notification_detail.html", {
        "active_tab": "alerts",
        "n": notification,
        "spec": spec,
        "recipient": recipient,
        "recipients": notification.recipients.select_related("user"),
    })


# ---------------------------------------------------------------------------
# Alert Configuration master
# ---------------------------------------------------------------------------

@login_required(login_url="login")
def alert_rule_list(request):
    """Every configured watch, with how many alerts each has raised."""
    rules = (
        AlertRule.objects.annotate(raised=Count("notifications"))
        .prefetch_related("notify_groups")
        .order_by("module", "name")
    )
    module = request.GET.get("module")
    if module:
        rules = rules.filter(module=module)

    rows = []
    for rule in rules:
        spec = rule.spec
        rows.append({
            "rule": rule,
            "spec": spec,
            "supported": bool(spec and spec.supported),
            "requires": spec.requires if spec else "Unknown alert type.",
        })

    return render(request, "alerthub/alert_rule_list.html", {
        "active_tab": "alerts",
        "rows": rows,
        "modules": Module.choices,
        "selected_module": module or "",
        "catalog_total": len(CATALOG),
        "configured": AlertRule.objects.count(),
    })


@login_required(login_url="login")
def alert_rule_form(request, pk=None):
    """Create or edit one rule.

    The catalogue is passed to the template as JSON so choosing an alert can
    prefill its default threshold, unit and priority, and show what it watches
    — otherwise "0.50" in a box labelled Threshold means nothing.
    """
    import json

    rule = get_object_or_404(AlertRule, pk=pk) if pk else None
    if request.method == "POST":
        form = AlertRuleForm(request.POST, instance=rule, user=request.user)
        if form.is_valid():
            saved = form.save(commit=False)
            if rule is None:
                saved.created_by = request.user
            saved.save()
            form.save_m2m()
            messages.success(
                request,
                f"Alert configuration “{saved.name}” "
                f"{'updated' if pk else 'created'}.",
            )
            return redirect("alerthub:alert_rule_list")
    else:
        form = AlertRuleForm(instance=rule, user=request.user)

    catalog = {
        spec.key: {
            "label": spec.label,
            "module": Module(spec.module).label,
            "priority": spec.priority,
            "description": spec.description,
            "requires": spec.requires,
            "threshold": None if spec.threshold is None else {
                "label": spec.threshold.label,
                "unit": spec.threshold.unit,
                "default": str(spec.threshold.default),
                "operator": spec.threshold.operator,
                "help": spec.threshold.help_text,
            },
        }
        for spec in CATALOG
    }

    return render(request, "alerthub/alert_rule_form.html", {
        "active_tab": "alerts",
        "form": form,
        "rule": rule,
        "catalog_json": json.dumps(catalog),
    })


@login_required(login_url="login")
def alert_rule_delete(request, pk):
    """Delete a configuration. The alerts it already raised are kept.

    ``Notification.rule`` is SET_NULL, so history survives — removing a rule
    stops future alerts rather than rewriting the record of past ones.
    """
    rule = get_object_or_404(AlertRule, pk=pk)
    if request.method == "POST":
        name = rule.name
        rule.delete()
        messages.success(request, f"Alert configuration “{name}” deleted.")
        return redirect("alerthub:alert_rule_list")
    return render(request, "alerthub/alert_rule_confirm_delete.html", {
        "active_tab": "alerts",
        "rule": rule,
        "raised": rule.notifications.count(),
    })


@login_required(login_url="login")
def alert_catalog(request):
    """Read-only map of every alert the system knows, supported or not.

    Its job is to answer "can the ERP tell me about X?" without the reader
    having to open the configuration form and scroll a dropdown of seventy.
    """
    by_module = {}
    for spec in CATALOG:
        by_module.setdefault(Module(spec.module).label, []).append(spec)

    configured = set(
        AlertRule.objects.filter(is_active=True).values_list("rule_key", flat=True)
    )
    return render(request, "alerthub/alert_catalog.html", {
        "active_tab": "alerts",
        "by_module": by_module,
        "configured": configured,
        "supported_count": sum(1 for s in CATALOG if s.supported),
        "total": len(CATALOG),
    })


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------

@login_required(login_url="login")
def preferences(request):
    pref = NotificationPreference.for_user(request.user)
    if request.method == "POST":
        form = PreferenceForm(request.POST, instance=pref)
        if form.is_valid():
            form.save()
            messages.success(request, "Notification preferences saved.")
            return redirect("alerthub:preferences")
    else:
        form = PreferenceForm(instance=pref)

    return render(request, "alerthub/preferences.html", {
        "active_tab": "alerts",
        "form": form,
    })


@login_required(login_url="login")
def send_notification(request):
    """Compose one notification and send it to chosen users or groups.

    Gated on the same right as Alert Configuration: deciding who the system
    notifies and notifying them by hand are the same kind of authority, and a
    separate permission would be one more thing to forget to grant.

    The message is a real notification, not a bare push — it lands in the
    recipients' bell and stays in the history, so there is a record of what was
    sent, to whom, and by whom.
    """
    from user.access import user_can

    if not user_can(request.user, "send_notification", "add"):
        raise Http404

    form = ManualNotificationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        people = form.recipients()
        notification = send_manual_notification(
            sender=request.user,
            recipients=people,
            title=form.cleaned_data["title"],
            message=form.cleaned_data["message"],
            priority=form.cleaned_data["priority"],
            module=form.cleaned_data["module"],
        )
        if notification is None:
            messages.error(request, "Nobody active matched that selection — nothing was sent.")
        else:
            pushed = sum(1 for u in people if getattr(u, "pk", None))
            messages.success(
                request,
                f"Sent to {len(people)} user(s). It is in their notifications now, "
                f"and on the phones of those with the app installed."
            )
            return redirect("alerthub:send_notification")

    return render(request, "alerthub/send_notification.html", {
        "active_tab": "send_notification",
        "form": form,
    })
