"""Retry helper for transient SMS failures.

Only :class:`~notification.exceptions.SmsTransientError` is retried; permanent
errors (invalid number, bad credentials, malformed request) propagate on the
first attempt so bad input is never sent repeatedly.
"""

import logging
import time

from .exceptions import SmsTransientError

logger = logging.getLogger("notification.sms")


def call_with_retry(func, max_retries, backoff, sleep=time.sleep):
    """Invoke ``func`` retrying transient failures with exponential backoff.

    Args:
        func: Zero-argument callable performing one send attempt.
        max_retries: Number of *additional* attempts after the first.
        backoff: Base delay in seconds; attempt ``n`` waits ``backoff * 2**n``.
        sleep: Injectable sleep function (kept out of the way in tests).

    Returns:
        Whatever ``func`` returns on the first successful attempt.

    Raises:
        The last :class:`SmsTransientError` if every attempt fails, or any
        non-transient exception immediately.
    """

    attempts = max(max_retries, 0) + 1
    last_error = None
    for attempt in range(attempts):
        try:
            return func()
        except SmsTransientError as exc:
            last_error = exc
            if attempt + 1 >= attempts:
                break
            delay = backoff * (2 ** attempt)
            logger.warning(
                "Transient SMS failure (attempt %d/%d); retrying in %.2fs: %s",
                attempt + 1, attempts, delay, exc,
            )
            sleep(delay)
    raise last_error
