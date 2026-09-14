"""Re-derive a settled batch's figures, and say what moved.

A Growing Charge settlement is a snapshot. Every figure the form showed is
frozen on the row, deliberately: a farmer is paid against it, and a rate
changed next season must not restate what was settled last season. Editing one
is built the same way — it touches the numbers a person typed and leaves the
computed ones exactly as they were stored.

That is right until the computation itself turns out to have been wrong. Then
the fix reaches every batch settled after it and none settled before, and the
old ones cannot be corrected by editing them, because editing is the one path
that will not touch a computed figure.

This is the other half. It rebuilds the computed figures from the batch's
records as they stand now, keeps everything a person entered, and reports the
difference. Two things make that safe enough to do to a signed document:

**It is a preview first.** Nothing is written unless the caller asks, so the
difference can be read before it is accepted.

**It leaves a trail.** Applying writes a
:class:`~broiler.models.GCSettlementRecalculation` naming who did it and every
field that moved. A correction nobody can see afterwards is indistinguishable
from an error.

The division of labour with the edit path is exact, and worth keeping:

    PUT /gc-settlement/<id>   the fields a person fills in, and nothing else
    recalculate()             every other field, and nothing else

so no field has two owners, and the running totals are rebuilt from both.
"""
from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal

from django.db import models, transaction

logger = logging.getLogger(__name__)

#: Never touched by a re-run: identity, the audit columns, and the batch this
#: belongs to. ``gc_date`` is handled separately — see ``include_date``.
_NEVER = {
    "id", "settlement_code", "batch", "batch_id", "farm", "farm_id",
    "scheme", "scheme_id", "created_by", "created_by_id", "created_at",
    "updated_at", "remarks", "gc_date", "tds_percent",
}


def _fields_to_refresh():
    """Every stored figure a re-run may replace.

    Everything on the model except the fields a person fills in (which belong
    to the edit path), the identity columns, and ``gc_date``. Derived by
    subtraction rather than listed, so a figure added to the settlement in
    future is refreshed without anyone remembering to add it here — the
    failure this exists to fix was a figure nobody could refresh at all.
    """
    from broiler.models import GrowingChargeSettlement
    from broiler.views import GC_SETTLEMENT_INPUT_FIELDS

    return [f.name for f in GrowingChargeSettlement._meta.fields
            if f.name not in _NEVER and f.name not in GC_SETTLEMENT_INPUT_FIELDS]


def _as_stored(field, value):
    """A freshly computed figure, as the column would hold it.

    The comparison is against what is in the database, and the database has
    already rounded: a settlement saved with an age of 40.123456 comes back as
    40.12. Comparing the stored 40.12 against a recomputed 40.123456 reports a
    change on every field with more precision than its column, so every
    settlement ever made looks like it needs correcting and the handful that
    genuinely do are lost among them.
    """
    if value is None:
        return None
    if isinstance(field, models.DecimalField):
        try:
            step = Decimal(1).scaleb(-field.decimal_places)
            return Decimal(str(value)).quantize(step, rounding=ROUND_HALF_UP)
        except (ArithmeticError, ValueError):
            return value
    if isinstance(field, models.IntegerField):
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    return value


def _as_text(value):
    """How a figure is written into the audit row.

    Strings, because this is read years later and has to survive the field
    changing type — or leaving the model altogether.
    """
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


_NUMERIC = (Decimal, int, float)


def _differs(old, new) -> bool:
    """Whether two stored figures are actually different.

    Numbers compare by value, across types. 500 and 500.00 are the same figure
    written two ways, and so are the integer 0 a bird count column holds and
    the Decimal("0.00") the calculation hands back. Reporting either as a
    change fills the difference with rows where nothing moved, and the one
    figure that did move is lost among them.
    """
    if isinstance(old, bool) or isinstance(new, bool):
        return old is not new
    if isinstance(old, _NUMERIC) and isinstance(new, _NUMERIC):
        return Decimal(str(old)) != Decimal(str(new))
    if old is None or new is None:
        return old is not new
    return _as_text(old) != _as_text(new)


def plan(settlement, *, include_date=True):
    """What a re-run would change, without changing anything.

    Returns ``{field: {"from": str, "to": str}}`` — empty when the stored
    figures already match what the batch's records say, which is the answer for
    a settlement made after the fault was fixed.
    """
    from broiler.views import (GC_SETTLEMENT_INPUT_FIELDS,
                               _gc_settlement_autofill, _gc_settlement_totals)

    fresh = _gc_settlement_autofill(settlement.batch, settlement.scheme)

    # The person's own entries survive: they are the edit path's to change, and
    # a re-run that overwrote a typed deduction would be destroying the work it
    # claims to be protecting.
    merged = dict(fresh)
    for name in GC_SETTLEMENT_INPUT_FIELDS:
        merged[name] = getattr(settlement, name)

    # Totals are dependent on both halves, so they are rebuilt from the merge
    # rather than taken from either side.
    merged.update(_gc_settlement_totals(
        merged, merged.get("sold_birds") or 0, merged.get("sold_weight") or 0))

    from broiler.models import GrowingChargeSettlement

    columns = {f.name: f for f in GrowingChargeSettlement._meta.fields}
    changes = {}
    for name in _fields_to_refresh():
        if name not in merged:
            continue
        old = getattr(settlement, name)
        new = _as_stored(columns[name], merged[name])
        if _differs(old, new):
            changes[name] = {"from": _as_text(old), "to": _as_text(new)}
            merged[name] = new

    if include_date:
        suggested = fresh.get("gc_date_default")
        if suggested and suggested != settlement.gc_date:
            changes["gc_date"] = {"from": _as_text(settlement.gc_date),
                                  "to": _as_text(suggested)}

    return changes, merged


@transaction.atomic
def recalculate(settlement, *, user=None, include_date=True, note=""):
    """Write the re-derived figures back, and record that it happened.

    Returns the changes applied — empty when there was nothing to correct, in
    which case nothing is written at all, not even an audit row: a re-run that
    found the settlement already right is not an event.

    The voucher follows. ``post_settlement_if_enabled`` cancels what was posted
    and writes a fresh one rather than amending a posted figure in place, which
    is what the edit path does for the same reason — and why this must never be
    the step that fails quietly. It is inside the transaction, so a posting
    failure takes the correction back out with it.
    """
    from broiler.models import GCSettlementRecalculation
    from broiler.services import gc_posting

    changes, merged = plan(settlement, include_date=include_date)
    if not changes:
        return {}

    for name in changes:
        if name == "gc_date":
            settlement.gc_date = merged["gc_date_default"]
        else:
            setattr(settlement, name, merged[name])
    settlement.save()

    # The batch's own closing dates were taken from gc_date when it was
    # settled, so they move with it. Leaving them behind would have the batch
    # and its settlement disagree about the day it finished.
    if "gc_date" in changes:
        batch = settlement.batch
        batch.closed_on = settlement.gc_date
        batch.end_date = settlement.gc_date
        batch.save(update_fields=["closed_on", "end_date"])

    entry = GCSettlementRecalculation.objects.create(
        settlement=settlement, actor=user, changes=changes, note=note or "")

    gc_posting.post_settlement_if_enabled(settlement, user=user)

    logger.info("gc: settlement %s recalculated by %s, %d field(s) changed",
                settlement.settlement_code, user, len(changes))
    return {"changes": changes, "entry_id": entry.id}
