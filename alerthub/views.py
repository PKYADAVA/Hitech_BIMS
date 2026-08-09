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
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

import json

from django.utils import timezone

from .catalog import CATALOG, BY_KEY
from .constants import Module, Priority, TYPE_DEFAULTS
from .dispatch import dispatch
from .forms import (
    ATTACHMENT_EXTENSIONS, ATTACHMENT_MAX_BYTES,
    AlertRuleForm, ManualNotificationForm, PreferenceForm,
)
from .models import (
    AlertRule, Notification, NotificationPreference, NotificationRecipient,
    OutgoingNotification,
)
from .recipients import (
    delivery_preview, employee_options, farms_for_branches, group_options,
    warehouses_for_branches,
)
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
@require_POST
def alert_rule_toggle(request, pk):
    """Turn one rule on or off from the list, without opening the form.

    Switching a watch off is the one edit that is made in a hurry — an alert
    firing too often at two in the morning, and the person who can stop it is
    looking at a list of forty rules. Making them open a form, find the right
    checkbox among a dozen fields and save was several steps and a page load
    away from the thing they actually wanted.

    POST only. A GET that changes state is a link a browser or a crawler will
    follow on its own, and "something disabled our alerts and nobody knows
    what" is a bad afternoon.
    """
    rule = get_object_or_404(AlertRule, pk=pk)

    # A rule whose alert type has no data source behind it cannot fire, so
    # letting it be switched "on" would show an Enabled badge that means
    # nothing. The form says the same thing at more length.
    spec = rule.spec
    if not rule.is_active and not (spec and spec.supported):
        return JsonResponse(
            {"ok": False,
             "is_active": rule.is_active,
             "message": spec.requires if spec else "This alert type is not available."},
            status=400)

    rule.is_active = not rule.is_active
    rule.save(update_fields=["is_active"])
    return JsonResponse({
        "ok": True,
        "is_active": rule.is_active,
        "message": f"“{rule.name}” {'enabled' if rule.is_active else 'disabled'}.",
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


# ---------------------------------------------------------------------------
# Send Notification
# ---------------------------------------------------------------------------
#
# Three views and one rule between them: nothing decides *who may do what*
# here. ``user_can`` answers that from the Web-Access matrix, and which people
# a sender may aim at comes from the Employee Organization Access master
# through ``alerthub.recipients``. This module reads both and defines neither.


def _require_send_permission(user):
    """Gate on the existing Web-Access matrix, or 404.

    404 rather than 403 deliberately, matching the rest of the module: a tab
    someone cannot use should not advertise that it exists.
    """
    from user.access import user_can

    if not user_can(user, "send_notification", "add"):
        raise Http404


@login_required(login_url="login")
def send_notification(request, pk=None):
    """Compose a notification and send it, schedule it, or save it as a draft.

    One view for all three because they are one composition at different points
    in its life — the difference is which button was pressed, not which form was
    filled in. Reopening a draft (``pk``) posts back here too, so a message
    saved on Monday and sent on Tuesday travels exactly one code path.

    Sending itself is delegated to :func:`alerthub.dispatch.dispatch`, which the
    scheduled-send command also calls. The page never writes a ``Notification``
    directly; that is what keeps a hand-sent message and a scheduled one
    identical in the bell, in the mobile app and in the history.
    """
    _require_send_permission(request.user)

    outgoing = None
    if pk is not None:
        outgoing = get_object_or_404(OutgoingNotification, pk=pk)
        if not outgoing.is_editable:
            messages.info(
                request,
                "That notification has already gone out — opening it read-only.",
            )
            return redirect("alerthub:outgoing_detail", pk=outgoing.pk)

    form = ManualNotificationForm(
        request.POST or None, request.FILES or None,
        instance=outgoing, user=request.user,
    )

    if request.method == "POST" and form.is_valid():
        record = form.save(commit=False)
        if record.created_by_id is None:
            record.created_by = request.user
        record.status = (
            OutgoingNotification.DRAFT if form.is_draft
            else OutgoingNotification.SCHEDULED if form.is_scheduled
            else OutgoingNotification.SENDING
        )
        record.error = ""
        record.save()
        form.save_m2m()

        if form.is_draft:
            messages.success(request, "Saved as a draft. It has not been sent.")
            return redirect("alerthub:outgoing_edit", pk=record.pk)

        if form.is_scheduled:
            messages.success(
                request,
                f"Scheduled for {timezone.localtime(record.send_at):%d %b %Y, %I:%M %p}. "
                f"It will go out then whether or not you are signed in.",
            )
            return redirect("alerthub:outgoing_detail", pk=record.pk)

        dispatch(record, force=True)
        if record.status == OutgoingNotification.FAILED:
            messages.error(request, record.error or "Nothing was sent.")
        elif record.status == OutgoingNotification.PARTIAL:
            messages.warning(
                request,
                f"Sent to {record.success_count} of {record.recipient_count} "
                f"recipients. {record.error}",
            )
        else:
            messages.success(
                request,
                f"Notification sent successfully. "
                f"{record.success_count} recipient(s) notified.",
            )
        return redirect("alerthub:outgoing_detail", pk=record.pk)

    return render(request, "alerthub/send_notification.html", {
        "active_tab": "send_notification",
        "form": form,
        "outgoing": outgoing,
        "attachment_extensions": ", ".join(
            e.upper() for e in ATTACHMENT_EXTENSIONS
        ),
        "attachment_max_mb": round(ATTACHMENT_MAX_BYTES / 1024 / 1024),
        # Rendered once so the page can pre-select a category the moment the
        # type changes, without a round trip for something already known.
        "type_defaults": json.dumps({
            key: {"category": category}
            for key, (_module, category) in TYPE_DEFAULTS.items()
        }),
        "recent": (
            OutgoingNotification.objects
            .filter(created_by=request.user)
            .exclude(status=OutgoingNotification.SENT)[:5]
        ),
    })


@login_required(login_url="login")
def send_notification_recipients(request):
    """Live employee list and delivery counts for the Recipients panel.

    The panel re-asks this whenever a hierarchy box is ticked. It exists so the
    picker and the preview cannot drift apart: both are rendered from one
    response, computed by :mod:`alerthub.recipients`, which is the same module
    the save path revalidates against.
    """
    _require_send_permission(request.user)

    def ids(name):
        return [int(v) for v in request.GET.getlist(name) if str(v).lstrip("-").isdigit()]

    branch_ids = ids("branches")
    employees = employee_options(
        sender=request.user,
        companies=ids("companies"),
        branches=branch_ids,
        farms=ids("farms"),
        warehouses=ids("warehouses"),
        departments=ids("departments"),
        designations=ids("designations"),
    )

    # The already-selected people stay in the count even if a narrowed filter
    # no longer lists them — the sender chose them on purpose, and silently
    # dropping someone because a checkbox moved is the bug this avoids.
    chosen = ids("users") or [e["id"] for e in employees]
    preview = delivery_preview(user_ids=chosen, group_ids=ids("groups"))

    return JsonResponse({
        "employees": employees,
        "groups": group_options(),
        # Both cascade from the chosen branches, so the page never offers a
        # farm or a store that belongs to a branch nobody ticked.
        "farms": [
            {"id": f.pk, "name": f.farm_name,
             "branch": f.branch.branch_name if f.branch_id else ""}
            for f in farms_for_branches(request.user, branch_ids)
        ],
        "warehouses": [
            {"id": w.pk, "name": w.name}
            for w in warehouses_for_branches(request.user, branch_ids)
        ],
        "preview": preview,
    })


@login_required(login_url="login")
def outgoing_detail(request, pk):
    """The audit record for one send, and its per-recipient delivery history.

    Delivery and read state are not stored twice: the rows come from
    ``NotificationRecipient``, the same table the bell reads, so "Rahul Singh ·
    Delivered · Read 10:32" is the actual state of his notification rather than
    a log written alongside it that could disagree.
    """
    _require_send_permission(request.user)
    outgoing = get_object_or_404(
        OutgoingNotification.objects.select_related("notification", "created_by"),
        pk=pk,
    )

    deliveries = []
    if outgoing.notification_id:
        deliveries = (
            NotificationRecipient.objects
            .filter(notification_id=outgoing.notification_id)
            .select_related("user")
            .order_by("-is_read", "user__first_name", "user__username")
        )

    return render(request, "alerthub/outgoing_detail.html", {
        "active_tab": "send_notification",
        "outgoing": outgoing,
        "deliveries": deliveries,
    })


@login_required(login_url="login")
@require_POST
def outgoing_cancel(request, pk):
    """Call off a scheduled message before its hour.

    Cancelling is a status, not a delete: "we decided not to send this" is
    itself worth keeping, and a row that vanished would leave the person who
    scheduled it wondering whether it went out.
    """
    _require_send_permission(request.user)
    outgoing = get_object_or_404(OutgoingNotification, pk=pk)

    if outgoing.status != OutgoingNotification.SCHEDULED:
        messages.error(request, "Only a scheduled notification can be cancelled.")
    else:
        outgoing.status = OutgoingNotification.CANCELLED
        outgoing.save(update_fields=["status", "updated_at"])
        messages.success(request, "Cancelled. It will not be sent.")
    return redirect("alerthub:outgoing_detail", pk=outgoing.pk)
