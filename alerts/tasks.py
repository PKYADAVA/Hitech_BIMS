"""Async dispatch abstraction.

The design contract from the spec: heavy work (email, webhooks, websocket
fan-out) must never block the HTTP request, yet the project currently ships no
Celery/Django-Q worker. This module hides that behind one function,
:func:`enqueue`, so call sites are identical whether or not a broker exists:

* ``ASYNC_BACKEND="celery"`` (or ``"auto"`` with Celery importable) → the work
  is handed to a Celery task.
* otherwise → it runs inline.

When a worker is added later, only ``ASYNC_BACKEND`` changes; no call site does.
The channel *fan-out* is what gets enqueued — the Alert/Audit rows are always
written synchronously inside the request so the feed is immediately correct.
"""
from __future__ import annotations

import logging
from typing import Any

from .conf import config

logger = logging.getLogger(__name__)


def _run_inline(payload: dict[str, Any]) -> None:
    from .services import deliver_to_channels

    deliver_to_channels(payload)


# --- optional Celery task -------------------------------------------------- #
# Defined only if Celery is importable so the module never hard-depends on it.
try:  # pragma: no cover - exercised only when Celery is installed
    from celery import shared_task

    @shared_task(name="alerts.dispatch_notifications", ignore_result=True)
    def _celery_dispatch(payload: dict[str, Any]) -> None:
        _run_inline(payload)

    _HAS_CELERY = True
except Exception:
    _celery_dispatch = None
    _HAS_CELERY = False


def _use_celery() -> bool:
    backend = (config.ASYNC_BACKEND or "auto").lower()
    if backend == "inline":
        return False
    if backend == "celery":
        return _HAS_CELERY
    return _HAS_CELERY  # "auto"


def enqueue(payload: dict[str, Any]) -> None:
    """Schedule channel delivery for a built alert payload.

    Never raises: notification delivery is best-effort and must not surface
    into the caller's transaction.
    """
    try:
        if _use_celery() and _celery_dispatch is not None:
            _celery_dispatch.delay(payload)
        else:
            _run_inline(payload)
    except Exception:
        logger.exception("alerts: notification dispatch failed")
