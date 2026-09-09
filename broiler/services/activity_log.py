"""Recent activity across the broiler farms — the engine behind both the
dashboard's "Broiler — Recent Activity" widget and the full Recent Activity
Log page (Broiler > Reports). One gathering function so the two can never
disagree about what counts as an event or how it is scoped.

Every row is a real transaction record: StockTransfer (chick/feed category),
MedicineVaccineEntry, DailyEntry and BirdSale, plus a negative-stock alert
from the same engine the Stock Alerts widget uses. Two things worth knowing
before extending this: "Bird Lifting" and "Bird Sale" are the same row
(BirdSale) under two names in the rest of the app, so they get one activity
type here rather than two; and there is no minimum-stock/reorder-threshold
concept anywhere in Item, only negative-balance detection, so the stock row
reports a negative balance rather than a fabricated "below threshold"
warning.
"""
from datetime import timedelta

from django.utils import timezone


def activity_who(user):
    """(display name, initials) for an activity row, or (None, None) when the
    entry has no recorded user — an alert the system raised, not a person's
    action, and a fabricated name would misattribute it."""
    if user is None:
        return None, None
    name = user.get_full_name() or user.username
    parts = [p for p in name.split() if p]
    initials = (parts[0][0] + parts[-1][0]).upper() if len(parts) > 1 else name[:2].upper()
    return name, initials


def activity_ago(when):
    """"2 hours ago" — timesince()'s own wording, trimmed to its first unit
    so a row reads "3 hours ago" rather than "3 hours, 12 minutes ago"."""
    from django.utils.timesince import timesince

    return f"{timesince(when, timezone.now()).split(',')[0]} ago"


def as_datetime(when):
    """negative_stock's `since` is a plain date; every other source's `when`
    is already a datetime. Normalised once here rather than at every call
    site that needs to sort or compare them."""
    if isinstance(when, timezone.datetime):
        return when
    return timezone.make_aware(timezone.datetime.combine(when, timezone.datetime.min.time()))


def gather_events(filters, user, window_days=7):
    """Every event in the window, newest first, scoped to what ``user`` may
    see. ``when`` stays a real datetime (or date, for the stock-alert rows)
    — callers that only need a display string call ``activity_ago`` on it
    themselves; a table with a Date & Time column and a day-by-day trend
    chart both need more than the widget's rounded-off "2 hours ago" did.
    """
    from broiler.models import BirdSale, BroilerFarm, DailyEntry, MedicineVaccineEntry
    from inventory.models import Item, StockTransfer
    from inventory.services.item_summary import negative_stock
    from user.services.dashboard_widgets import FILTER_KEYS, _scope_farms, _scope_to_user
    from user.services.scoping import allowed_ids

    day = filters.get("date") or timezone.localdate()
    window_start = day - timedelta(days=window_days)

    def scoped(qs, prefix):
        qs = _scope_farms(qs, filters, prefix)
        return qs if user is None else _scope_to_user(qs, user, prefix)

    chick_ids = set(Item.objects.filter(category__name__icontains="chick")
                    .values_list("id", flat=True))
    feed_ids = set(Item.objects.filter(category__name__icontains="feed")
                   .values_list("id", flat=True))

    events = []

    transfers = scoped(
        StockTransfer.objects.filter(
            date__gte=window_start, date__lte=day,
            item_id__in=chick_ids | feed_ids, to_farm__isnull=False,
        ), "to_farm"
    ).select_related("item", "to_farm", "to_batch", "to_batch__breed", "created_by")
    for t in transfers:
        farm = t.to_farm.farm_name if t.to_farm_id else "—"
        batch = f"Batch {t.to_batch.batch_name}" if t.to_batch_id and t.to_batch.batch_name else None
        name, initials = activity_who(t.created_by)
        common = {"farm": farm, "farm_id": t.to_farm_id, "batch": batch,
                  "batch_id": t.to_batch_id, "user_name": name,
                  "user_id": t.created_by_id, "user_initials": initials,
                  "when": t.created_at}
        if t.item_id in chick_ids:
            breed = (t.to_batch.breed.description
                    if t.to_batch_id and t.to_batch.breed_id else None)
            events.append({
                "category": "placement", "icon": "fa-solid fa-kiwi-bird", "colour": "dw-c-amber",
                "title": "Chicks Placed", "subtitle": "Placement recorded",
                "metric": f"{t.quantity:,.0f} chicks", "metric_sub": breed,
                "status": "Completed", "tone": "good", **common,
            })
        else:
            events.append({
                "category": "feed", "icon": "fa-solid fa-sack", "colour": "dw-c-blue",
                "title": "Feed Issued", "subtitle": "Feed issued from store",
                "metric": f"{t.quantity:,.0f} kg", "metric_sub": t.item.description,
                "status": "Completed", "tone": "good", **common,
            })

    meds = scoped(
        MedicineVaccineEntry.objects.filter(date__gte=window_start, date__lte=day),
        "farm"
    ).select_related("item", "farm", "batch", "entry_by")
    for m in meds:
        name, initials = activity_who(m.entry_by)
        events.append({
            "category": "medicine", "icon": "fa-solid fa-syringe", "colour": "dw-c-cyan",
            "title": "Medicine Given", "subtitle": m.item.description if m.item_id else "Medicine/vaccine entry",
            "farm": m.farm.farm_name if m.farm_id else "—", "farm_id": m.farm_id,
            "batch": f"Batch {m.batch.batch_name}" if m.batch_id and m.batch.batch_name else None,
            "batch_id": m.batch_id,
            "metric": (f"{m.qty:,.0f} {m.item.consumption_uom.name}"
                      if m.item_id and m.item.consumption_uom_id else f"{m.qty:,.0f}"),
            "metric_sub": None,
            "status": "Completed", "tone": "good",
            "user_name": name, "user_id": m.entry_by_id, "user_initials": initials,
            "when": m.entry_time,
        })

    entries = scoped(
        DailyEntry.objects.filter(date__gte=window_start, date__lte=day),
        "farm"
    ).select_related("farm", "batch", "entry_by")
    for e in entries:
        name, initials = activity_who(e.entry_by)
        farm = e.farm.farm_name if e.farm_id else "—"
        batch = f"Batch {e.batch.batch_name}" if e.batch_id and e.batch.batch_name else None
        common = {"farm": farm, "farm_id": e.farm_id, "batch": batch,
                  "batch_id": e.batch_id, "user_name": name,
                  "user_id": e.entry_by_id, "user_initials": initials,
                  "when": e.entry_time}
        losses = (e.mortality or 0) + (e.culls or 0)
        if losses > 0:
            events.append({
                "category": "mortality", "icon": "fa-solid fa-skull", "colour": "dw-c-red",
                "title": "Mortality Entry", "subtitle": "Daily mortality recorded",
                "metric": f"{losses:,.0f} birds", "metric_sub": None,
                "status": "Attention", "tone": "warn", **common,
            })
        else:
            events.append({
                "category": "daily_entry", "icon": "fa-solid fa-clipboard-check", "colour": "dw-c-green",
                "title": "Daily Entry", "subtitle": "Production data updated",
                "metric": (f"Avg wt. {e.avg_weight_gms:,.0f} g" if e.avg_weight_gms else "—"),
                "metric_sub": None,
                "status": "Updated", "tone": "neutral", **common,
            })

    lifts = scoped(
        BirdSale.objects.filter(date__gte=window_start, date__lte=day),
        "farm"
    ).select_related("farm", "batch", "customer", "farmer", "entry_by")
    for s in lifts:
        name, initials = activity_who(s.entry_by)
        buyer = (s.customer.customer_name if s.customer_id and hasattr(s.customer, "customer_name")
                else (str(s.customer) if s.customer_id else (str(s.farmer) if s.farmer_id else None)))
        events.append({
            "category": "lifting", "icon": "fa-solid fa-truck-fast", "colour": "dw-c-purple",
            "title": "Bird Sale", "subtitle": f"Lifted to {buyer}" if buyer else "Birds lifted",
            "farm": s.farm.farm_name if s.farm_id else "—", "farm_id": s.farm_id,
            "batch": f"Batch {s.batch.batch_name}" if s.batch_id and s.batch.batch_name else None,
            "batch_id": s.batch_id,
            "metric": f"{s.birds:,.0f} birds", "metric_sub": f"{s.net_weight:,.0f} kg",
            "status": "Completed", "tone": "good",
            "user_name": name, "user_id": s.entry_by_id, "user_initials": initials,
            "when": s.entry_time,
        })

    # Stock alerts carry no responsible user in negative_stock's own data — an
    # alert the system raised by replaying transactions, not an entry someone
    # made — so that column is left blank rather than guessed.
    stock_rows = [r for r in negative_stock(as_of_date=day, location_type="farm")
                  if r["item_id"] in feed_ids]
    farm_filters = {k: filters[k] for k in ("branch", "line", "supervisor", "farm") if filters.get(k)}
    if farm_filters:
        fqs = BroilerFarm.objects.all()
        for key, field in (("branch", "branch_id"), ("line", "line"),
                          ("supervisor", "supervisor_id"), ("farm", "id")):
            if key in farm_filters:
                fqs = fqs.filter(**{field: farm_filters[key]})
        allowed_farm_ids = set(fqs.values_list("id", flat=True))
        stock_rows = [r for r in stock_rows if r["location_id"] in allowed_farm_ids]
    if user is not None:
        limit = allowed_ids(user, "farms")
        if limit is not None:
            stock_rows = [r for r in stock_rows if r["location_id"] in limit]
    for r in stock_rows:
        if r["since"] < window_start:
            continue
        events.append({
            "category": "stock", "icon": "fa-solid fa-triangle-exclamation", "colour": "dw-c-red",
            "title": "Feed Stock Alert", "subtitle": "Stock balance went negative",
            "farm": r["location"], "farm_id": r["location_id"], "batch": None, "batch_id": None,
            "metric": f"{r['quantity']:,.0f} kg", "metric_sub": r["item"],
            "status": "Low Stock", "tone": "bad",
            "user_name": None, "user_id": None, "user_initials": None,
            "when": r["since"],
        })

    events.sort(key=lambda e: as_datetime(e["when"]), reverse=True)
    return events


#: (key, label, chart colour) in the order the filter pills and the legends
#: read. One list so the pills, the donut and the trend chart can never drift
#: apart on either naming or colour.
CATEGORIES = [
    ("daily_entry", "Daily Entry", "#2563eb"),
    ("feed", "Feed", "#f59e0b"),
    ("medicine", "Medicine", "#ec4899"),
    ("mortality", "Mortality", "#dc2626"),
    ("lifting", "Sale", "#7c3aed"),
    ("placement", "Chicks Placement", "#16a34a"),
    ("stock", "Others", "#64748b"),
]
