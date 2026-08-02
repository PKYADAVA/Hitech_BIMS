"""One rule about transaction dates, shared by every module.

A transaction dated ahead of today corrupts everything that is read as-of a
date: age, opening stock, the live-bird count, every ledger balance. There is
no legitimate reason to file one, so it is refused rather than clamped —
clamping would save a row nobody asked for and hide the mistake.

The browser stops it too (``static/js/main.js``), but that guard is a
courtesy: the mobile client, an old tab and a hand-made request all arrive
here instead.

Scheduling dates are a different thing and must not be passed through this.
A hatch date, a tray transfer date, a phase's effective_from, a financial
year's bounds and an agreement's start are all legitimately in the future.
Only the date a transaction *happened* on belongs here.
"""
from django.core.exceptions import ValidationError
from django.utils import timezone


def reject_future_date(value, label="Entry date"):
    """Return ``value`` unchanged, or raise ``ValidationError`` if it is after
    today. ``None`` passes, so callers can hand over an optional field."""
    if value and value > timezone.localdate():
        raise ValidationError(
            "%s cannot be later than today (%s)."
            % (label, timezone.localdate().strftime("%d.%m.%Y")))
    return value
