"""Dashboard widgets — the four numbers worth looking at before anything else.

Every widget **reuses the engine that already owns its figure** rather than
re-deriving it. That is not a style preference: this codebase has repeatedly
grown parallel copies of the same calculation which then drift apart (four
separate stock engines, each of which had to be fixed for the same Sent/
Received bug). A dashboard that disagrees with the report it links to is worse
than no dashboard, so:

* Stock alerts calls ``inventory.services.item_summary.negative_stock``.
* Receivables / Payables call the same per-party row builders the Customer and
  Supplier Balance reports use.
* Live Flock and Daily Entries aggregate straight off the transaction tables,
  using the same definitions the Live Flock report does (birds placed = chick-
  category stock transfers into the batch; alive = placed − mortality − culls −
  sold).

Each widget is gated on the tab codes of the report it links to, so the
dashboard can never show a figure from a module the user cannot open — the same
rule, and the same permission source, as the global search.

Filters (Date / Branch / Line / Supervisor / Farm) match the broiler reports'
filter bar. They are broiler-shaped, so they do not all apply to every widget:
Receivables & Payables is a party-level figure with no farm dimension at all,
and stock lives at locations rather than under a supervisor. Rather than
silently ignore a filter, each widget reports which ones it actually applied
and the card says so — a number that quietly ignored your filter is a wrong
number.
"""
import logging

from django.core.cache import cache
from django.db.models import Q
from django.utils import timezone

from user.access import allowed_view_tabs

logger = logging.getLogger(__name__)

# Widget payloads are the same for everyone who can see them, so the unfiltered
# ones are cached by widget and the permission filter runs after the cache read.
# Note LocMemCache is per-process: with several gunicorn workers each warms its
# own copy, so this trims repeat loads rather than guaranteeing one computation
# per interval. Filtered views are never cached — the key space is unbounded and
# a filtered dashboard is a deliberate, occasional query.
CACHE_SECONDS = 300

#: The filter bar, in the order it is drawn.
FILTER_KEYS = ("date", "branch", "line", "supervisor", "farm")

FILTER_LABELS = {"date": "Date", "branch": "Branch", "line": "Line",
                 "supervisor": "Supervisor", "farm": "Farm"}


def parse_filters(params):
    """Normalise the filter bar's querystring into typed values."""
    from django.utils.dateparse import parse_date

    out = dict.fromkeys(FILTER_KEYS)
    raw = (params.get("date") or "").strip()
    out["date"] = parse_date(raw) if raw else None
    for key in ("branch", "supervisor", "farm"):
        value = (params.get(key) or "").strip()
        out[key] = int(value) if value.isdigit() else None
    # Line is a CharField on BroilerFarm holding the line's name, not a foreign
    # key to BroilerLine — the same reason the Day Record report filters it as
    # a string.
    out["line"] = (params.get("line") or "").strip() or None
    return out


def _active(filters):
    return [k for k in FILTER_KEYS if filters.get(k)]


def _scope_farms(qs, filters, prefix):
    """Narrow a queryset that reaches a BroilerFarm through ``prefix``."""
    p = f"{prefix}__" if prefix else ""
    for key, field in (("farm", "id"), ("branch", "branch_id"),
                       ("line", "line"), ("supervisor", "supervisor_id")):
        if filters.get(key):
            qs = qs.filter(**{f"{p}{field}": filters[key]})
    return qs


def _batches_live_on(day, filters):
    """Flocks that were live on ``day``, narrowed by the farm-side filters.

    A batch counts as live if it had started by then and had not ended: either
    it is still running, or it ended *after* the day being asked about. The end
    date is the day the flock closed, so a batch ending on ``day`` is already
    finished — with no date filter this is exactly the report's "open" set.
    """
    from broiler.models import BroilerBatch

    qs = BroilerBatch.objects.filter(
        Q(start_date__lte=day) | Q(start_date__isnull=True)
    ).filter(
        Q(end_date__isnull=True, is_closed=False) | Q(end_date__gt=day)
    )
    return _scope_farms(qs, filters, "broiler_farm")


def _inr(value):
    """Indian-grouped rupees, no paise — dashboards are for magnitudes."""
    try:
        n = int(round(float(value or 0)))
    except (TypeError, ValueError):
        return "0"
    sign, n = ("-" if n < 0 else ""), abs(n)
    text = str(n)
    if len(text) > 3:                       # 1234567 -> 12,34,567
        head, tail = text[:-3], text[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        text = ",".join(parts) + "," + tail
    return sign + text


def _num(value):
    """Thousands-grouped integer for counts of birds, bags and so on."""
    try:
        return f"{int(round(float(value or 0))):,}"
    except (TypeError, ValueError):
        return "0"


def _pct(part, whole):
    try:
        part, whole = float(part or 0), float(whole or 0)
    except (TypeError, ValueError):
        return None
    return (part / whole * 100) if whole else None


def _tone_over(value, warn, bad):
    """Tone for a metric where higher is worse (mortality)."""
    if value is None:
        return None
    return "bad" if value >= bad else ("warn" if value >= warn else "good")


def _tone_under(value, warn, bad):
    """Tone for a metric where lower is worse (reporting completeness)."""
    if value is None:
        return None
    return "bad" if value < bad else ("warn" if value < warn else "good")


# ---------------------------------------------------------------------------
# Builders. Each returns the widget body, including "filters_used" so the card
# can be honest about which parts of the filter bar it could act on.
# ---------------------------------------------------------------------------

def _live_flock(viewable, filters):
    """Flocks live on the chosen date: birds alive, mortality, average age.

    Aggregated across the batches in a handful of queries rather than by running
    the per-batch costing engine N times — the report does the latter because it
    prints a row per flock; a dashboard only needs the totals.
    """
    from django.db.models import Sum
    from broiler.models import BirdSale, DailyEntry
    from inventory.models import Item, StockTransfer

    day = filters.get("date") or timezone.localdate()
    used = list(FILTER_KEYS)          # this widget can act on all five

    batches = list(_batches_live_on(day, filters).values_list("id", "start_date"))
    if not batches:
        return {"stats": [{"label": "Open batches", "value": "0"}],
                "note": "No live flocks match this filter.", "filters_used": used}

    ids = [b[0] for b in batches]
    chick_ids = list(Item.objects.filter(category__name__icontains="chick")
                     .values_list("id", flat=True))

    placed = StockTransfer.objects.filter(
        to_batch_id__in=ids, item_id__in=chick_ids, date__lte=day
    ).aggregate(t=Sum("quantity"))["t"] or 0
    losses = DailyEntry.objects.filter(batch_id__in=ids, date__lte=day).aggregate(
        m=Sum("mortality"), c=Sum("culls"))
    mort = float(losses["m"] or 0)
    culls = float(losses["c"] or 0)
    sold = float(BirdSale.objects.filter(batch_id__in=ids, date__lte=day)
                 .aggregate(b=Sum("birds"))["b"] or 0)

    placed = float(placed)
    alive = placed - mort - culls - sold
    mort_pct = _pct(mort + culls, placed)

    ages = [(day - s).days for _i, s in batches if s]
    avg_age = round(sum(ages) / len(ages)) if ages else None

    note = None
    if not chick_ids:
        note = "No item category matching “chick”, so birds placed cannot be counted."
    elif not placed:
        note = "No chick placements recorded against these batches yet."

    return {
        "stats": [
            {"label": "Open batches", "value": _num(len(batches))},
            {"label": "Birds alive", "value": _num(alive)},
            {"label": "Mortality",
             "value": ("—" if mort_pct is None else f"{mort_pct:.2f}%"),
             "sub": f"{_num(mort + culls)} incl. culls",
             "tone": _tone_over(mort_pct, warn=5, bad=8)},
            {"label": "Avg age", "value": ("—" if avg_age is None else f"{avg_age} d")},
        ],
        "note": note,
        "filters_used": used,
    }


def _daily_entries(viewable, filters):
    """Which live flocks have reported on the chosen day — and which have not.

    The point of this one is same-day: a missing entry is fixable this evening
    and awkward next week.
    """
    from broiler.models import DailyEntry

    day = filters.get("date") or timezone.localdate()
    used = list(FILTER_KEYS)

    batches = list(_batches_live_on(day, filters).select_related("broiler_farm"))
    if not batches:
        return {"stats": [{"label": "Expected", "value": "0"}],
                "note": "No live flocks match this filter.", "filters_used": used}

    reported = set(DailyEntry.objects.filter(
        batch_id__in=[b.id for b in batches], date=day)
        .values_list("batch_id", flat=True))
    missing = [b for b in batches if b.id not in reported]
    pct = _pct(len(reported), len(batches))

    rows = [{
        "label": (b.broiler_farm.farm_name if b.broiler_farm_id else "") or "—",
        "meta": b.batch_name or "",
    } for b in missing[:5]]

    return {
        "stats": [
            {"label": "Reported", "value": f"{len(reported)} of {len(batches)}",
             "sub": ("—" if pct is None else f"{pct:.0f}% of live flocks"),
             "tone": _tone_under(pct, warn=90, bad=60)},
            {"label": "Not yet in", "value": _num(len(missing)),
             "tone": "bad" if missing else "good"},
        ],
        "rows": rows,
        "rows_title": "Waiting on" if rows else None,
        "more": max(0, len(missing) - 5),
        "note": "Every live flock has reported." if not missing else None,
        "filters_used": used,
    }


def _balances(viewable, filters):
    """Receivables and payables, each half shown only to those who may see it.

    Both halves call the balance reports' own per-party row builders, so the
    dashboard total and the report total are the same number by construction.
    A customer's balance has no farm, line or supervisor dimension, so only the
    date applies — it becomes the "as on" date.
    """
    day = filters.get("date") or timezone.localdate()
    as_on = filters.get("date")          # None = all time, i.e. today's position
    stats, rows = [], []

    if "customer_balance" in viewable:
        from sales.models import Customer
        from sales.views import _customer_balance_row

        parties = [_customer_balance_row(c, None, as_on, day)
                   for c in Customer.objects.all()]
        owed = [p for p in parties if p["debit"] > 0]
        total = sum((p["debit"] for p in owed), 0)
        stats.append({"label": "Receivable", "value": "₹" + _inr(total),
                      "sub": f"from {len(owed)} customer{'' if len(owed) == 1 else 's'}",
                      "tone": "warn" if total else None})
        rows += [{"label": p["name"], "value": "₹" + _inr(p["debit"]),
                  "meta": f"{p['gap']}d"}
                 for p in sorted(owed, key=lambda p: -p["debit"])[:3]]

    if "supplier_balance" in viewable:
        from purchase.models import Supplier
        from purchase.views import _supplier_balance_row

        parties = [_supplier_balance_row(s, None, as_on, day)
                   for s in Supplier.objects.all()]
        due = [p for p in parties if p["credit"] > 0]
        total = sum((p["credit"] for p in due), 0)
        stats.append({"label": "Payable", "value": "₹" + _inr(total),
                      "sub": f"to {len(due)} supplier{'' if len(due) == 1 else 's'}",
                      "tone": "warn" if total else None})
        rows += [{"label": p["name"], "value": "₹" + _inr(p["credit"]),
                  "meta": f"{p['gap']}d"}
                 for p in sorted(due, key=lambda p: -p["credit"])[:3]]

    if not stats:
        return None
    return {
        "stats": stats,
        "rows": rows,
        "rows_title": "Largest outstanding" if rows else None,
        "note": "Nothing outstanding." if not rows else None,
        "filters_used": ["date"],
    }


def _stock_alerts(viewable, filters):
    """Negative balances — stock booked out of somewhere it was never booked in.

    These are always data errors, and they silently corrupt valuation until
    someone notices, which is exactly what a dashboard is for. Stock sits at a
    location, so Farm narrows it; Branch, Line and Supervisor have no meaning
    for a stock balance.
    """
    from inventory.services.item_summary import negative_stock

    farm_id = filters.get("farm")
    rows = negative_stock(as_of_date=filters.get("date"),
                          location_type="farm" if farm_id else None,
                          location_id=farm_id)
    used = ["date", "farm"]

    if not rows:
        return {"stats": [{"label": "Negative balances", "value": "0", "tone": "good"}],
                "note": "No negative stock anywhere.", "filters_used": used}

    worst = sorted(rows, key=lambda r: r["quantity"])[:5]
    return {
        "stats": [
            {"label": "Negative balances", "value": _num(len(rows)), "tone": "bad"},
            {"label": "Items affected", "value": _num(len({r["item_id"] for r in rows}))},
            {"label": "Locations", "value": _num(len({(r["location_type"], r["location_id"])
                                                      for r in rows}))},
        ],
        "rows": [{"label": r["item"], "value": _num(r["quantity"]),
                  "meta": r["location"]} for r in worst],
        "rows_title": "Worst offenders",
        "more": max(0, len(rows) - 5),
        "filters_used": used,
    }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

#: key, title, the tab codes that gate it, the page it links to, and its look.
WIDGETS = [
    ("live_flock", "Live Flock", ("live_flock_summary_report",),
     "live_flock_summary_report", "fa-solid fa-egg", "gs-blue", _live_flock),
    ("daily_entries", "Daily Entries", ("daily_entry_list",),
     "daily_entry_list", "fa-solid fa-clipboard-check", "gs-green", _daily_entries),
    ("balances", "Receivables & Payables",
     ("customer_balance", "supplier_balance"),
     "customer_balance", "fa-solid fa-indian-rupee-sign", "gs-orange", _balances),
    ("stock_alerts", "Stock Alerts", ("negative_stock_report",),
     "negative_stock_report", "fa-solid fa-triangle-exclamation", "gs-red", _stock_alerts),
]


def _link(url_name, viewable, filters):
    """The report link, carrying whatever of the filter the report understands."""
    from urllib.parse import urlencode
    from django.urls import NoReverseMatch, reverse

    if url_name not in viewable:
        return ""
    try:
        url = reverse(url_name)
    except NoReverseMatch:
        return ""
    # Only the broiler reports share this filter vocabulary; sending branch=3 to
    # the Customer Balance report would just be noise in its querystring.
    if url_name in ("live_flock_summary_report", "daily_entry_list"):
        carried = {k: (v.isoformat() if k == "date" else v)
                   for k, v in filters.items() if v}
        if carried:
            url += "?" + urlencode(carried)
    return url


def _ignored_note(filters, used):
    """Name the filters a widget could not act on, so a figure is never quietly
    unfiltered."""
    ignored = [FILTER_LABELS[k] for k in _active(filters) if k not in used]
    if not ignored:
        return None
    if len(ignored) == 1:
        return f"{ignored[0]} does not apply here."
    return f"{', '.join(ignored[:-1])} and {ignored[-1]} do not apply here."


def dashboard_widgets(user, filters=None, use_cache=True):
    """Widget payloads for everything ``user`` is allowed to see.

    One widget failing must not take the dashboard down with it, so a builder
    that raises is logged and rendered as a card that says so.
    """
    filters = filters or dict.fromkeys(FILTER_KEYS)
    viewable = allowed_view_tabs(user)
    # A filtered view is a deliberate question with an unbounded key space;
    # only the default dashboard is worth caching.
    use_cache = use_cache and not _active(filters)

    out = []
    for key, title, tabs, url_name, icon, colour, build in WIDGETS:
        if not any(t in viewable for t in tabs):
            continue
        card = {"key": key, "title": title, "icon": icon, "colour": colour,
                "url": _link(url_name, viewable, filters)}
        # The visible tabs are part of the key: Receivables & Payables builds a
        # different body for someone who may see only one of its two halves.
        seen = "|".join(sorted(t for t in tabs if t in viewable))
        cache_key = f"dash:widget:{key}:{seen}"
        body = cache.get(cache_key) if use_cache else None
        if body is None:
            try:
                body = build(viewable, filters) or {}
            except Exception:
                logger.exception("dashboard widget %r failed", key)
                body = {"error": True,
                        "note": "This figure could not be calculated just now."}
            else:
                if use_cache:
                    cache.set(cache_key, body, CACHE_SECONDS)
        card.update(body)
        card["ignored"] = _ignored_note(filters, card.get("filters_used") or [])
        out.append(card)
    return out
