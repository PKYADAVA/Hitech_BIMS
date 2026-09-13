"""Feed detectors — stock left at the farm and intake against breed standard."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from alerthub.constants import compare
from alerthub.engine import raise_alert
from alerthub.measures import (batch_entry_url, birds_alive, breed_standard,
                              pct, safe_url)
from alerthub.scoping import rule_applies_to

from . import detector

LOOKBACK_DAYS = 3


def _latest_entries(limit_days=LOOKBACK_DAYS):
    """The most recent daily entry per batch inside the window.

    Feed stock is a running balance, so only the newest reading means anything;
    an older row would raise an alert about a shortage that has since been
    refilled.
    """
    from broiler.models import DailyEntry

    today = timezone.localdate()
    rows = (
        DailyEntry.objects.filter(date__gte=today - timedelta(days=limit_days))
        .exclude(batch__isnull=True)
        .select_related("batch", "batch__breed", "batch__broiler_farm",
                        "batch__broiler_farm__branch", "feed_1", "feed_2")
        .order_by("batch_id", "-date", "-id")
    )
    seen, latest = set(), []
    for row in rows:
        if row.batch_id in seen:
            continue
        seen.add(row.batch_id)
        latest.append(row)
    return latest


@detector("feed.low_feed_stock")
def low_feed_stock(rule):
    """Closing feed stock at a farm, from the daily entry's running balance.

    Both feed slots are checked independently — a farm with plenty of starter
    and no finisher is out of feed for the birds that need finisher, and summing
    the two would hide exactly that.
    """
    for entry in _latest_entries():
        batch = entry.batch
        farm = batch.broiler_farm
        scope = {"farm": farm, "branch": getattr(farm, "branch", None)}
        if not rule_applies_to(rule, **scope):
            continue

        slots = (
            (entry.feed_1, entry.feed_1_stock, "1"),
            (entry.feed_2, entry.feed_2_stock, "2"),
        )
        for item, stock, slot in slots:
            # A slot with no item is unused, not empty. Only a slot that is
            # actually in use can be low.
            if item is None:
                continue
            if not compare(stock, rule.operator, rule.threshold):
                continue

            raise_alert(
                rule,
                title="Low Feed Stock",
                message=(
                    f"{farm.farm_name} has {stock} kg of {item.description} left "
                    f"as of {entry.date:%d %b %Y} (limit {rule.threshold} kg), "
                    f"batch {batch.batch_name}."
                ),
                dedupe_key=f"{rule.pk}:low_feed:{batch.pk}:{item.pk}",
                measured_value=stock,
                threshold_value=rule.threshold,
                object_label="broiler.BroilerBatch",
                object_id=batch.pk,
                object_display=batch.batch_name,
                voucher_no=entry.entry_no,
                action_url=safe_url("daily_entry_list"),
                metadata={"item": item.description, "slot": slot,
                          "as_of": str(entry.date)},
                **scope,
            )


@detector("feed.consumption_above_standard")
def consumption_above_standard(rule):
    """Feed per bird per day against the breed's standard intake for that age.

    Overshooting the standard is usually spillage, theft or a miscounted flock
    rather than hungry birds, which is why it is worth a look even though it
    reads like good news for the birds.
    """
    entries = _latest_entries(limit_days=2)
    if not entries:
        return

    alive = birds_alive([e.batch_id for e in entries])

    for entry in entries:
        batch = entry.batch
        flock = alive.get(entry.batch_id)
        if not flock or flock <= 0:
            continue

        standard = breed_standard(batch.breed_id, entry.age_days)
        if not standard or not standard.feed_intake:
            continue

        total_kg = (entry.feed_1_qty or 0) + (entry.feed_2_qty or 0)
        if total_kg <= 0:
            continue

        # Standard intake is grams per bird per day; the entry is kilograms
        # for the whole flock.
        per_bird_g = (Decimal(str(total_kg)) * 1000) / flock
        excess = pct(per_bird_g - standard.feed_intake, standard.feed_intake)
        if excess is None or excess <= 0:
            continue
        if not compare(excess, rule.operator, rule.threshold):
            continue

        farm = batch.broiler_farm
        scope = {"farm": farm, "branch": getattr(farm, "branch", None)}
        if not rule_applies_to(rule, **scope):
            continue

        raise_alert(
            rule,
            title="Feed Consumption exceeds Standard",
            message=(
                f"{farm.farm_name} fed {per_bird_g:.0f}g per bird on "
                f"{entry.date:%d %b %Y} against a standard of "
                f"{standard.feed_intake}g at day {entry.age_days} — "
                f"{excess:.1f}% over (limit {rule.threshold}%)."
            ),
            dedupe_key=f"{rule.pk}:feed_std:{batch.pk}:{entry.date}",
            measured_value=round(excess, 3),
            threshold_value=rule.threshold,
            object_label="broiler.BroilerBatch",
            object_id=batch.pk,
            object_display=batch.batch_name,
            voucher_no=entry.entry_no,
            action_url=safe_url("daily_entry_list"),
            metadata={"per_bird_g": f"{per_bird_g:.1f}",
                      "standard_g": str(standard.feed_intake),
                      "birds": int(flock)},
            **scope,
        )


#: How many days of entries the consumption average is taken over. Long enough
#: that one heavy or skipped day does not swing it, short enough to follow a
#: flock whose intake climbs every week.
CONSUMPTION_WINDOW_DAYS = 7


def _daily_consumption(batch_ids, window=CONSUMPTION_WINDOW_DAYS):
    """(batch, slot) -> average kilograms a day, over the recent window.

    Averaged across the days that actually recorded a feeding rather than
    across the window: a farm that feeds every other day is not consuming half
    as much, it is recording half as often, and dividing by the calendar would
    say its stock lasts twice as long as it does.
    """
    from django.db.models import Avg, Q

    from broiler.models import DailyEntry

    since = timezone.localdate() - timedelta(days=window)
    rows = (DailyEntry.objects
            .filter(batch_id__in=batch_ids, date__gte=since)
            .values("batch_id")
            .annotate(one=Avg("feed_1_qty", filter=Q(feed_1_qty__gt=0)),
                      two=Avg("feed_2_qty", filter=Q(feed_2_qty__gt=0))))
    out = {}
    for row in rows:
        out[(row["batch_id"], "1")] = row["one"]
        out[(row["batch_id"], "2")] = row["two"]
    return out


@detector("feed.stock_coverage_days")
def stock_coverage_days(rule):
    """How many days the feed on the farm will last at the current rate.

    Kilograms alone cannot answer the question anybody is actually asking.
    Eight hundred kilos is a fortnight for a young flock and half a day for a
    full shed a week from harvest, so a single kilogram threshold either
    shouts at every small flock or says nothing about the large one that is
    about to run out. Coverage is the same number expressed the way the
    decision is made: stock divided by what is going out per day.

    A slot with no recorded consumption is skipped rather than treated as
    lasting for ever — there is no rate to divide by, and inventing one would
    put a number on the screen that nothing measured.
    """
    entries = list(_latest_entries())
    if not entries:
        return

    consumption = _daily_consumption([e.batch_id for e in entries])

    for entry in entries:
        batch = entry.batch
        farm = batch.broiler_farm
        scope = {"farm": farm, "branch": getattr(farm, "branch", None)}
        if not rule_applies_to(rule, **scope):
            continue

        slots = (
            (entry.feed_1, entry.feed_1_stock, "1"),
            (entry.feed_2, entry.feed_2_stock, "2"),
        )
        for item, stock, slot in slots:
            if item is None:
                continue
            rate = consumption.get((entry.batch_id, slot))
            if not rate or Decimal(str(rate)) <= 0:
                continue

            stock = Decimal(str(stock or 0))
            days = (stock / Decimal(str(rate))).quantize(Decimal("0.1"))
            if not compare(days, rule.operator, rule.threshold):
                continue

            raise_alert(
                rule,
                title="Feed Stock Coverage Low",
                message=(
                    f"{farm.farm_name} has {stock:,.0f} kg of "
                    f"{item.description} against {Decimal(str(rate)):,.0f} kg a "
                    f"day — {days} days of cover (limit {rule.threshold} days), "
                    f"batch {batch.batch_name}."
                ),
                dedupe_key=f"{rule.pk}:feed_cover:{batch.pk}:{item.pk}",
                measured_value=days,
                threshold_value=rule.threshold,
                object_label="broiler.BroilerBatch",
                object_id=batch.pk,
                object_display=batch.batch_name,
                voucher_no=entry.entry_no,
                action_url=batch_entry_url(batch.pk, entry.date),
                metadata={"item": item.description, "slot": slot,
                          "stock_kg": str(stock),
                          "daily_kg": str(Decimal(str(rate)).quantize(Decimal("0.01"))),
                          "days_cover": str(days), "as_of": str(entry.date)},
                **scope,
            )
