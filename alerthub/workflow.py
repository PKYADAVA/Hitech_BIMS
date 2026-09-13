"""What may be done about an alert, and what happens when it is.

The dashboard's Action Required card is a list of problems somebody has to do
something about, so an alert needs to say more than "raised". It needs to say
whether anybody has picked it up, whether the work is under way, and — when it
goes quiet — whether that was because it was fixed or because it was waved off,
and by whom.

All of that lives here rather than in the view or the template. The rules about
which move follows which, who may make it, and what has to be written down are
business rules; a card and a dialog are how they are reached today, and neither
should be the place they are defined.

Three things are worth stating outright.

**Dismissing requires a reason.** It is the one transition that closes an alert
without anything having been done, and an operational log full of silent
dismissals is worse than no log — it reads like the problems went away.

**Every move is written to** :class:`~alerthub.models.AlertAction` **before the
alert is saved**, inside one transaction. The status is the current answer; the
action rows are how it was arrived at, and the pair must never disagree.

**Resolving is not suppressing.** A resolved alert keeps its measured value,
its threshold and its scope. The detectors' ``dedupe_key`` stops the next scan
re-raising the same thing while it is still open, and a resolved alert whose
underlying condition persists *should* come back — which is the point of
resolving it rather than dismissing it.
"""
from __future__ import annotations

import logging

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .constants import OPEN_STATUSES, AlertStatus
from .models import AlertAction, Notification

logger = logging.getLogger(__name__)

#: status -> the statuses it may move to.
#:
#: Resolved and dismissed are not terminal: a fix that did not hold, or a
#: dismissal made in error, has to be reopenable, and re-raising an alert by
#: hand is not something a supervisor can do. Everything else only moves
#: forward — an alert cannot go from in-progress back to untouched, because
#: nobody can un-know that it was picked up.
TRANSITIONS = {
    AlertStatus.OPEN: {AlertStatus.ACKNOWLEDGED, AlertStatus.IN_PROGRESS,
                       AlertStatus.RESOLVED, AlertStatus.DISMISSED},
    AlertStatus.ACKNOWLEDGED: {AlertStatus.IN_PROGRESS, AlertStatus.RESOLVED,
                               AlertStatus.DISMISSED},
    AlertStatus.IN_PROGRESS: {AlertStatus.RESOLVED, AlertStatus.DISMISSED},
    AlertStatus.RESOLVED: {AlertStatus.OPEN},
    AlertStatus.DISMISSED: {AlertStatus.OPEN},
}

#: The audit word for each destination, when the move is made the ordinary way.
_ACTION_FOR = {
    AlertStatus.ACKNOWLEDGED: AlertAction.ACKNOWLEDGED,
    AlertStatus.IN_PROGRESS: AlertAction.STARTED,
    AlertStatus.RESOLVED: AlertAction.RESOLVED,
    AlertStatus.DISMISSED: AlertAction.DISMISSED,
    AlertStatus.OPEN: AlertAction.REOPENED,
}


class TransitionError(ValidationError):
    """A move the state machine does not allow."""


def can_action(user, alert) -> bool:
    """Whether this user may change this alert's state at all.

    Seeing an alert and answering for it are the same permission here: scoping
    already decides who may see which branches and farms, and an alert somebody
    is shown on their own dashboard is by definition one about their own
    operation. A second, narrower permission would mean a supervisor who is
    shown a problem and cannot say they have picked it up — which is the state
    this widget exists to get rid of.
    """
    if not user or not user.is_authenticated:
        return False
    return Notification.objects.for_user(user).filter(pk=alert.pk).exists()


def _guard(user, alert, target):
    if not can_action(user, alert):
        raise PermissionDenied("This alert is not yours to action.")
    if target not in TRANSITIONS.get(alert.status, set()):
        raise TransitionError(
            "An alert that is %s cannot be marked %s."
            % (AlertStatus(alert.status).label.lower(),
               AlertStatus(target).label.lower())
        )


def _same_problem(alert, user):
    """Every open alert about the same subject as this one, this user's to act on.

    ``dedupe_key`` identifies the *subject* — this feed item at this warehouse,
    this flock's mortality — not the occasion it was noticed. A nightly scan
    raised one row a day for the same subject until the engine was taught not
    to, so a farm carries rows raised before that fix that all say the same
    thing.

    Somebody pressing Mark Resolved has dealt with the problem, not with the
    row. Settling one and leaving its twins on the list is the worst of both:
    the work was done and the dashboard still says it was not.

    Scoped through ``for_user`` so a grouped move can never reach further than
    the person could reach one row at a time.
    """
    if not alert.dedupe_key:
        return [alert]
    rows = (Notification.objects.for_user(user)
            .filter(dedupe_key=alert.dedupe_key, status__in=OPEN_STATUSES)
            .exclude(pk=alert.pk))
    return [alert] + list(rows)


@transaction.atomic
def set_status(alert, target, *, user, note="") -> AlertAction:
    """Move one alert along, and write down that it moved.

    Along with every other open alert about the same subject — see
    :func:`_same_problem`. One press settles the problem; it would be a strange
    dashboard that asked for the same decision three times because the scanner
    had noticed something on three mornings.

    Each row is locked for the length of the transaction. Two people pressing
    Acknowledge on the same alert at the same moment is not unusual on a shared
    dashboard, and without the lock both would read "open", both would pass the
    transition check, and the log would carry two acknowledgements of an alert
    that was only ever picked up once.
    """
    alert = Notification.objects.select_for_update().get(pk=alert.pk)
    target = AlertStatus(target)
    _guard(user, alert, target)

    note = (note or "").strip()
    if target == AlertStatus.DISMISSED and not note:
        raise ValidationError(
            "Say why this is being dismissed. A closed alert with no reason "
            "against it cannot be reviewed later."
        )

    now = timezone.now()
    actor = user if getattr(user, "pk", None) else None
    entry = None

    for row in _same_problem(alert, user):
        # A twin may be at a different point — acknowledged while this one is
        # open — and a move that is legal here may not be legal there. Skip it
        # rather than fail the press: the row that was actually pressed is what
        # the person is waiting on.
        if row.pk != alert.pk and target not in TRANSITIONS.get(row.status, set()):
            continue

        row = Notification.objects.select_for_update().get(pk=row.pk)
        written = AlertAction.objects.create(
            notification=row, action=_ACTION_FOR[target], actor=actor,
            note=note, from_status=row.status, to_status=target,
        )
        if row.pk == alert.pk:
            entry = written

        row.status = target
        row.status_changed_at = now
        row.status_changed_by = actor
        # Reopening clears the old reason rather than leaving it attached to an
        # alert that is open again, where it would read as the reason it is open.
        row.dismiss_reason = note if target == AlertStatus.DISMISSED else ""
        row.save(update_fields=["status", "status_changed_at",
                                "status_changed_by", "dismiss_reason"])

    logger.info("alerthub: alert %s -> %s by %s", alert.pk, target, user)
    return entry


def acknowledge(alert, *, user, note=""):
    """Somebody has seen it and owns it. No work claimed yet."""
    return set_status(alert, AlertStatus.ACKNOWLEDGED, user=user, note=note)


def start(alert, *, user, note=""):
    return set_status(alert, AlertStatus.IN_PROGRESS, user=user, note=note)


def resolve(alert, *, user, note=""):
    return set_status(alert, AlertStatus.RESOLVED, user=user, note=note)


def dismiss(alert, *, user, reason):
    """Close it without acting. ``reason`` is not optional."""
    return set_status(alert, AlertStatus.DISMISSED, user=user, note=reason)


def reopen(alert, *, user, note=""):
    return set_status(alert, AlertStatus.OPEN, user=user, note=note)


# ---------------------------------------------------------------------------
# Notify Supervisor
# ---------------------------------------------------------------------------

def supervisor_candidates(alert):
    """Who this alert could sensibly be escalated to, nearest first.

    An alert about a farm goes to the person responsible for that farm, not to
    a list of everyone in the company — the point of the dialog is to reach the
    one person who can go and look. So the farm's own supervisor comes first,
    then the rest of that branch's, and the list stops there.

    A supervisor with no user account is left out: they cannot be sent an
    in-app notification, and offering a name the message will not reach is a
    promise the dialog does not keep.
    """
    from broiler.models import Supervisor

    rows = (Supervisor.objects
            .select_related("employee", "employee__user", "branch")
            .filter(employee__user__isnull=False, employee__user__is_active=True))

    farm = alert.farm
    if farm is not None:
        rows = rows.filter(branch_id=farm.branch_id)
    elif alert.branch_id:
        rows = rows.filter(branch_id=alert.branch_id)

    own = getattr(farm, "supervisor_id", None)
    people = [{
        "id": sup.employee.user_id,
        "supervisor_id": sup.pk,
        "name": sup.name,
        "role": "Farm supervisor" if sup.pk == own else "Supervisor",
        "branch": str(sup.branch) if sup.branch_id else "",
        "is_owner": sup.pk == own,
    } for sup in rows.order_by("name")]

    # The farm's own supervisor to the top; the rest alphabetical behind them.
    people.sort(key=lambda p: (not p["is_owner"], p["name"]))
    return people


@transaction.atomic
def notify_supervisor(alert, *, user, user_ids, note="") -> AlertAction:
    """Put this alert in front of named people, and record that it was.

    It deliberately does not change the alert's status. Telling somebody about
    a problem is not the same as the problem being picked up, and a widget that
    quietly marked an alert as handled the moment it was forwarded would hide
    exactly the alerts nobody had answered.

    Delivery is the ordinary in-app recipient row — the same one the bell and
    the notification centre read — so an escalated alert turns up in the
    supervisor's own list rather than in a channel built for this dialog alone.
    """
    from django.contrib.auth import get_user_model

    from .models import NotificationRecipient

    if not can_action(user, alert):
        raise PermissionDenied("This alert is not yours to escalate.")

    wanted = []
    for value in (user_ids or []):
        try:
            wanted.append(int(value))
        except (TypeError, ValueError):
            continue
    if not wanted:
        raise ValidationError("Choose at least one person to notify.")

    people = list(get_user_model().objects.filter(pk__in=wanted, is_active=True))
    if not people:
        raise ValidationError("None of those people can be notified.")

    for person in people:
        # get_or_create, not create: the alert may already have gone to this
        # supervisor from the rule that raised it, and the unique constraint
        # would turn a second, deliberate escalation into an error page.
        NotificationRecipient.objects.get_or_create(
            notification=alert, user=person,
            defaults={"delivered_channels": ["in_app"]},
        )

    entry = AlertAction.objects.create(
        notification=alert, action=AlertAction.NOTIFIED, actor=user,
        note=(note or "").strip(),
        notified=[p.get_full_name() or p.get_username() for p in people],
    )
    logger.info("alerthub: alert %s escalated to %s by %s",
                alert.pk, entry.notified, user)
    return entry
