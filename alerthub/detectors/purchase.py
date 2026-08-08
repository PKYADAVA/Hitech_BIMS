"""Purchase detectors — price movement and double entry.

Both rules here are controls rather than reminders: they look for a purchase
that was recorded wrongly or twice, which is money already out the door rather
than work still to do.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db.models import Count
from django.utils import timezone

from alerthub.constants import compare
from alerthub.engine import raise_alert
from alerthub.measures import pct, safe_url
from alerthub.scoping import rule_applies_to

from . import detector

#: Only recent purchases are checked. An old price jump is a report's job.
WINDOW_DAYS = 14


@detector("purchase.rate_difference")
def rate_difference(rule):
    """An item bought well above the last rate paid for it.

    The comparison is against the most recent *earlier* purchase of the same
    item, not an average: averages hide a steady climb, and what a buyer needs
    to see is "you paid more than last time, by this much".
    """
    from purchase.models import GeneralPurchaseItem

    today = timezone.localdate()
    recent = (
        GeneralPurchaseItem.objects.filter(
            purchase__date__gte=today - timedelta(days=WINDOW_DAYS),
            rate__gt=0,
        )
        .select_related("purchase", "purchase__supplier", "item", "farm_warehouse")
        .order_by("-purchase__date", "-id")
    )

    for line in recent:
        previous = (
            GeneralPurchaseItem.objects.filter(
                item_id=line.item_id, rate__gt=0,
                purchase__date__lt=line.purchase.date,
            )
            .order_by("-purchase__date", "-id")
            .select_related("purchase")
            .first()
        )
        if previous is None:
            continue                       # nothing to compare a first buy to

        rise = pct(line.rate - previous.rate, previous.rate)
        if rise is None or rise <= 0:
            continue
        if not compare(rise, rule.operator, rule.threshold):
            continue

        # Warehouse or farm — a purchase row now lands at either.
        scope = {"warehouse": line.farm_warehouse, "farm": line.farm}
        if not rule_applies_to(rule, **scope):
            continue

        raise_alert(
            rule,
            title="Rate Difference",
            message=(
                f"{line.item.description} bought at ₹{line.rate} on "
                f"{line.purchase.date:%d %b %Y} against ₹{previous.rate} on "
                f"{previous.purchase.date:%d %b %Y} — {rise:.1f}% higher "
                f"(limit {rule.threshold}%). Supplier "
                f"{line.purchase.supplier.name}."
            ),
            dedupe_key=f"{rule.pk}:rate_diff:{line.pk}",
            measured_value=round(rise, 3),
            threshold_value=rule.threshold,
            object_label="purchase.GeneralPurchase",
            object_id=line.purchase_id,
            object_display=line.purchase.purchase_no,
            voucher_no=line.purchase.purchase_no,
            action_url=safe_url("general_purchase_list"),
            metadata={"item": line.item.description,
                      "rate": str(line.rate),
                      "previous_rate": str(previous.rate),
                      "previous_purchase": previous.purchase.purchase_no},
            **scope,
        )


@detector("purchase.duplicate_invoice")
def duplicate_invoice(rule):
    """The same supplier bill number entered more than once.

    Keyed on (supplier, bill_no) because bill numbers are only unique within a
    supplier — two suppliers both numbering their bills "001" is normal and not
    a duplicate. Purchases with no bill number are skipped: a blank is not a
    match, and treating it as one would flag every cash purchase.
    """
    from purchase.models import GeneralPurchase

    today = timezone.localdate()
    window_start = today - timedelta(days=90)

    duplicates = (
        GeneralPurchase.objects.filter(date__gte=window_start)
        .exclude(bill_no="")
        .values("supplier_id", "bill_no")
        .annotate(count=Count("id"))
        .filter(count__gt=1)
    )

    for group in duplicates:
        rows = list(
            GeneralPurchase.objects.filter(
                supplier_id=group["supplier_id"], bill_no=group["bill_no"],
                date__gte=window_start,
            )
            .select_related("supplier")
            .order_by("date", "id")
        )
        if len(rows) < 2:
            continue

        first, *repeats = rows
        numbers = ", ".join(row.purchase_no for row in rows)
        if not rule_applies_to(rule):
            continue

        raise_alert(
            rule,
            title="Duplicate Invoice",
            message=(
                f"Bill {group['bill_no']} from {first.supplier.name} has been "
                f"entered {len(rows)} times — {numbers}."
            ),
            dedupe_key=f"{rule.pk}:dup_invoice:{group['supplier_id']}:"
                       f"{group['bill_no']}",
            measured_value=Decimal(len(rows)),
            object_label="purchase.GeneralPurchase",
            object_id=repeats[0].pk,
            object_display=repeats[0].purchase_no,
            voucher_no=group["bill_no"],
            action_url=safe_url("general_purchase_list"),
            metadata={"bill_no": group["bill_no"],
                      "purchases": [row.purchase_no for row in rows],
                      "supplier": first.supplier.name},
        )
