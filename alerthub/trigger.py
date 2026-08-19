"""An outside scheduler's way in to the alert scan.

Most of the conditions this module watches are not events. "A flock reached
harvest age" and "an invoice went overdue" happen because a date passed, with
no row being saved, so something has to come along and look. That something is
``run_alert_scan``, and until now nothing ran it: no cron, no scheduled task,
no worker. Every part of the chain worked and the chain was never started.

This is the trigger, and it is an HTTP endpoint rather than a worker process
because App Platform has no cron of its own — its jobs run on deploy, not on a
clock — and a worker exists only to sleep between fifteen-second bursts of
work. A scheduler that already exists (GitHub Actions, see
``.github/workflows/alert-scan.yml``) calls this instead, and nothing new runs
around the clock to be paid for and watched.

The endpoint is public in the sense that the URL is in a public repository, so
it is the token that protects it and nothing else:

* **Off unless configured.** No ``ALERT_SCAN_TOKEN`` in the environment and the
  view 404s. A deployment that has not been given a token has not opted in.
* **404, not 403, on a bad token.** A wrong secret gets exactly what a wrong
  URL gets, so probing cannot tell the difference between "no such endpoint"
  and "right endpoint, wrong key".
* **Constant-time comparison**, so the answer cannot be found a byte at a time.
* **POST only**, because it does work; a crawler following a link must never
  set off a scan.
"""
from __future__ import annotations

import hmac
import logging

from django.conf import settings
from django.http import Http404, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)

#: Header the scheduler sends the token in. Not the Authorization header:
#: this is not a user, and nothing about the request should look like a login.
TOKEN_HEADER = "HTTP_X_ALERT_SCAN_TOKEN"


def _authorised(request) -> bool:
    expected = (getattr(settings, "ALERT_SCAN_TOKEN", "") or "").strip()
    if not expected:
        return False
    given = (request.META.get(TOKEN_HEADER) or "").strip()
    return bool(given) and hmac.compare_digest(given, expected)


@csrf_exempt
@require_POST
def run_scan(request):
    """POST /tasks/alert-scan/ — evaluate the active rules once.

    Returns the same counts the management command prints, so a scheduler's
    log says what happened without anyone opening the app. Runs the scan in
    the request rather than handing it off: there is no worker to hand it to,
    the rules take seconds, and the per-rule cooldown means a slow run
    overlapping the next one costs duplicated work rather than duplicated
    alerts.
    """
    from .services import scan

    if not _authorised(request):
        raise Http404

    result = scan()
    logger.info("alert scan via trigger: %s", result.summary())
    return JsonResponse({
        "ok": True,
        "summary": result.summary(),
        "rules_run": result.rules_run,
        "alerts": result.raised,
        "failed": sorted(set(result.failed)),
        "skipped_unsupported": sorted(set(result.skipped_unsupported)),
        "skipped_no_detector": sorted(set(result.skipped_no_detector)),
    })
