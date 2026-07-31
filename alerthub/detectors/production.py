"""Production detectors — mortality, weight, flock age and settled KPIs."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from alerthub.constants import compare
from alerthub.engine import raise_alert
from alerthub.measures import (
    birds_alive,
    breed_standard,
    live_batches,
    pct,
    safe_url,
)
from alerthub.scoping import rule_applies_to

from . import detector

#: How far back a scan looks for daily entries. Entries are often keyed in a day
#: late, and a scanner that only ever read "today" would miss every one of them.
LOOKBACK_DAYS = 2


def _farm_scope(batch):
    """The scope columns for an alert about a flock."""
    farm = batch.broiler_farm
    return {"farm": farm, "branch": getattr(farm, "branch", None)}


def _batch_url(batch):
    return safe_url("broiler_batch_list") or safe_url("daily_entry_list")


@detector("production.high_mortality")
def high_mortality(rule):
    """One day's mortality as a share of the flock that was alive that morning.

    The denominator is the previous day's closing count, not birds placed —
    losing 50 birds from a flock of 500 is a crisis and from 20,000 is a normal
    Tuesday, and measuring both against the original placement would rank them
    the same for most of the cycle.
    """
    from broiler.models import DailyEntry

    today = timezone.localdate()
    window_start = today - timedelta(days=LOOKBACK_DAYS)

    entries = list(
        DailyEntry.objects.filter(date__gte=window_start, date__lte=today)
        .exclude(batch__isnull=True)
        .filter(mortality__gt=0)
        .select_related("batch", "batch__broiler_farm",
                        "batch__broiler_farm__branch", "farm")
    )
    if not entries:
        return

    # One alive-map per distinct date, rather than per entry: the map is a
    # handful of aggregate queries and the window is small.
    by_date: dict = {}
    for entry in entries:
        by_date.setdefault(entry.date, []).append(entry)

    for day, day_entries in by_date.items():
        batch_ids = [e.batch_id for e in day_entries]
        alive_before = birds_alive(batch_ids, upto=day - timedelta(days=1))

        for entry in day_entries:
            flock = alive_before.get(entry.batch_id)
            if not flock or flock <= 0:
                continue                  # placement unknown — see birds_alive
            share = pct(entry.mortality, flock)
            if not compare(share, rule.operator, rule.threshold):
                continue

            batch = entry.batch
            scope = _farm_scope(batch)
            if not rule_applies_to(rule, **scope):
                continue

            raise_alert(
                rule,
                title="High Mortality",
                message=(
                    f"{entry.mortality} bird(s) died on {day:%d %b %Y} — "
                    f"{share:.2f}% of the {int(flock):,} alive that morning "
                    f"(limit {rule.threshold}%). Batch {batch.batch_name}, "
                    f"day {entry.age_days}."
                ),
                dedupe_key=f"{rule.pk}:high_mortality:{entry.batch_id}:{day}",
                measured_value=round(share, 3),
                threshold_value=rule.threshold,
                object_label="broiler.BroilerBatch",
                object_id=batch.pk,
                object_display=batch.batch_name,
                voucher_no=entry.entry_no,
                action_url=_batch_url(batch),
                metadata={"age_days": entry.age_days, "deaths": entry.mortality},
                **scope,
            )


@detector("production.cumulative_mortality")
def cumulative_mortality(rule):
    """Total mortality and culls since placement, against birds placed."""
    from alerthub.measures import birds_placed, flock_losses

    batches = list(live_batches())
    if not batches:
        return
    batch_ids = [b.pk for b in batches]
    placed = birds_placed(batch_ids)
    losses = flock_losses(list(placed))

    for batch in batches:
        total = placed.get(batch.pk)
        if not total:
            continue
        mortality, culls, _sold = losses.get(batch.pk, (0, 0, 0))
        share = pct(mortality + culls, total)
        if not compare(share, rule.operator, rule.threshold):
            continue

        scope = _farm_scope(batch)
        if not rule_applies_to(rule, **scope):
            continue

        raise_alert(
            rule,
            title="Cumulative Mortality Exceeds Limit",
            message=(
                f"Batch {batch.batch_name} has lost {int(mortality + culls):,} of "
                f"{int(total):,} birds placed — {share:.2f}% "
                f"(limit {rule.threshold}%)."
            ),
            dedupe_key=f"{rule.pk}:cum_mortality:{batch.pk}",
            measured_value=round(share, 3),
            threshold_value=rule.threshold,
            object_label="broiler.BroilerBatch",
            object_id=batch.pk,
            object_display=batch.batch_name,
            action_url=_batch_url(batch),
            **scope,
        )


@detector("production.low_body_weight")
def low_body_weight(rule):
    """Average weight against the breed's standard curve for that age.

    Silently skips flocks with no breed or no standard row — an unconfigured
    breed standard is a setup gap, and guessing a target weight would raise
    alerts about a number nobody chose.
    """
    from broiler.models import DailyEntry

    today = timezone.localdate()
    entries = (
        DailyEntry.objects.filter(
            date__gte=today - timedelta(days=LOOKBACK_DAYS),
            avg_weight_gms__gt=0,
        )
        .exclude(batch__isnull=True)
        .select_related("batch", "batch__breed", "batch__broiler_farm",
                        "batch__broiler_farm__branch")
        .order_by("batch_id", "-date")
    )

    seen = set()
    for entry in entries:
        if entry.batch_id in seen:
            continue                       # most recent reading per batch only
        seen.add(entry.batch_id)

        batch = entry.batch
        standard = breed_standard(batch.breed_id, entry.age_days)
        if not standard or not standard.body_weight:
            continue

        shortfall = pct(standard.body_weight - entry.avg_weight_gms,
                        standard.body_weight)
        if shortfall is None or shortfall <= 0:
            continue
        if not compare(shortfall, rule.operator, rule.threshold):
            continue

        scope = _farm_scope(batch)
        if not rule_applies_to(rule, **scope):
            continue

        raise_alert(
            rule,
            title="Low Body Weight",
            message=(
                f"Batch {batch.batch_name} averages {entry.avg_weight_gms}g at day "
                f"{entry.age_days} against a standard of {standard.body_weight}g — "
                f"{shortfall:.1f}% under (limit {rule.threshold}%)."
            ),
            dedupe_key=f"{rule.pk}:low_weight:{batch.pk}:{entry.date}",
            measured_value=round(shortfall, 3),
            threshold_value=rule.threshold,
            object_label="broiler.BroilerBatch",
            object_id=batch.pk,
            object_display=batch.batch_name,
            voucher_no=entry.entry_no,
            action_url=_batch_url(batch),
            metadata={"avg_weight_gms": str(entry.avg_weight_gms),
                      "standard_gms": str(standard.body_weight),
                      "age_days": entry.age_days},
            **scope,
        )


def _settlement_kpi(rule, field, title, unit=""):
    """Shared body for the three settled performance rules.

    They differ only in which column they read and how it reads out loud, so
    the query, the scoping and the dedupe live here once.
    """
    from broiler.models import GrowingChargeSettlement

    recent = timezone.localdate() - timedelta(days=90)
    rows = GrowingChargeSettlement.objects.filter(gc_date__gte=recent).select_related(
        "batch", "farm", "farm__branch"
    )
    for settlement in rows:
        value = getattr(settlement, field, None)
        if value in (None, Decimal("0")):
            continue
        if not compare(value, rule.operator, rule.threshold):
            continue

        scope = {"farm": settlement.farm,
                 "branch": getattr(settlement.farm, "branch", None)}
        if not rule_applies_to(rule, **scope):
            continue

        batch = settlement.batch
        raise_alert(
            rule,
            title=title,
            message=(
                f"Batch {batch.batch_name} settled with {field.upper()} "
                f"{value}{unit} (limit {rule.threshold}{unit}), "
                f"closed {settlement.gc_date:%d %b %Y}."
            ),
            dedupe_key=f"{rule.pk}:{field}:{settlement.pk}",
            measured_value=value,
            threshold_value=rule.threshold,
            object_label="broiler.GrowingChargeSettlement",
            object_id=settlement.pk,
            object_display=settlement.settlement_code,
            voucher_no=settlement.settlement_code,
            action_url=safe_url("gc_settlement_list"),
            **scope,
        )


@detector("production.poor_fcr")
def poor_fcr(rule):
    _settlement_kpi(rule, "fcr", "Poor FCR")


@detector("production.poor_cfcr")
def poor_cfcr(rule):
    _settlement_kpi(rule, "cfcr", "Poor CFCR")


@detector("production.low_eef")
def low_eef(rule):
    _settlement_kpi(rule, "eef", "Low EEF")


def _age_rule(rule, title, describe):
    """Shared body for Bird Age and Harvest Due — same query, different words."""
    today = timezone.localdate()
    for batch in live_batches():
        if not batch.start_date:
            continue
        age = (today - batch.start_date).days
        if not compare(Decimal(age), rule.operator, rule.threshold):
            continue

        scope = _farm_scope(batch)
        if not rule_applies_to(rule, **scope):
            continue

        raise_alert(
            rule,
            title=title,
            message=describe(batch, age),
            dedupe_key=f"{rule.pk}:{title}:{batch.pk}",
            measured_value=Decimal(age),
            threshold_value=rule.threshold,
            object_label="broiler.BroilerBatch",
            object_id=batch.pk,
            object_display=batch.batch_name,
            action_url=_batch_url(batch),
            metadata={"age_days": age},
            **scope,
        )


@detector("production.bird_age")
def bird_age(rule):
    _age_rule(
        rule, "Bird Age Alert",
        lambda batch, age: (
            f"Batch {batch.batch_name} at {batch.broiler_farm.farm_name} is "
            f"{age} days old (alert at {rule.threshold} days)."
        ),
    )


@detector("production.harvest_due")
def harvest_due(rule):
    _age_rule(
        rule, "Harvest Due",
        lambda batch, age: (
            f"Batch {batch.batch_name} is {age} days old and still open — "
            f"harvest age is {rule.threshold} days."
        ),
    )


@detector("production.placement_pending")
def placement_pending(rule):
    """Batches created a while ago with no chicks booked into them.

    An empty chick-item list means placements cannot be identified at all, so
    every batch would look unplaced. The detector stands down rather than
    raising an alert per open batch.
    """
    from alerthub.measures import birds_placed, chick_item_ids

    chick_ids = chick_item_ids()
    if not chick_ids:
        return

    today = timezone.localdate()
    batches = list(live_batches())
    placed = birds_placed([b.pk for b in batches], chick_ids=chick_ids)

    for batch in batches:
        if placed.get(batch.pk):
            continue
        reference = batch.start_date or batch.created_at.date()
        waiting = (today - reference).days
        if not compare(Decimal(waiting), rule.operator, rule.threshold):
            continue

        scope = _farm_scope(batch)
        if not rule_applies_to(rule, **scope):
            continue

        raise_alert(
            rule,
            title="Placement Pending",
            message=(
                f"Batch {batch.batch_name} at {batch.broiler_farm.farm_name} has "
                f"had no chicks placed for {waiting} day(s)."
            ),
            dedupe_key=f"{rule.pk}:placement_pending:{batch.pk}",
            measured_value=Decimal(waiting),
            threshold_value=rule.threshold,
            object_label="broiler.BroilerBatch",
            object_id=batch.pk,
            object_display=batch.batch_name,
            action_url=safe_url("chicks_placement_list"),
            **scope,
        )


@detector("production.dispatch_pending")
def dispatch_pending(rule):
    """Flocks past harvest age with nothing sold off them yet."""
    from broiler.models import BirdSale

    today = timezone.localdate()
    batches = [b for b in live_batches() if b.start_date]
    if not batches:
        return

    sold_batches = set(
        BirdSale.objects.filter(batch_id__in=[b.pk for b in batches])
        .values_list("batch_id", flat=True)
    )

    for batch in batches:
        if batch.pk in sold_batches:
            continue
        overdue = (today - batch.start_date).days - int(rule.threshold or 0)
        if overdue < 0:
            continue

        scope = _farm_scope(batch)
        if not rule_applies_to(rule, **scope):
            continue

        raise_alert(
            rule,
            title="Dispatch Pending",
            message=(
                f"Batch {batch.batch_name} is {(today - batch.start_date).days} days "
                f"old with no bird sale recorded — {overdue} day(s) past dispatch."
            ),
            dedupe_key=f"{rule.pk}:dispatch_pending:{batch.pk}",
            measured_value=Decimal(overdue),
            threshold_value=rule.threshold,
            object_label="broiler.BroilerBatch",
            object_id=batch.pk,
            object_display=batch.batch_name,
            action_url=safe_url("bird_sale_list"),
            **scope,
        )
