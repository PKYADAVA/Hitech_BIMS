"""Shared measurements the detectors need, and safe URL building.

The flock figures here use the **same definitions as the Live Flock report and
the dashboard widget** — birds placed are chick-category stock transfers into
the batch; alive is placed minus mortality, culls and birds sold. That
duplication is deliberate and narrow: the report's engine returns printable rows
per flock and the widget's returns display dicts, neither of which a detector can
use. What must not diverge is the *definition*, so it is stated once here and
cross-referenced. If the definition changes, these three change together.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from django.db.models import Sum
from django.urls import NoReverseMatch, reverse

logger = logging.getLogger(__name__)

Z = Decimal("0")


def safe_url(name, *args, **kwargs) -> str:
    """``reverse`` that returns "" instead of raising.

    An alert whose View button cannot be built is still worth raising — losing
    the link is a much smaller loss than losing the warning, and a renamed url
    should not take the alerting engine down with it.
    """
    try:
        return reverse(name, args=args, kwargs=kwargs)
    except NoReverseMatch:
        logger.debug("alerthub: no reverse for %s", name)
        return ""


def chick_item_ids() -> list[int]:
    """Item ids in a chick category — how placements are identified.

    Same lookup the Live Flock widget uses. An empty result means the item
    categories are not set up, in which case bird counts are unknowable and the
    detectors that need them stand down rather than reporting zero.
    """
    from inventory.models import Item

    return list(
        Item.objects.filter(category__name__icontains="chick")
        .values_list("id", flat=True)
    )


def birds_placed(batch_ids, upto=None, chick_ids=None) -> dict[int, Decimal]:
    """Birds placed per batch, as chick-category transfers into it."""
    from inventory.models import StockTransfer

    chick_ids = chick_item_ids() if chick_ids is None else chick_ids
    if not chick_ids or not batch_ids:
        return {}

    rows = StockTransfer.objects.filter(
        to_batch_id__in=batch_ids, item_id__in=chick_ids
    )
    if upto is not None:
        rows = rows.filter(date__lte=upto)
    return {
        row["to_batch"]: Decimal(str(row["total"] or 0))
        for row in rows.values("to_batch").annotate(total=Sum("quantity"))
    }


def flock_losses(batch_ids, upto=None) -> dict[int, tuple[Decimal, Decimal, Decimal]]:
    """``{batch_id: (mortality, culls, sold)}`` to date."""
    from broiler.models import BirdSale, DailyEntry

    if not batch_ids:
        return {}

    entries = DailyEntry.objects.filter(batch_id__in=batch_ids)
    sales = BirdSale.objects.filter(batch_id__in=batch_ids)
    if upto is not None:
        entries = entries.filter(date__lte=upto)
        sales = sales.filter(date__lte=upto)

    losses = {b: [Z, Z, Z] for b in batch_ids}
    for row in entries.values("batch").annotate(m=Sum("mortality"), c=Sum("culls")):
        losses[row["batch"]][0] = Decimal(str(row["m"] or 0))
        losses[row["batch"]][1] = Decimal(str(row["c"] or 0))
    for row in sales.values("batch").annotate(b=Sum("birds")):
        if row["batch"] in losses:
            losses[row["batch"]][2] = Decimal(str(row["b"] or 0))
    return {k: tuple(v) for k, v in losses.items()}


def birds_alive(batch_ids, upto=None) -> dict[int, Decimal]:
    """Birds alive per batch = placed − mortality − culls − sold.

    Batches with no recorded placement are omitted rather than returned as
    zero: "we never booked the chicks in" and "they are all dead" are different
    facts, and a mortality percentage computed against a zero flock is a
    division by nothing, not a 100% loss.
    """
    placed = birds_placed(batch_ids, upto)
    losses = flock_losses(list(placed), upto)
    alive = {}
    for batch_id, count in placed.items():
        mortality, culls, sold = losses.get(batch_id, (Z, Z, Z))
        alive[batch_id] = count - mortality - culls - sold
    return alive


def pct(part, whole):
    """``part`` as a percentage of ``whole``, or None when it is meaningless."""
    if not whole:
        return None
    return (Decimal(str(part)) / Decimal(str(whole))) * 100


def live_batches(as_of=None):
    """Batches open on a date — started, not ended, not closed.

    Mirrors ``user.services.dashboard_widgets._batches_live_on``: a batch
    ending on the day itself has already finished.
    """
    from django.db.models import Q
    from django.utils import timezone

    from broiler.models import BroilerBatch

    day = as_of or timezone.localdate()
    return (
        BroilerBatch.objects.filter(
            Q(start_date__lte=day) | Q(start_date__isnull=True)
        )
        .filter(Q(end_date__isnull=True, is_closed=False) | Q(end_date__gt=day))
        .select_related("broiler_farm", "broiler_farm__branch", "breed")
    )


def breed_standard(breed_id, age):
    """The breed's standard row at an age, or None.

    Falls back to the nearest younger row, because standard curves are often
    entered at intervals (day 7, 14, 21) and an exact-age lookup would silently
    disable every standard comparison for the days in between.
    """
    from broiler.models import BreedStandard

    if not breed_id or age is None:
        return None
    return (
        BreedStandard.objects.filter(
            breed_id=breed_id, age__lte=age, is_active=True
        )
        .order_by("-age")
        .first()
    )
