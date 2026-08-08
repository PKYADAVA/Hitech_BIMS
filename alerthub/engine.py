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

from django.db import transaction
from django.utils import timezone

from .constants import Channel, LIVE_CHANNELS, Module, Priority
from .push import push_recipients, send_alert_push
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
        if _recently_raised(rule, dedupe_key):
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
MANUAL_RULE_KEY = "manual"


def send_manual_notification(
    *,
    sender,
    recipients,
    title,
    message="",
    priority=Priority.MEDIUM,
    module=Module.SYSTEM,
):
    """Send one notification, composed by a person, to named users.

    Unlike :func:`raise_alert` there is no rule: nobody configured this and
    nothing will raise it again, so there is no cooldown to respect and no
    audience to resolve — the sender chose the recipients themselves.

    What it deliberately keeps from the alert path:

    * It writes a real ``Notification`` with real recipient rows, so it lands in
      the bell, the notification centre and the history like anything else. A
      message that only existed as a push would be gone the moment it was
      swiped away, with no record it was ever sent.
    * It respects each user's push preference. Someone who turned Mobile Push
      off still gets it in their bell — the opt-out narrows the channel, never
      the message.
    * The push goes out on commit, for the same reason alerts do.

    Returns the ``Notification``, or ``None`` if there was nobody to send to.
    """
    from .push import push_recipients, send_alert_push

    people = [u for u in recipients if getattr(u, "is_active", True)]
    if not people or not title:
        return None

    with transaction.atomic():
        notification = Notification.objects.create(
            rule=None,
            rule_key=MANUAL_RULE_KEY,
            module=module,
            priority=priority,
            title=title[:200],
            message=message,
            created_by=sender if getattr(sender, "pk", None) else None,
        )
        wanted = push_recipients(None, people)
        channels = [Channel.IN_APP] + ([Channel.PUSH] if wanted else [])
        NotificationRecipient.objects.bulk_create(
            [
                NotificationRecipient(
                    notification=notification, user=user, delivered_channels=channels,
                )
                for user in people
            ],
            ignore_conflicts=True,
        )
        if wanted:
            transaction.on_commit(
                lambda n=notification, w=wanted: send_alert_push(n, w)
            )

    logger.info(
        "alerthub: manual notification %s sent to %s user(s) by %s",
        notification.pk, len(people), getattr(sender, "username", "?"),
    )
    return notification
