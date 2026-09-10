"""An outside scheduler's way in to routine cleanup.

``IdempotencyRecord`` keeps one row per keyed write so a duplicate can be
answered without doing the work twice. The rows stop being useful once no
client could still be retrying — the phone's outbox gives up long before a week
is out — and until now nothing ever removed them. That was tolerable while only
the phone's queued writes left rows behind. The ERP's own saves carry a key
now, so the table grows with everyday use rather than with offline sync.

An HTTP endpoint rather than a worker, for the same reason the alert scan is
one: App Platform has no cron, its jobs run on deploy rather than on a clock,
and a worker would exist only to sleep between a few seconds of work once a
week. A scheduler that already exists calls this instead — see
``.github/workflows/purge-idempotency.yml``.

Guarded exactly as the alert scan is, and by the same token:

* **Off unless configured.** No ``ALERT_SCAN_TOKEN`` and the view 404s. A
  deployment that was never given a token never asked for a scheduler.
* **404, not 403, on a bad token**, so probing cannot tell a wrong key from a
  wrong URL.
* **Constant-time comparison**, so the answer cannot be found a byte at a time.
* **POST only**, because it deletes things.

One token for both tasks on purpose. A second secret is a second thing to set,
and the history of the first one — green runs that quietly did nothing for
weeks because it was unset — is the argument against adding another. What the
token grants stays of one kind: routine maintenance nobody has to think about,
never anything that reads or writes business data.
"""
from __future__ import annotations

import hmac
import logging

from django.conf import settings
from django.http import Http404, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)

#: Header the scheduler sends the token in. Not Authorization: this is not a
#: user, and nothing about the request should look like a login.
TOKEN_HEADER = "HTTP_X_ALERT_SCAN_TOKEN"

#: Keys younger than this may still be retried, so they stay.
DEFAULT_DAYS = 7


def _authorised(request) -> bool:
    expected = (getattr(settings, "ALERT_SCAN_TOKEN", "") or "").strip()
    if not expected:
        return False
    given = (request.META.get(TOKEN_HEADER) or "").strip()
    return bool(given) and hmac.compare_digest(given, expected)


@csrf_exempt
@require_POST
def purge_idempotency(request):
    """POST /tasks/purge-idempotency/ — drop keys nobody could still be using.

    Reports what went and what is left, so the scheduler's own log answers
    "is this working?" without anyone opening the app.

    ``?days=`` overrides the window. Anything unreadable falls back to the
    default rather than failing: a scheduler that mistypes a number should
    still get its cleanup, and the only cost of too generous a window is rows
    that live a little longer.
    """
    from api.middleware import purge_idempotency_records
    from api.models import IdempotencyRecord

    if not _authorised(request):
        raise Http404

    try:
        days = int(request.GET.get("days", DEFAULT_DAYS))
    except (TypeError, ValueError):
        days = DEFAULT_DAYS
    days = max(days, 1)          # never let a stray 0 purge keys still in use

    deleted = purge_idempotency_records(days)
    remaining = IdempotencyRecord.objects.count()
    logger.info("idempotency purge: deleted %d, %d remain", deleted, remaining)
    return JsonResponse({"ok": True, "deleted": deleted,
                         "remaining": remaining, "days": days})
