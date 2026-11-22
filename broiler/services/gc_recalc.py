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
    """Every stored figure a re-run may replace outright.

    Everything on the model except the fields a person can actually type
    into (which belong to the edit path), the scheme-suggested fields a
    person *can* override (see ``_scheme_default_fields_to_review`` --
    those are reported separately, never silently replaced), the identity
    columns, and ``gc_date``. Derived by subtraction rather than listed, so
    a figure added to the settlement in future is refreshed without anyone
    remembering to add it here — the failure this exists to fix was a
    figure nobody could refresh at all.
    """
    from broiler.models import GrowingChargeSettlement
    from broiler.views import GC_SETTLEMENT_INPUT_FIELDS, GC_SETTLEMENT_SCHEME_DEFAULT_FIELDS

    skip = set(GC_SETTLEMENT_INPUT_FIELDS) - set(GC_SETTLEMENT_SCHEME_DEFAULT_FIELDS)
    return [f.name for f in GrowingChargeSettlement._meta.fields
            if f.name not in _NEVER and f.name not in skip]


def _scheme_default_fields_to_review(settlement, fresh):
    """Scheme-suggested figures the stored value may no longer match.

    These fields are overridable on the form, so what is stored may be a
    deliberate override rather than an unrefreshed default -- a re-run
    cannot tell those apart, and silently overwriting an override some
    farmer was paid against is worse than leaving a stale default alone.
    So they are never corrected automatically. What they are is reported:
    what the scheme would suggest now, next to what is stored, so whoever
    is rechecking the settlement can see whether the two still agree and
    decide for themselves whether anything here needs to change.
    """
    from broiler.models import GrowingChargeSettlement
    from broiler.views import GC_SETTLEMENT_SCHEME_DEFAULT_FIELDS

    columns = {f.name: f for f in GrowingChargeSettlement._meta.fields}
    review = {}
    for name in GC_SETTLEMENT_SCHEME_DEFAULT_FIELDS:
        if name not in fresh or name not in columns:
            continue
        old = getattr(settlement, name)
        new = _as_stored(columns[name], fresh[name])
        if _differs(old, new):
            review[name] = {"from": _as_text(old), "to": _as_text(new)}
    return review


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

    Returns ``(changes, review, merged)``. ``changes`` is
    ``{field: {"from": str, "to": str}}`` for the figures a re-run would
    simply correct — empty when the stored ones already match what the
    batch's records say. ``review`` is the same shape for the scheme-default
    fields a person can override: never applied automatically, since the
    stored value may be a deliberate override rather than a stale default,
    and a re-run has no way to tell those apart (see
    ``_scheme_default_fields_to_review``).
    """
    from broiler.views import (GC_SETTLEMENT_INPUT_FIELDS,
                               _gc_settlement_autofill, _gc_settlement_totals)

    fresh = _gc_settlement_autofill(settlement.batch, settlement.scheme)
    review = _scheme_default_fields_to_review(settlement, fresh)

    # Which scheme applies can itself have moved on -- a new scheme covering
    # these placement dates, an existing one's date range edited, a branch or
    # region reassigned. The settlement stays bound to the scheme it was made
    # under (scheme_id is in _NEVER, deliberately: a settled document does not
    # change its own basis unasked), so every figure above is worked out from
    # that one. If the master would now pick a different scheme, the whole
    # comparison is against the wrong rates and saying nothing about it is the
    # worst of the options -- so it is reported, for a person to act on.
    try:
        from broiler.views import _match_growing_charge_scheme, _placement_date

        matched = _match_growing_charge_scheme(settlement.batch,
                                               _placement_date(settlement.batch))
    except Exception:  # a picker failure must not take the whole preview down
        matched = None
    if matched and matched.id != settlement.scheme_id:
        stored_name = (f"{settlement.scheme.scheme_code} - {settlement.scheme.schema_name}"
                       if settlement.scheme_id else "(none)")
        review["scheme"] = {
            "from": stored_name,
            "to": f"{matched.scheme_code} - {matched.schema_name}",
        }

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

    return changes, review, merged


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

    changes, _review, merged = plan(settlement, include_date=include_date)
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
