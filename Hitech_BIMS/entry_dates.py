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
import datetime

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.dateparse import parse_date


def reject_future_date(value, label="Entry date"):
    """Return ``value`` unchanged, or raise ``ValidationError`` if it is after
    today. ``None`` passes, so callers can hand over an optional field."""
    if value and value > timezone.localdate():
        raise ValidationError(
            "%s cannot be later than today (%s)."
            % (label, timezone.localdate().strftime("%d.%m.%Y")))
    return value


def date_from_query(value):
    """A date out of a query string, or None when there is not one.

    Django's ``parse_date`` returns None for something that is not a date at
    all, but *raises* for a string shaped like one that cannot exist —
    "2026-13-45", "2026-02-30". A report filtered by hand-typed dates, or
    reached by a link somebody edited, then answers with a 500 rather than
    with the report.

    None means "no filter", which is what every report already does with a
    blank box, so an unreadable date is treated as one nobody typed.
    """
    if value is None or value == "":
        return None
    # Already a date — some callers default the range to real dates before
    # filtering, and a helper used in eighty places has to take what it is
    # given rather than assume every caller holds a string.
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    try:
        return parse_date(str(value).strip())
    except ValueError:
        return None
