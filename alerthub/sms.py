"""SMS transport for business alerts.

The same join ``push.py`` describes, for the channel next to it. Alerthub has
modelled an SMS channel since it was written and refused to use it, because
``LIVE_CHANNELS`` had no transport behind it — while the notification app has a
working gateway with messages already sent through it. Both halves existed and
had never been joined.

It follows push's contract exactly, and for the same reasons:

* **It sends to the alert's own audience, never broadcasts.** The recipients
  are the users ``scoping.audience_for`` already resolved, so a message can
  only reach someone who could have opened the alert in the bell.
* **It sends after commit**, handed there by the engine. A text cannot be
  recalled, so it must not go out for a notification whose transaction then
  rolls back.
* **It never raises.** Alerting is a side effect of business work; a dead
  gateway must not be the reason a daily entry fails to save.

One thing differs from push, and it is the reason this channel should be turned
on deliberately rather than by default: a push costs nothing and an SMS costs
money per message. The rule decides whether to ask for SMS at all, and the
recipient's preference can still refuse it.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: A gateway charges by the segment, and an alert is a notice, not a report.
#: The bell carries the full text; this carries enough to act on.
_BODY_LIMIT = 300


def phone_numbers_for(users) -> list[str]:
    """Mobile numbers belonging to these users, de-duplicated.

    A login reaches a number through the employee record it belongs to —
    ``Employee.user`` — because that is where the ERP keeps a person's phone.
    A user with no employee record, or an employee with no number, is skipped
    rather than guessed at: an alert sent to the wrong handset is worse than
    one that stayed in the bell.
    """
    from hr.models import Employee

    user_ids = [u.pk for u in users if getattr(u, "pk", None)]
    if not user_ids:
        return []
    # personal_contact is a PositiveBigIntegerField, so a missing number is
    # NULL — there is no empty string to exclude, and the value arrives as an
    # int that the gateway wants as text.
    numbers = (Employee.objects
               .filter(user_id__in=user_ids)
               .exclude(personal_contact__isnull=True)
               .values_list("personal_contact", flat=True)
               .distinct())
    return [str(n).strip() for n in numbers if str(n or "").strip()]


def sms_recipients(rule, recipients):
    """The subset of `recipients` who have asked for SMS on this rule.

    Opt *in*, where push is opt out, and the difference is the money. A
    preference row is only written when someone opens the settings page, so
    under push's rule — everyone not recorded as refusing — a user who has
    never expressed a view would be texted. That is the right default for a
    free push and the wrong one for a message that costs per send, so this
    asks for a recorded yes.
    """
    from .models import NotificationPreference

    asked_for_it = set(
        NotificationPreference.objects
        .filter(user__in=recipients, receive_sms=True)
        .values_list("user_id", flat=True)
    )
    return [u for u in recipients if u.pk in asked_for_it]


def send_alert_sms(notification, recipients) -> int:
    """Text one alert to its recipients. Returns the number of messages sent.

    Returns 0 — rather than raising — when there is nobody to reach, no number
    on file, or the gateway refuses.
    """
    from notification.services.sms_service import SmsService

    try:
        numbers = phone_numbers_for(recipients)
        if not numbers:
            logger.debug("alerthub: no mobile numbers for notification %s",
                         notification.pk)
            return 0

        title = (notification.title or "Hitech BIMS").strip()
        body = (notification.message or "").strip()
        text = f"{title}: {body}" if body else title
        text = text[:_BODY_LIMIT]

        sent = 0
        with SmsService() as service:
            for number in numbers:
                result = service.send_sms(number, text)
                # The service reports rather than raises, so a refusal for one
                # recipient must not cost the rest theirs.
                if getattr(result, "success", False):
                    sent += 1
                else:
                    logger.info("alerthub: SMS to one recipient not sent for "
                                "notification %s: %s", notification.pk,
                                getattr(result, "error", "no reason given"))
        logger.info("alerthub: texted notification %s to %s recipient(s)",
                    notification.pk, sent)
        return sent
    except Exception:
        logger.exception("alerthub: SMS delivery failed for notification %s",
                         getattr(notification, "pk", None))
        return 0
