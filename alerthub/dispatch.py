"""Turning a composed message into a delivered one.

:class:`OutgoingNotification` is the composition; :class:`Notification` is the
delivery. This module is the single step between them, and it is the only place
that step happens — the page, the confirmation dialog and the scheduled-send
command all call :func:`dispatch`, so a message sent by hand at 9am and one that
fired from the schedule at 6pm went out through identical code.

It reuses the notification infrastructure that already exists rather than
building a second one:

* ``Notification`` + ``NotificationRecipient`` — the same rows the automatic
  alerts write, so a manual message lands in the ERP notification centre, the
  bell and the mobile app's list with no special case anywhere downstream.
* :mod:`alerthub.push` — the same Expo transport, respecting the same per-user
  Mobile Push opt-out.

Nothing here decides who *may* be notified; that was settled when the sender
picked the list, against the Employee Organization Access master.
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from .constants import Channel
from .engine import MANUAL_RULE_KEY
from .models import Notification, NotificationRecipient, OutgoingNotification

logger = logging.getLogger(__name__)


def dispatch(outgoing: OutgoingNotification, *, force: bool = False) -> OutgoingNotification:
    """Send one composed message now, and record what happened.

    Returns the same row, updated. It never raises for a delivery failure: a
    message that could not reach anyone is a ``FAILED`` row with a reason on it,
    which the page can show, rather than a traceback that loses the composition
    along with the error.

    ``force`` sends a row that is still scheduled for later — what the Send Now
    button on a scheduled message means.
    """
    if outgoing.status in OutgoingNotification.TERMINAL:
        # Re-sending is not a repair. A second delivery would double every
        # recipient's bell and make the audit row lie about how many people
        # were told, so an already-finished send is left exactly as it is.
        logger.info(
            "alerthub: dispatch skipped, %s is already %s",
            outgoing.pk, outgoing.status,
        )
        return outgoing

    if not force and outgoing.status == OutgoingNotification.SCHEDULED \
            and not outgoing.is_due:
        return outgoing

    people = outgoing.resolve_recipients()
    if not people:
        return _finish(
            outgoing, OutgoingNotification.FAILED, 0, 0, 0,
            error="No eligible recipients — everyone selected is inactive or "
                  "was removed.",
        )

    try:
        notification = _deliver(outgoing, people)
    except Exception as exc:                       # pragma: no cover - defensive
        logger.exception("alerthub: dispatch failed for outgoing %s", outgoing.pk)
        return _finish(
            outgoing, OutgoingNotification.FAILED, len(people), 0, len(people),
            error=str(exc)[:300],
        )

    delivered = notification.recipients.count()
    failed = len(people) - delivered
    status = (OutgoingNotification.SENT if failed == 0
              else OutgoingNotification.PARTIAL)
    outgoing.notification = notification
    return _finish(
        outgoing, status, len(people), delivered, failed,
        error="" if failed == 0 else f"{failed} recipient row(s) could not be written.",
    )


def _deliver(outgoing: OutgoingNotification, people) -> Notification:
    """Write the notification and its recipient rows, then push after commit."""
    from .push import push_recipients, send_alert_push

    with transaction.atomic():
        notification = Notification.objects.create(
            rule=None,
            rule_key=MANUAL_RULE_KEY,
            module=outgoing.module,
            category=outgoing.category,
            priority=outgoing.priority,
            title=outgoing.title[:200],
            message=outgoing.message,
            created_by=outgoing.created_by,
            # The same stored file, not a copy: assigning the name points the
            # notification at the object the draft already uploaded, so nothing
            # is re-uploaded and there is one file to delete, not two.
            attachment=outgoing.attachment.name if outgoing.attachment else None,
            # A single branch/farm on the notification is what the scope
            # columns can hold; recording it when exactly one was chosen keeps
            # the centre's place filter working without pretending a
            # three-branch send belongs to one of them.
            branch=_single(outgoing.branches),
            farm=_single(outgoing.farms),
            warehouse=_single(outgoing.warehouses),
            metadata={
                "outgoing_id": outgoing.pk,
                "notification_type": outgoing.notification_type,
            },
        )

        wanted = push_recipients(None, people)
        channels = [Channel.IN_APP] + ([Channel.PUSH] if wanted else [])
        NotificationRecipient.objects.bulk_create(
            [
                NotificationRecipient(
                    notification=notification, user=user,
                    delivered_channels=channels,
                )
                for user in people
            ],
            ignore_conflicts=True,
        )

        if wanted:
            # A push cannot be recalled, so it must not go out for a
            # notification whose transaction then rolls back.
            transaction.on_commit(
                lambda n=notification, w=wanted: send_alert_push(n, w)
            )

    logger.info(
        "alerthub: outgoing %s delivered as notification %s to %s user(s)",
        outgoing.pk, notification.pk, len(people),
    )
    return notification


def _finish(outgoing, status, total, success, failed, error=""):
    outgoing.status = status
    outgoing.recipient_count = total
    outgoing.success_count = success
    outgoing.failed_count = failed
    outgoing.error = error
    outgoing.sent_at = timezone.now()
    outgoing.save(update_fields=[
        "status", "recipient_count", "success_count", "failed_count",
        "error", "sent_at", "notification", "updated_at",
    ])
    return outgoing


def _single(manager):
    """The one object chosen, or None when none or several were.

    "Several" deliberately returns None rather than the first: a notification
    stamped with one of three branches would filter into that branch's list and
    silently out of the other two.
    """
    rows = list(manager.all()[:2])
    return rows[0] if len(rows) == 1 else None


def send_due(now=None, limit: int = 200) -> list[OutgoingNotification]:
    """Dispatch every scheduled message whose hour has come.

    Called by the ``send_scheduled_notifications`` management command. Rows are
    claimed by flipping them to ``SENDING`` in a single UPDATE before any work
    starts, so two overlapping runs of the command cannot both send the same
    message — the second finds nothing left to claim.
    """
    now = now or timezone.now()
    due_ids = list(
        OutgoingNotification.objects
        .filter(status=OutgoingNotification.SCHEDULED, send_at__lte=now)
        .order_by("send_at")
        .values_list("id", flat=True)[:limit]
    )
    if not due_ids:
        return []

    claimed = OutgoingNotification.objects.filter(
        id__in=due_ids, status=OutgoingNotification.SCHEDULED
    ).update(status=OutgoingNotification.SENDING)
    logger.info("alerthub: claimed %s scheduled notification(s)", claimed)

    done = []
    for outgoing in OutgoingNotification.objects.filter(
        id__in=due_ids, status=OutgoingNotification.SENDING
    ):
        done.append(dispatch(outgoing, force=True))
    return done
