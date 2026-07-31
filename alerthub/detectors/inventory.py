"""Inventory and health-stock detectors — balances, expiry and disease.

Medicine alerts live here rather than in a health module of their own because
they are stock questions wearing a health hat: "medicine expiring" is "item
expiring" filtered to a category. Sharing the implementation keeps the two from
disagreeing about what expiry means.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from alerthub.constants import compare
from alerthub.engine import raise_alert
from alerthub.measures import safe_url
from alerthub.scoping import rule_applies_to

from . import detector

#: Item categories treated as medicine/vaccine for the health rules. Matched
#: case-insensitively against the category name, the same loose match the Live
#: Flock widget uses for "chick".
MEDICINE_HINTS = ("medicine", "vaccine", "medicin")


def _medicine_item_ids():
    from django.db.models import Q

    from inventory.models import Item

    condition = Q()
    for hint in MEDICINE_HINTS:
        condition |= Q(category__name__icontains=hint)
    return list(Item.objects.filter(condition).values_list("id", flat=True))


# ---------------------------------------------------------------------------
# Balances
# ---------------------------------------------------------------------------

def _low_stock(rule, title, item_ids=None):
    """Items at or below a quantity at the warehouses that carry them.

    Bounded by ``Item.warehouse`` — the master already says which offices stock
    an item, so this checks that many pairs rather than every item against every
    warehouse, which on a real master is tens of thousands of balance
    reconciliations per scan.
    """
    from inventory.models import Item, warehouse_item_stock

    items = Item.objects.prefetch_related("warehouse").select_related("category")
    if item_ids is not None:
        if not item_ids:
            return
        items = items.filter(id__in=item_ids)

    for item in items:
        for warehouse in item.warehouse.all():
            scope = {"warehouse": warehouse}
            if not rule_applies_to(rule, **scope):
                continue

            balance = warehouse_item_stock(item.id, warehouse.id)
            if balance is None:
                continue
            balance = Decimal(str(balance))
            # Negative balances are a data error with their own, louder rule.
            # Reporting them here too would double-alert the same row.
            if balance < 0:
                continue
            if not compare(balance, rule.operator, rule.threshold):
                continue

            raise_alert(
                rule,
                title=title,
                message=(
                    f"{item.description} at {warehouse.name} is down to "
                    f"{balance} (limit {rule.threshold})."
                ),
                dedupe_key=f"{rule.pk}:low_stock:{item.id}:{warehouse.id}",
                measured_value=balance,
                threshold_value=rule.threshold,
                object_label="inventory.Item",
                object_id=item.id,
                object_display=item.description,
                action_url=safe_url("item_summary_report") or safe_url("item_list"),
                metadata={"warehouse": warehouse.name,
                          "category": item.category.name if item.category_id else ""},
                **scope,
            )


@detector("inventory.low_stock")
def low_stock(rule):
    _low_stock(rule, "Low Stock")


@detector("health.medicine_stock_low")
def medicine_stock_low(rule):
    _low_stock(rule, "Medicine Stock Low", item_ids=_medicine_item_ids())


@detector("inventory.negative_stock")
def negative_stock(rule):
    """Locations holding a negative balance.

    Delegates to ``inventory.services.item_summary.negative_stock`` — the same
    engine behind the Negative Stock report and the dashboard's Stock Alerts
    card. A second implementation here would be a fourth stock engine in a
    codebase that has already been burned by three.
    """
    from broiler.models import BroilerFarm
    from inventory.models import Warehouse
    from inventory.services.item_summary import negative_stock as find_negative

    rows = find_negative()
    if not rows:
        return

    warehouses = {w.pk: w for w in Warehouse.objects.filter(
        pk__in=[r["location_id"] for r in rows if r["location_type"] == "warehouse"]
    )}
    farms = {f.pk: f for f in BroilerFarm.objects.select_related("branch").filter(
        pk__in=[r["location_id"] for r in rows if r["location_type"] == "farm"]
    )}

    for row in rows:
        if row["location_type"] == "warehouse":
            warehouse = warehouses.get(row["location_id"])
            if warehouse is None:
                continue
            scope = {"warehouse": warehouse}
        else:
            farm = farms.get(row["location_id"])
            if farm is None:
                continue
            scope = {"farm": farm, "branch": getattr(farm, "branch", None)}

        if not rule_applies_to(rule, **scope):
            continue

        since = row.get("since")
        raise_alert(
            rule,
            title="Negative Stock",
            message=(
                f"{row['item']} at {row['location']} shows {row['quantity']} — "
                f"more has left than was ever booked in"
                + (f", first negative on {since:%d %b %Y}." if since else ".")
            ),
            dedupe_key=f"{rule.pk}:negative:{row['location_type']}:"
                       f"{row['location_id']}:{row['item_id']}",
            measured_value=Decimal(str(row["quantity"])),
            object_label="inventory.Item",
            object_id=row["item_id"],
            object_display=row["item"],
            action_url=safe_url("negative_stock_report"),
            metadata={"location": row["location"],
                      "location_type": row["location_type"],
                      "since": str(since) if since else ""},
            **scope,
        )


# ---------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------

def _expiry(rule, title, *, expired, item_ids=None):
    """Purchased batches past — or approaching — their expiry date.

    Expiry lives on the purchase document, so this reports the batch that
    expires rather than the item in general: two deliveries of the same vaccine
    expire on different days and only one of them is a problem.
    """
    from purchase.models import GeneralPurchase

    today = timezone.localdate()
    rows = GeneralPurchase.objects.filter(expiry_date__isnull=False).select_related(
        "supplier"
    ).prefetch_related("items__item", "items__farm_warehouse")

    if expired:
        rows = rows.filter(expiry_date__lt=today)
    else:
        window = int(rule.threshold or 30)
        rows = rows.filter(
            expiry_date__gte=today,
            expiry_date__lte=today + timedelta(days=window),
        )

    for purchase in rows:
        lines = list(purchase.items.all())
        if item_ids is not None:
            lines = [line for line in lines if line.item_id in set(item_ids)]
        if not lines:
            continue

        days = (purchase.expiry_date - today).days
        for line in lines:
            warehouse = line.farm_warehouse
            scope = {"warehouse": warehouse}
            if not rule_applies_to(rule, **scope):
                continue

            when = (
                f"expired {abs(days)} day(s) ago" if expired
                else f"expires in {days} day(s)"
            )
            raise_alert(
                rule,
                title=title,
                message=(
                    f"{line.item.description} from {purchase.supplier.name} "
                    f"(batch {purchase.batch_no or '—'}) {when} on "
                    f"{purchase.expiry_date:%d %b %Y}."
                ),
                dedupe_key=f"{rule.pk}:expiry:{purchase.pk}:{line.item_id}",
                measured_value=Decimal(days),
                threshold_value=None if expired else rule.threshold,
                object_label="purchase.GeneralPurchase",
                object_id=purchase.pk,
                object_display=purchase.purchase_no,
                voucher_no=purchase.purchase_no,
                action_url=safe_url("general_purchase_list"),
                metadata={"item": line.item.description,
                          "batch_no": purchase.batch_no,
                          "expiry_date": str(purchase.expiry_date)},
                **scope,
            )


@detector("inventory.item_expired")
def item_expired(rule):
    _expiry(rule, "Item Expired", expired=True)


@detector("inventory.item_near_expiry")
def item_near_expiry(rule):
    _expiry(rule, "Item Near Expiry", expired=False)


@detector("health.medicine_expired")
def medicine_expired(rule):
    _expiry(rule, "Medicine Expired", expired=True, item_ids=_medicine_item_ids())


@detector("health.medicine_expiring")
def medicine_expiring(rule):
    _expiry(rule, "Medicine Expiring Soon", expired=False,
            item_ids=_medicine_item_ids())


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@detector("health.disease_alert")
def disease_alert(rule):
    """Diseases diagnosed against a flock in the last fortnight.

    Every diagnosis is worth telling people about, so there is no threshold —
    the window exists only to stop a scan re-reading the whole history.
    """
    from broiler.models import BroilerDisease

    since = timezone.localdate() - timedelta(days=14)
    rows = BroilerDisease.objects.filter(diagnosed_date__gte=since).select_related(
        "batch", "batch__broiler_farm", "batch__broiler_farm__branch"
    )

    for disease in rows:
        batch = disease.batch
        if batch is None:
            continue
        farm = batch.broiler_farm
        scope = {"farm": farm, "branch": getattr(farm, "branch", None)}
        if not rule_applies_to(rule, **scope):
            continue

        raise_alert(
            rule,
            title="Disease Alert",
            message=(
                f"{disease.disease_name} diagnosed on batch {batch.batch_name} at "
                f"{farm.farm_name} ({disease.diagnosed_date:%d %b %Y}). "
                f"{(disease.symptoms or '')[:160]}"
            ).strip(),
            dedupe_key=f"{rule.pk}:disease:{disease.pk}",
            object_label="broiler.BroilerDisease",
            object_id=disease.pk,
            object_display=disease.disease_name,
            action_url=safe_url("broiler_disease"),
            metadata={"disease_code": disease.disease_code,
                      "diagnosed": str(disease.diagnosed_date)},
            **scope,
        )
