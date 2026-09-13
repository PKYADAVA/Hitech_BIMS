"""Raising an alert: deduplication, fan-out and delivery.

Every alert in the system is born here. Detectors describe *what* they found;
this module decides whether it is new, who hears about it, and on which
channels.

**Deduplication is the whole reason a scanner is usable.** A rule watching
mortality re-detects the same breach every time it runs. Without a cooldown, a
15-minute scan turns one bad day into 96 identical notifications and the feed
becomes unreadable — which is the failure mode that made the previous alert feed
worthless. Detectors supply a ``dedupe_key`` identifying the *subject* of the
alert ("this rule, this batch, this day"), and a repeat inside the rule's
cooldown window is dropped.

**Failure is contained.** ``raise_alert`` never lets an alerting problem break
the thing that triggered it; a detector that explodes must not roll back a stock
transfer. Callers get ``None`` and the traceback goes to the log.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from .constants import (Channel, LIVE_CHANNELS, Module, OPEN_STATUSES,
                        AlertStatus, Operator, Priority)
from .push import push_recipients, send_alert_push
from .sms import send_alert_sms, sms_recipients
from .models import Notification, NotificationRecipient
from .scoping import audience_for

logger = logging.getLogger(__name__)


def raise_alert(
    rule,
    *,
    title,
    message="",
    dedupe_key,
    priority=None,
    branch=None,
    org_centre=None,
    farm=None,
    warehouse=None,
    object_label="",
    object_id="",
    object_display="",
    voucher_no="",
    action_url="",
    measured_value=None,
    threshold_value=None,
    metadata=None,
    created_by=None,
):
    """Raise one alert under ``rule``, unless an equivalent one is still fresh.

    Returns the :class:`~alerthub.models.Notification`, or ``None`` when the
    alert was suppressed by the cooldown, had no audience, or failed.

    An alert with no audience is not written at all. A notification nobody can
    read is not a record of anything — it would inflate the history and every
    "unread" count computed from it while telling no one.
    """
    try:
        if (_still_unanswered(rule, dedupe_key)
                or _waved_off_and_no_worse(rule, dedupe_key, measured_value)
                or _recently_raised(rule, dedupe_key)):
            return None

        notification = Notification(
            rule=rule,
            rule_key=rule.rule_key,
            module=rule.module,
            priority=priority or rule.priority,
            title=title[:200],
            message=message,
            branch=branch,
            org_centre=org_centre,
            farm=farm,
            warehouse=warehouse,
            object_label=object_label,
            object_id=str(object_id or ""),
            object_display=object_display[:255],
            voucher_no=voucher_no[:60],
            action_url=action_url,
            measured_value=measured_value,
            threshold_value=threshold_value,
            metadata=metadata or {},
            dedupe_key=dedupe_key[:255],
            created_by=created_by,
        )

        # Audience is resolved before the write so an alert with no recipients
        # costs nothing. It needs the unsaved instance's scope columns only,
        # which are already set.
        recipients = audience_for(rule, notification)
        if not recipients:
            logger.debug("alerthub: no audience for %s (%s)", rule.name, dedupe_key)
            return None

        with transaction.atomic():
            notification.save()
            delivered = _deliver(rule, notification, recipients)
            NotificationRecipient.objects.bulk_create(
                [
                    NotificationRecipient(
                        notification=notification,
                        user=user,
                        delivered_channels=delivered,
                    )
                    for user in recipients
                ],
                ignore_conflicts=True,
            )
        return notification

    except Exception:
        # Deliberately broad: alerting is a side effect of business work and
        # must never be the reason a save fails.
        logger.exception("alerthub: failed to raise alert for rule %s", rule.pk)
        return None


def _still_unanswered(rule, dedupe_key) -> bool:
    """Whether this exact problem is already on somebody's list, unresolved.

    The cooldown alone was not enough. It asks "was this raised recently",
    which a nightly scan answers "no" every morning — so one unaddressed
    problem became a row a day. Three days of that turned ten real problems
    into twenty-nine alerts, and the dashboard's worklist read as though the
    farms had three times the trouble they had.

    Raising a second row changes nothing for anybody: the first is still
    there, still says the same thing, and now has to be resolved twice. So an
    open, acknowledged or in-progress alert for the same subject suppresses
    the next one outright, however long ago it was raised.

    Resolved and dismissed deliberately do not suppress. A problem somebody
    dealt with that the scanner can still see is news, and the cooldown below
    is what decides how soon it may be said again.

    A rule with no cooldown has opted out of deduplication altogether — it
    watches genuinely distinct events, a duplicate invoice or a bounced
    cheque, where the second occurrence is a second thing that happened and
    not another sighting of the first. This must not quietly overrule that.
    """
    if not rule.cooldown_hours:
        return False
    if not dedupe_key:
        # Hand-composed messages carry no key. Two of them are two messages.
        return False
    return Notification.objects.filter(
        dedupe_key=dedupe_key[:255], status__in=OPEN_STATUSES
    ).exists()


#: How much worse a waved-off measurement has to get before it is worth saying
#: again, as a fraction of the value at the time it was waved off.
#:
#: Some margin is needed or the answer is noise: feed cover drifting from 2.90
#: days to 2.89 is the same situation measured twice, and re-raising on that
#: would have somebody dismissing the same alert every morning — which is how a
#: dismissal button stops being used and the alert stops being read.
DISMISSAL_TOLERANCE = Decimal("0.05")

#: Operators where a bigger number is a worse situation. Mortality over a
#: limit, days since the last entry. The rest — low stock, days of cover, body
#: weight under standard — are worse as they fall.
_WORSE_WHEN_HIGHER = {Operator.GT, Operator.GTE}
_WORSE_WHEN_LOWER = {Operator.LT, Operator.LTE}


def _waved_off_and_no_worse(rule, dedupe_key, measured_value) -> bool:
    """Whether somebody has already judged this not worth acting on.

    Dismissing is the one move that closes an alert with nothing done, and it
    costs a typed reason — "stock arrived this morning, the entry is going in
    today". Raising the same thing again tomorrow ignores that judgement and
    asks for it a second time, which makes the reason box pointless.

    So a dismissal holds until the situation actually deteriorates. Not until
    the condition clears — it never cleared, that is why it had to be
    dismissed rather than resolved — but until the number moves meaningfully
    in the bad direction, which is the point at which the earlier judgement
    was about something else.

    Which direction is bad comes from the rule's own operator, so a rule
    watching mortality climb and one watching feed cover fall are both
    handled without either being named here. When the direction cannot be
    worked out, or either measurement is missing, this declines to guess and
    lets the cooldown decide as before.
    """
    if not dedupe_key:
        return False

    if rule.operator in _WORSE_WHEN_HIGHER:
        worse_when_higher = True
    elif rule.operator in _WORSE_WHEN_LOWER:
        worse_when_higher = False
    else:
        # "Equal to" has no worse. A duplicate invoice number either matches
        # or does not, and there is no scale to have moved along.
        return False

    latest = (Notification.objects
              .filter(dedupe_key=dedupe_key[:255], status=AlertStatus.DISMISSED)
              .order_by("-status_changed_at", "-id").first())
    if latest is None or latest.measured_value is None or measured_value is None:
        return False

    was = latest.measured_value
    try:
        now = Decimal(str(measured_value))
    except (InvalidOperation, TypeError, ValueError):
        return False

    margin = abs(was) * DISMISSAL_TOLERANCE
    if worse_when_higher:
        return now <= was + margin
    return now >= was - margin


def _recently_raised(rule, dedupe_key) -> bool:
    """Whether this exact alert was already raised inside the cooldown window.

    A cooldown of 0 disables suppression, which is what a rule watching
    genuinely distinct events (a duplicate invoice, a bounced cheque) wants.
    """
    if not rule.cooldown_hours:
        return False
    since = timezone.now() - timedelta(hours=rule.cooldown_hours)
    return Notification.objects.filter(
        dedupe_key=dedupe_key, created_at__gte=since
    ).exists()


def _deliver(rule, notification, recipients) -> list[str]:
    """Send on every channel the rule asked for that has a transport.

    Returns the channels actually delivered. In-app is the database row itself,
    so it is delivered by definition. The rest are recorded as requested and
    logged, because claiming an SMS went out when no gateway was called is the
    one thing a notification history must never do.

    Push is the one channel that reaches outside the database, so it is handed
    to ``transaction.on_commit``: a push cannot be recalled, and firing one for
    a notification whose transaction then rolls back would tell a supervisor
    about an alert that does not exist.
    """
    delivered = []
    for channel in rule.channels:
        if channel not in LIVE_CHANNELS:
            logger.info(
                "alerthub: %s delivery requested by rule %s but no transport is "
                "wired; recorded as in-app only.", channel, rule.pk,
            )
            continue

        if channel == Channel.PUSH:
            wanted = push_recipients(rule, recipients)
            if not wanted:
                # Everyone asked for it turned push off; recording it as
                # delivered would be a claim about phones nothing was sent to.
                continue
            transaction.on_commit(
                lambda n=notification, w=wanted: send_alert_push(n, w)
            )

        if channel == Channel.SMS:
            wanted = sms_recipients(rule, recipients)
            if not wanted:
                # Everyone asked for it turned SMS off. Recording it as
                # delivered would be a claim about messages nobody was sent.
                continue
            transaction.on_commit(
                lambda n=notification, w=wanted: send_alert_sms(n, w)
            )
        delivered.append(channel)

    return delivered or [Channel.IN_APP]


def mark_read(user, notification_ids=None) -> int:
    """Mark a user's notifications read. ``None`` means all of theirs.

    Only ever touches rows belonging to ``user`` — read state is personal, and
    an id from a request body is not permission to clear someone else's badge.
    """
    rows = NotificationRecipient.objects.filter(user=user, is_read=False)
    if notification_ids is not None:
        rows = rows.filter(notification_id__in=notification_ids)
    return rows.update(is_read=True, read_at=timezone.now())


def unread_count(user) -> int:
    """Unread notifications this user may currently see.

    Goes through the scoped queryset rather than counting recipient rows
    directly, so the badge can never claim a number larger than the list the
    user is able to open.
    """
    return (
        Notification.objects.for_user(user)
        # Cleared ones are off this user's list, so they must not keep the
        # badge lit — a count you cannot reach by opening the list is a badge
        # nobody can ever clear.
        .filter(recipients__user=user, recipients__is_read=False,
                recipients__is_dismissed=False)
        .count()
    )


#: Rule key stamped on notifications a person sent by hand. It is not a rule —
#: nothing raises it on a schedule — but the column is indexed and every read
#: path groups by it, so a manual send needs one of its own to be filterable.
#:
#: Sending one is :mod:`alerthub.dispatch`, not this module. Composing a message
#: by hand and detecting a breached threshold are different jobs, and the one
#: thing they must share — writing the notification and its recipient rows — is
#: shared by both calling the same models, not by a second sender living here.
MANUAL_RULE_KEY = "manual"
