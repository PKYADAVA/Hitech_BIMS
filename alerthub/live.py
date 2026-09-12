"""Raise the alerts that a saved row can decide, without waiting for the scan.

Most of what this module watches is not an event: "a flock reached harvest age"
and "an invoice went overdue" happen because a date passed, and only a sweep
can notice them. But some conditions are *created* by a row being saved — a
daily entry records the mortality that breaches a limit, a transfer takes a
store negative — and for those, waiting for the next sweep means the alert
arrives minutes or hours after the fact.

That was the whole latency. The scan runs on a clock (every two minutes
locally, and in production only as often as a scheduler gets round to it), so
"real time" was never limited by delivery — push and the bell are immediate —
but by when anyone looked.

Three things this is careful about, and they are the reasons it is written as
its own module rather than a few lines in a detector:

* **It runs after commit.** A rule reads the database, so it must not read a
  row that is about to roll back — and a push, once sent, cannot be recalled.
* **It never raises.** Alerting is a side effect of business work. The same
  rule ``push.py`` states: a dead network, a broken detector or a missing
  audience must not be the reason a daily entry fails to save.
* **It is throttled per rule.** A detector evaluates a rule across the whole
  business, not just the row that woke it. Importing a thousand daily entries
  would otherwise run the mortality rule a thousand times, and the cooldown
  would discard all but the first anyway — so the work is what needs stopping,
  not just the duplicate alert.

Nothing here changes what an alert *is*. It calls the same ``scan(rule_key=)``
the scheduled command calls, so a rule cannot behave one way on a save and
another on a sweep, and the cooldown in ``engine`` still decides whether the
alert is a repeat. This only changes *when* someone looks.
"""
from __future__ import annotations

import logging

from django.core.cache import cache
from django.db import transaction
from django.db.models.signals import post_save

logger = logging.getLogger(__name__)

#: ``"app_label.Model"`` -> the catalogue keys a save on it can decide.
#:
#: Deliberately short. A rule belongs here only when the saved row is what
#: creates the condition; a rule that turns on because a date passed gains
#: nothing but load, since no save marks the moment it becomes true.
LIVE_RULES: dict[str, tuple[str, ...]] = {
    # The entry that records a death is what makes the mortality a breach.
    "broiler.DailyEntry": (
        "production.high_mortality",
        "production.cumulative_mortality",
        "feed.consumption_above_standard",
    ),
    # Anything that moves stock can be what takes a store below zero.
    "inventory.StockTransfer": ("inventory.negative_stock",),
    "inventory.StockIssue": ("inventory.negative_stock",),
    "inventory.MedicineTransfer": ("inventory.negative_stock",),
    "inventory.InventoryAdjustment": ("inventory.negative_stock",),
    # A duplicate invoice only exists once the second one is entered.
    "purchase.GeneralPurchase": ("purchase.duplicate_invoice",),
}

#: Seconds a rule is left alone after being evaluated from a save.
#:
#: Long enough that a bulk import evaluates each rule once rather than once per
#: row, short enough that a person entering records one at a time still gets
#: the alert while they are looking at the screen. The scheduled scan is the
#: backstop for anything this window swallows.
THROTTLE_SECONDS = 30


def _run(rule_key: str) -> None:
    """Evaluate one rule, swallowing everything it can throw."""
    from .services import scan

    try:
        scan(rule_key=rule_key)
    except Exception:                       # noqa: BLE001 — see module docstring
        logger.exception("alerthub: live rule %s failed", rule_key)


def _on_save(sender, instance, created, **kwargs):
    """Queue the rules this model can decide, once the transaction commits."""
    label = f"{sender._meta.app_label}.{sender.__name__}"
    for rule_key in LIVE_RULES.get(label, ()):
        # Claim the window before commit, so a thousand rows in one import
        # queue one evaluation rather than a thousand. `add` is atomic on
        # every cache backend this runs on, and a False means someone else
        # has this rule in hand.
        if not cache.add(f"alerthub:live:{rule_key}", 1, THROTTLE_SECONDS):
            continue
        transaction.on_commit(lambda key=rule_key: _run(key))


def connect() -> None:
    """Bind the save hooks. Called from ``AlertHubConfig.ready``."""
    from django.apps import apps

    for label in LIVE_RULES:
        try:
            model = apps.get_model(label)
        except LookupError:
            # A model that has been renamed or removed must not stop the app
            # from starting; the scheduled scan still covers its rules.
            logger.warning("alerthub: live rules name an unknown model %s", label)
            continue
        post_save.connect(_on_save, sender=model, dispatch_uid=f"alerthub:live:{label}")
