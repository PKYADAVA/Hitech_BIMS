"""Mobile push transport for business alerts.

The two halves of this already existed and had never been joined: the phone
registers an Expo token with ``/devices/register`` (``notification.DeviceToken``)
and ``notification.push.send_push`` talks to Expo's HTTP API, while alerthub
modelled a ``PUSH`` channel it had no transport for. This is the join.

Three things this module is careful about:

* **It sends to the alert's own audience, never broadcasts.** The recipients
  are the users ``scoping.audience_for`` already resolved, so a push can only
  reach someone who could have opened the alert in the bell.
* **It sends after commit.** A push cannot be recalled, so it must not go out
  for a notification whose transaction then rolls back.
* **It never raises.** Alerting is a side effect of business work; a dead
  network must not be the reason a daily entry fails to save.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Expo rejects oversized payloads, and a lock-screen line is short anyway.
_BODY_LIMIT = 178


def device_tokens_for(users) -> list[str]:
    """Expo tokens belonging to these users, de-duplicated.

    One person may carry two phones, and one phone may have been handed to
    another supervisor — ``DeviceToken`` is keyed by token and reassigned on
    login, so asking by user is what keeps a push off the previous owner's
    handset.
    """
    from notification.models import DeviceToken

    user_ids = [u.pk for u in users if getattr(u, "pk", None)]
    if not user_ids:
        return []
    return list(
        DeviceToken.objects.filter(user_id__in=user_ids)
        .values_list("token", flat=True)
        .distinct()
    )


def push_recipients(rule, recipients):
    """The subset of `recipients` who accept push for this rule.

    A user preference can only ever narrow what the rule asked for, the same
    contract the other channels follow.
    """
    from .models import NotificationPreference

    opted_out = set(
        NotificationPreference.objects
        .filter(user__in=recipients, receive_push=False)
        .values_list("user_id", flat=True)
    )
    return [u for u in recipients if u.pk not in opted_out]


def send_alert_push(notification, recipients) -> int:
    """Push one alert to its recipients' devices. Returns tokens sent to.

    Returns 0 — rather than raising — when there is nobody to reach, no device
    registered, or the send fails outright.
    """
    from notification.push import send_push

    try:
        tokens = device_tokens_for(recipients)
        if not tokens:
            logger.debug("alerthub: no devices for notification %s", notification.pk)
            return 0

        body = (notification.message or "")[:_BODY_LIMIT]
        result = send_push(
            tokens,
            notification.title or "Hitech BIMS",
            body,
            # Enough for the app to open the right thing when the push is
            # tapped, without shipping the whole record through Expo.
            data={
                "type": "alert",
                "notification_id": notification.pk,
                "module": notification.module,
                "priority": notification.priority,
            },
        )
        sent = (result or {}).get("sent", 0)
        logger.info(
            "alerthub: pushed notification %s to %s device(s)", notification.pk, sent
        )
        return sent
    except Exception:
        # Same rule as the engine: alerting must never break the work that
        # triggered it, and a push that failed is not worth a 500.
        logger.exception(
            "alerthub: push delivery failed for notification %s",
            getattr(notification, "pk", None),
        )
        return 0
