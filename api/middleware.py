import logging

from django.db import IntegrityError, transaction
from django.http import HttpResponse, JsonResponse

from .models import IdempotencyRecord

logger = logging.getLogger(__name__)

HEADER = "HTTP_IDEMPOTENCY_KEY"
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
API_PREFIX = "/api/"


def _requesting_user(request):
    """Who is making this call, before DRF has had a chance to say.

    Middleware runs ahead of the view, so ``request.user`` is still anonymous
    for a bearer token — DRF authenticates inside the view. The phone uses
    bearer tokens for everything, so reading ``request.user`` alone would mean
    this never applied to the one client it exists for. The token is resolved
    here instead, and the session user is accepted too so the same guarantee
    holds if the browser ever posts a key.

    A bad or expired token returns None: the view is about to reject it, and
    refusing it here as well would only change the error the phone sees.
    """
    from rest_framework_simplejwt.authentication import JWTAuthentication

    try:
        resolved = JWTAuthentication().authenticate(request)
    except Exception:
        return None
    if resolved:
        return resolved[0]
    user = getattr(request, "user", None)
    return user if (user and user.is_authenticated) else None


class IdempotencyMiddleware:
    """Performs a keyed write once, however many times the phone sends it.

    The phone queues writes made with no signal and replays them on reconnect.
    A replay cannot tell "never arrived" from "arrived, and the answer was lost
    on the way back" — so without this, coming back into signal files the same
    day's entry twice, and a duplicated mortality figure moves stock.

    Only requests carrying an ``Idempotency-Key`` are treated this way. The web
    ERP sends none and is untouched; so is every GET, which is already
    repeatable.

    Two requests with one key can be in flight at once — a retry fired while
    the first is still climbing a slow rural link. The unique constraint lets
    exactly one of them through, and the loser is told to retry rather than
    being allowed to double-post or being served a half-written answer.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        key = request.META.get(HEADER, "").strip()
        if (not key or request.method not in UNSAFE
                or not request.path.startswith(API_PREFIX)):
            return self.get_response(request)

        user = _requesting_user(request)
        if user is None:
            return self.get_response(request)

        key = key[:100]
        try:
            with transaction.atomic():
                record = IdempotencyRecord.objects.create(
                    key=key, user=user, method=request.method,
                    path=request.path[:500])
        except IntegrityError:
            return self._already_seen(key, user)

        try:
            response = self.get_response(request)
        except Exception:
            # The view blew up, so nothing is settled. Leaving the record in
            # place with no response would answer every retry with "still
            # running" for ever, which is worse than the error itself.
            IdempotencyRecord.objects.filter(pk=record.pk).delete()
            raise
        self._remember(record, response)
        return response

    # -- replay ------------------------------------------------------------

    def _already_seen(self, key, user):
        """Answer a key that has been used before, or say it is still running."""
        record = IdempotencyRecord.objects.filter(user=user, key=key).first()
        if record is None or record.status_code is None:
            # Either still in flight, or deleted between the collision and this
            # read. Asking the phone to retry is safer than doing the work
            # twice, and the outbox will come back to it.
            return self._in_progress()

        replay = HttpResponse(record.response or "", status=record.status_code,
                              content_type="application/json")
        # Says the write was not performed again, so a reader of the logs is
        # not left thinking the phone posted twice and got away with it.
        replay["Idempotent-Replay"] = "true"
        return replay

    @staticmethod
    def _in_progress():
        return JsonResponse(
            {"error": {"code": "idempotency_in_progress",
                       "message": "An identical request is still being processed.",
                       "fields": {}}},
            status=409)

    # -- recording ---------------------------------------------------------

    @staticmethod
    def _remember(record, response):
        """Store the answer, so a replay can be given it.

        Only settled outcomes are kept. A 5xx may well have left nothing
        behind, and storing it would answer the retry with the failure instead
        of letting it do the work — so the record is dropped and the key
        becomes usable again. Client errors *are* kept: a 400 is a verdict on
        the payload and will not change on a second try.
        """
        if response.status_code >= 500:
            IdempotencyRecord.objects.filter(pk=record.pk).delete()
            return
        body = ""
        if not getattr(response, "streaming", False):
            try:
                body = response.content.decode(response.charset or "utf-8")
            except (UnicodeDecodeError, AttributeError):
                logger.warning("idempotency: response for %s is not text; storing empty",
                               record.key)
        IdempotencyRecord.objects.filter(pk=record.pk).update(
            status_code=response.status_code, response=body)


def purge_idempotency_records(older_than_days=7):
    """Drop keys old enough that no phone could still be holding them.

    The outbox gives up on a write long before this, so anything still here is
    a record of work already done and acknowledged.
    """
    from datetime import timedelta

    from django.utils import timezone

    cutoff = timezone.now() - timedelta(days=older_than_days)
    deleted, _ = IdempotencyRecord.objects.filter(created_at__lt=cutoff).delete()
    return deleted
