"""Retry helper for transient provider failures.

Only :class:`~tracking.exceptions.TrackingTransientError` is retried;
permanent errors (bad request, rejected credentials, unknown endpoint)
propagate on the first attempt so a misconfiguration is never hammered.
Mirrors ``notification.retry``.
"""

import logging
import time

from ..exceptions import TrackingTransientError

logger = logging.getLogger("tracking.sync")


def call_with_retry(func, max_retries=2, backoff=1.0, sleep=time.sleep):
    """Invoke ``func`` retrying transient failures with exponential backoff.

    Args:
        func: Zero-argument callable performing one fetch attempt.
        max_retries: Number of *additional* attempts after the first.
        backoff: Base delay in seconds; attempt ``n`` waits ``backoff * 2**n``.
        sleep: Injectable sleep function (kept out of the way in tests).

    Returns:
        ``(result, retries_used)`` from the first successful attempt.

    Raises:
        The last :class:`TrackingTransientError` if every attempt fails, or
        any non-transient exception immediately.
    """
    attempts = max(max_retries, 0) + 1
    last_error = None
    for attempt in range(attempts):
        try:
            return func(), attempt
        except TrackingTransientError as exc:
            last_error = exc
            if attempt + 1 >= attempts:
                break
            delay = backoff * (2 ** attempt)
            logger.warning(
                "Transient tracking failure (attempt %d/%d); retrying in %.2fs: %s",
                attempt + 1, attempts, delay, exc,
            )
            sleep(delay)
    raise last_error
