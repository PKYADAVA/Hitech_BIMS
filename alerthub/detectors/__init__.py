"""Detector registry — the code behind each catalogued rule key.

A detector is a function that takes one configured
:class:`~alerthub.models.AlertRule` and raises whatever alerts it finds:

.. code-block:: python

    @detector("production.high_mortality")
    def high_mortality(rule):
        for entry in ...:
            raise_alert(rule, title=..., dedupe_key=...)

It returns nothing. Counting is the scanner's job (it diffs the notification
table), so a detector cannot mis-report what it did.

**Detectors query, they do not listen.** Everything here is evaluated on a
schedule rather than wired into ``post_save``. Two reasons: most of these
conditions are not events at all — "a flock reached harvest age" and "an invoice
went overdue" happen because a date passed, with no row being saved — and
signal-driven alerting is what produced the feedback loop the audit feed had to
be rescued from. A scan that reads is incapable of triggering itself.

Importing this package imports every module in it, which is what registers the
functions; :mod:`alerthub.apps` does that on startup.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil

logger = logging.getLogger(__name__)

#: rule_key -> detector function.
REGISTRY: dict[str, callable] = {}


def detector(rule_key):
    """Register a function as the detector for ``rule_key``."""

    def decorator(func):
        if rule_key in REGISTRY:
            raise RuntimeError(f"alerthub: duplicate detector for {rule_key!r}")
        REGISTRY[rule_key] = func
        return func

    return decorator


def autodiscover():
    """Import every detector module so the decorators run. Idempotent."""
    for info in pkgutil.iter_modules(__path__):
        importlib.import_module(f"{__name__}.{info.name}")


def get(rule_key):
    return REGISTRY.get(rule_key)


def missing_detectors():
    """Catalogue keys marked supported that have no registered detector.

    A wiring mistake, not a data gap — the catalogue promises these fire. The
    scanner reports them rather than failing silently, and a test asserts the
    list is empty.
    """
    from alerthub.catalog import supported_keys

    autodiscover()
    return sorted(supported_keys() - set(REGISTRY))
