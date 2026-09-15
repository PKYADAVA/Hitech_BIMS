"""Item Price List — the current-price view, price history, bulk revisions and
uploads.

The list is a dated history: an item's price on a day is its most recent entry
effective on or before that day, which is what transfers are valued at
(inventory.services.pricing.item_issue_price). Everything here reads the
history the same way, so the price this page calls Active is the price a
transfer made today would take.
"""
import csv
import io
from collections import defaultdict
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from inventory.models import Item, ItemPriceList, ItemPriceListAudit

TWO_PLACES = Decimal("0.01")
MAX_ROWS = 5000
#: A repricing from the last purchase that moves a price by more than this is
#: flagged in the preview: usually a unit mismatch rather than a real change.
LARGE_CHANGE_PCT = 50

STATUS_ACTIVE = "active"
STATUS_UPCOMING = "upcoming"
STATUS_NOT_PRICED = "not_priced"
STATUS_SUPERSEDED = "superseded"
STATUS_INACTIVE = "inactive"
STATUS_LABELS = {
    STATUS_INACTIVE: "Inactive",
    STATUS_ACTIVE: "Active",
    STATUS_UPCOMING: "Upcoming",
    STATUS_NOT_PRICED: "Not Priced",
    STATUS_SUPERSEDED: "Superseded",
}


class PriceRowError(ValueError):
    """A revision or upload that cannot be used as asked; the message says why."""


# --- small readers -----------------------------------------------------------

def _money(value):
    return Decimal(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def _text(value):
    return None if value is None else str(_money(value))


def _pct(new, old):
    if new is None or not old:
        return None
    change = (Decimal(new) - Decimal(old)) / Decimal(old) * 100
    return str(change.quantize(TWO_PLACES, rounding=ROUND_HALF_UP))


def _iso(value):
    return value.isoformat() if value else None


def _unit(item):
    uom = item.storage_uom or item.consumption_uom
    if not uom:
        return ""
    return uom.symbol or uom.name


_KG = {"kg", "kgs", "kilogram", "kilograms"}
_BAG = {"bag", "bags"}


def _unit_kind(text):
    value = (text or "").strip().lower()
    if value in _KG:
        return "kg"
    if value in _BAG:
        return "bag"
    return value


def purchase_rate_per_price_unit(item, rate, unit):
    """A purchase rate restated in the unit the item is priced in.

    Bills are typed per whatever unit the supplier sold in, and the price list
    is per the item's own unit, so a feed bought at 42 per Kg and priced at
    2,000 per Bag cannot be compared as it stands. Kg and Bag convert through
    the item's Kg per Bag. None when the two units cannot be matched: a wrong
    comparison is worse than none. A blank unit on either side is taken as the
    same unit."""
    if rate is None:
        return None
    rate = Decimal(str(rate))
    have, want = _unit_kind(unit), _unit_kind(_unit(item))
    if not have or not want or have == want:
        return _money(rate)
    per_bag = Decimal(str(item.kg_per_bag)) if item.kg_per_bag else None
    if per_bag and have == "kg" and want == "bag":
        return _money(rate * per_bag)
    if per_bag and have == "bag" and want == "kg":
        return _money(rate / per_bag)
    return None


def parse_date(value):
    """A date from a form, JSON or a spreadsheet cell: a date, an ISO string,
    or DD-MM-YYYY / DD.MM.YYYY / DD/MM/YYYY."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_price(value):
    """A price rounded to paise, None when blank. Raises PriceRowError when
    the value is not a number."""
    if value is None or str(value).strip() == "":
        return None
    try:
        price = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        raise PriceRowError("not a number")
    if not price.is_finite():
        raise PriceRowError("not a number")
    return _money(price)


def _clean_ids(values):
    ids = []
    for value in values or []:
        text = str(value).strip()
        if text.isdigit() and int(text) not in ids:
            ids.append(int(text))
    return ids


def _entries_by_item(item_ids):
    """Each item's price entries, newest effective date first."""
    grouped = defaultdict(list)
    entries = (ItemPriceList.objects.filter(item_id__in=item_ids)
               .order_by("-effective_date", "-id"))
    for entry in entries:
        grouped[entry.item_id].append(entry)
    return grouped


def _in_force(entries, on_date):
    return next((e for e in entries if e.effective_date <= on_date), None)


def current_prices(item_ids, today=None):
    """Each item's price in force today, as ``{item_id: {"price", "date"}}``.
    Items with no price in force are absent."""
    today = today or timezone.localdate()
    prices = {}
    for item_id, entries in _entries_by_item(list(item_ids)).items():
        entry = _in_force(entries, today)
        if entry:
            prices[item_id] = {"price": _text(entry.price), "date": _iso(entry.effective_date)}
    return prices


def last_purchase_rates(item_ids):
    """The rate on each item's most recent purchase bill, as
    ``{item_id: {"rate", "unit", "date", "supplier", "ref", "source"}}``.

    Read from General, Chicks and Egg purchases. The latest bill date wins,
    and on the same date the line entered last. It is the rate typed on the
    bill, per the unit on that line, not a landed cost. A line with no rate
    (a free or sample delivery) is passed over rather than shown as a price of
    nothing, and an item never bought is absent."""
    from hatchery.models import EggPurchaseItem
    from purchase.models import ChicksPurchaseItem, GeneralPurchaseItem

    ids = [item_id for item_id in item_ids if item_id]
    if not ids:
        return {}
    best = {}

    def offer(item_id, when, order, rate, unit, supplier, ref, source):
        key = (when, order)
        if item_id in best and best[item_id]["_key"] >= key:
            return
        best[item_id] = {
            "_key": key, "rate": _text(rate), "unit": unit or "",
            "date": _iso(when), "supplier": supplier or "", "ref": ref or "",
            "source": source,
        }

    general = (GeneralPurchaseItem.objects.filter(item_id__in=ids, rate__gt=0)
               .select_related("purchase__supplier")
               .order_by("item_id", "-purchase__date", "-id").distinct("item_id"))
    for line in general:
        offer(line.item_id, line.purchase.date, (3, line.id), line.rate, line.unit,
              line.purchase.supplier.name, line.purchase.purchase_no, "General Purchase")

    chicks = (ChicksPurchaseItem.objects.filter(purchase__item_id__in=ids, rate__gt=0)
              .select_related("purchase__supplier")
              .order_by("purchase__item_id", "-purchase__date", "-id")
              .distinct("purchase__item_id"))
    for line in chicks:
        offer(line.purchase.item_id, line.purchase.date, (2, line.id), line.rate, "",
              line.purchase.supplier.name, line.purchase.purchase_no, "Chicks Purchase")

    eggs = (EggPurchaseItem.objects.filter(item_id__in=ids, rate__gt=0)
            .select_related("egg_purchase__supplier")
            .order_by("item_id", "-egg_purchase__date", "-id").distinct("item_id"))
    for line in eggs:
        offer(line.item_id, line.egg_purchase.date, (1, line.id), line.rate, "",
              line.egg_purchase.supplier.name, line.egg_purchase.transaction_no, "Egg Purchase")

    for value in best.values():
        value.pop("_key")
    return best


def _item_info(item):
    return {
        "item": item.id,
        "item_code": item.item_code,
        "item_name": item.description,
        "category": item.category.name if item.category_id else "",
        "category_id": item.category_id,
        "unit": _unit(item),
        "is_active": item.is_active,
    }


# --- the list ----------------------------------------------------------------

def price_overview(today=None, category=None, status=None, search=None, item_ids=None):
    """Every item once, with the price in force today, the one before it and
    any price already set for a later date.

    Active: priced today. Upcoming: only priced from a later date. Not Priced:
    no price at all, so a transfer of it would be refused."""
    today = today or timezone.localdate()
    items = (Item.objects.select_related("category", "storage_uom", "consumption_uom")
             .order_by("item_code"))
    if item_ids is not None:
        items = items.filter(id__in=list(item_ids))
    if category and str(category).isdigit():
        items = items.filter(category_id=int(category))
    if search and search.strip():
        term = search.strip()
        items = items.filter(Q(item_code__icontains=term) | Q(description__icontains=term))
    items = list(items)
    grouped = _entries_by_item([item.id for item in items])
    purchases = last_purchase_rates([item.id for item in items])

    rows = []
    for item in items:
        entries = grouped.get(item.id, [])
        past = [e for e in entries if e.effective_date <= today]
        future = [e for e in entries if e.effective_date > today]
        current = past[0] if past else None
        previous = past[1] if len(past) > 1 else None
        upcoming = future[-1] if future else None

        if current:
            state, shown = STATUS_ACTIVE, current
        elif upcoming:
            state, shown = STATUS_UPCOMING, upcoming
        else:
            state, shown = STATUS_NOT_PRICED, None
        if not item.is_active:
            # One status per row: an item out of use reads Inactive, whatever
            # its price. The price itself still shows.
            state = STATUS_INACTIVE

        row = _item_info(item)
        row.update({
            "entry": shown.id if shown else None,
            "price": _text(shown.price) if shown else None,
            "effective_date": _iso(shown.effective_date) if shown else None,
            "previous_price": _text(previous.price) if current and previous else None,
            "previous_date": _iso(previous.effective_date) if current and previous else None,
            "change_pct": _pct(current.price, previous.price) if current and previous else None,
            "next_price": _text(upcoming.price) if current and upcoming else None,
            "next_date": _iso(upcoming.effective_date) if current and upcoming else None,
            "status": state,
            "status_label": STATUS_LABELS[state],
            "entries": len(entries),
            "last_purchase": purchases.get(item.id),
            "cost_rate": None,
            "margin_pct": None,
            "below_cost": False,
            "cost_note": "",
        })
        purchase = purchases.get(item.id)
        if purchase and shown:
            cost = purchase_rate_per_price_unit(item, purchase["rate"], purchase["unit"])
            if cost is None:
                row["cost_note"] = ("Bought per %s, priced per %s. Set the item's Kg per Bag "
                                    "or check the units to compare." % (purchase["unit"], _unit(item)))
            elif cost > 0:
                row["cost_rate"] = str(cost)
                row["margin_pct"] = _pct(shown.price, cost)
                row["below_cost"] = shown.price < cost
        rows.append(row)

    if status and status != "all":
        rows = [row for row in rows if row["status"] == status]
    return rows


# --- server-side paging ------------------------------------------------------

#: The list columns the database can sort by, keyed by the column's data name.
#: Last purchase, previous price, change and margin are worked out per row and
#: cannot be sorted in the query, so they are not offered.
ORDERABLE = {
    "item_code": "item_code",
    "item_name": "description",
    "category": "category__name",
    "unit": "storage_uom__symbol",
    "price": "shown_price",
    "effective_date": "shown_date",
    "status": "state",
}


def _annotated_items(today, category=None, search=None):
    """Items with their shown price, date and status worked out in the query,
    so the list can be filtered, counted, sorted and paged by the database."""
    from django.db.models import CharField, OuterRef, Subquery, Value, When, Case
    from django.db.models.functions import Coalesce

    entries = ItemPriceList.objects.filter(item=OuterRef("pk"))
    current = entries.filter(effective_date__lte=today).order_by("-effective_date", "-id")
    upcoming = entries.filter(effective_date__gt=today).order_by("effective_date", "id")
    items = (Item.objects
             .annotate(cur_price=Subquery(current.values("price")[:1]),
                       cur_date=Subquery(current.values("effective_date")[:1]),
                       up_price=Subquery(upcoming.values("price")[:1]),
                       up_date=Subquery(upcoming.values("effective_date")[:1]))
             .annotate(shown_price=Coalesce("cur_price", "up_price"),
                       shown_date=Coalesce("cur_date", "up_date"),
                       state=Case(
                           When(is_active=False, then=Value(STATUS_INACTIVE)),
                           When(cur_date__isnull=False, then=Value(STATUS_ACTIVE)),
                           When(up_date__isnull=False, then=Value(STATUS_UPCOMING)),
                           default=Value(STATUS_NOT_PRICED),
                           output_field=CharField())))
    if category and str(category).isdigit():
        items = items.filter(category_id=int(category))
    if search and search.strip():
        term = search.strip()
        items = items.filter(Q(item_code__icontains=term) | Q(description__icontains=term))
    return items


def _rows_in_order(ids, today):
    if not ids:
        return []
    by_id = {row["item"]: row for row in price_overview(today=today, item_ids=ids)}
    return [by_id[item_id] for item_id in ids if item_id in by_id]


def _filtered(today, category, status, search, order_by="item_code", descending=False):
    from django.db.models import F

    base = _annotated_items(today, category, search)
    filtered = base if not status or status == "all" else base.filter(state=status)
    field = ORDERABLE.get(order_by, "item_code")
    ordering = F(field).desc(nulls_last=True) if descending else F(field).asc(nulls_last=True)
    return base, filtered.order_by(ordering, "item_code")


def price_overview_page(today=None, category=None, status=None, search=None, below_cost=False,
                        start=0, length=25, order_by="item_code", descending=False):
    """One page of the list, with the totals DataTables needs.

    Only the page's rows are built in full (last purchase, margin, previous
    price), so the work per request follows the page size, not the size of
    the item master. Below cost is the one filter the database cannot answer,
    as it needs the restated purchase rate, so with it on the rows are built
    for everything matching and filtered here."""
    from django.db.models import Count

    today = today or timezone.localdate()
    base, filtered = _filtered(today, category, status, search, order_by, descending)
    counts = base.aggregate(
        all=Count("id"),
        active=Count("id", filter=Q(state=STATUS_ACTIVE)),
        inactive=Count("id", filter=Q(state=STATUS_INACTIVE)),
        upcoming=Count("id", filter=Q(state=STATUS_UPCOMING)),
        not_priced=Count("id", filter=Q(state=STATUS_NOT_PRICED)))
    start = max(int(start or 0), 0)
    ids = filtered.values_list("id", flat=True)
    if below_cost:
        rows = [row for row in _rows_in_order(list(ids), today) if row["below_cost"]]
        matching = len(rows)
        page = rows[start:] if length < 0 else rows[start:start + length]
    else:
        matching = filtered.count()
        page_ids = list(ids[start:] if length < 0 else ids[start:start + length])
        page = _rows_in_order(page_ids, today)
    return {"records_total": Item.objects.count(), "records_filtered": matching,
            "rows": page, "counts": counts}


def matching_item_ids(today=None, category=None, status=None, search=None, below_cost=False):
    """Every item id the current filters match, across all pages: what Select
    all and a Bulk Revise with nothing ticked work on."""
    today = today or timezone.localdate()
    _base, filtered = _filtered(today, category, status, search)
    ids = list(filtered.values_list("id", flat=True))
    if below_cost:
        return [row["item"] for row in _rows_in_order(ids, today) if row["below_cost"]]
    return ids


def active_item_options():
    """The active items, for the Add Prices dropdown."""
    return [{"id": item.id, "label": f"{item.item_code} - {item.description}"}
            for item in Item.objects.active().order_by("item_code")]


def last_price_change():
    """When a price was last created, edited or deleted, in local time."""
    stamp = ItemPriceListAudit.objects.aggregate(last=Max("created_at"))["last"]
    return timezone.localtime(stamp) if stamp else None


def audit_rows(item_id=None, limit=500, date_from=None, date_to=None,
               action=None, source=None, user=None):
    logs = ItemPriceListAudit.objects.select_related("user").order_by("-created_at", "-id")
    if item_id and str(item_id).isdigit():
        logs = logs.filter(item_ref=int(item_id))
    start, end = parse_date(date_from), parse_date(date_to)
    if start:
        logs = logs.filter(created_at__date__gte=start)
    if end:
        logs = logs.filter(created_at__date__lte=end)
    if action:
        logs = logs.filter(action=action)
    if source:
        logs = logs.filter(source=source)
    if user:
        logs = logs.filter(user_label=user)
    rows = []
    for log in logs[:limit]:
        by = log.user_label
        if not by and log.user_id:
            by = log.user.get_full_name() or log.user.get_username()
        rows.append({
            "id": log.id,
            "when": timezone.localtime(log.created_at).strftime("%d %b %Y %I:%M %p"),
            "item": log.item_label,
            "item_ref": log.item_ref,
            "action": log.action,
            "action_label": log.get_action_display(),
            "old_price": _text(log.old_price),
            "new_price": _text(log.new_price),
            "old_date": _iso(log.old_effective_date),
            "new_date": _iso(log.new_effective_date),
            "by": by or "System",
            "source": log.source,
            "note": log.note,
        })
    return rows


def price_usage(entry):
    """Saved transfers dated inside this price's span: from its effective
    date up to the item's next dated price.

    Those transfers keep the rate they were saved with, so changing or
    deleting the price does not revalue them, but a transfer entered later for
    one of those dates takes the changed price. Shown before an edit or a
    delete so that is known first."""
    from inventory.models import MedicineTransferItem, StockTransfer

    later = (ItemPriceList.objects
             .filter(item_id=entry.item_id, effective_date__gt=entry.effective_date)
             .order_by("effective_date").values_list("effective_date", flat=True).first())
    stock = StockTransfer.objects.filter(item_id=entry.item_id, date__gte=entry.effective_date)
    medicine = MedicineTransferItem.objects.filter(
        item_id=entry.item_id, transfer__date__gte=entry.effective_date)
    if later:
        stock = stock.filter(date__lt=later)
        medicine = medicine.filter(transfer__date__lt=later)
    return {
        "from": _iso(entry.effective_date),
        "until": _iso(later),
        "stock_transfers": stock.count(),
        "medicine_transfers": medicine.count(),
    }


def audit_filter_options():
    """The sources and people that appear in the change log, for its filters."""
    sources = set(ItemPriceListAudit.objects.values_list("source", flat=True))
    users = set(ItemPriceListAudit.objects.values_list("user_label", flat=True))
    return {"sources": sorted(s for s in sources if s), "users": sorted(u for u in users if u)}


def item_price_history(item, today=None):
    """All of one item's prices, newest first, each marked Upcoming, Active or
    Superseded, with its change against the price before it."""
    today = today or timezone.localdate()
    entries = list(item.price_list_entries.order_by("-effective_date", "-id"))
    current = _in_force(entries, today)
    rows = []
    for index, entry in enumerate(entries):
        older = entries[index + 1] if index + 1 < len(entries) else None
        if entry.effective_date > today:
            state = STATUS_UPCOMING
        elif current and entry.id == current.id:
            state = STATUS_ACTIVE
        else:
            state = STATUS_SUPERSEDED
        rows.append({
            "id": entry.id,
            "price": _text(entry.price),
            "effective_date": _iso(entry.effective_date),
            "change_pct": _pct(entry.price, older.price) if older else None,
            "status": state,
            "status_label": STATUS_LABELS[state],
        })
    return {
        "item": _item_info(item),
        "last_purchase": last_purchase_rates([item.id]).get(item.id),
        "today": today.isoformat(),
        "entries": rows,
        "audit": audit_rows(item_id=item.id, limit=200),
    }


# --- bulk revision -----------------------------------------------------------

def revise_preview(item_ids, mode, value, effective_date):
    """New prices for a revision by a percentage or a fixed amount, worked
    from each item's price in force on the new effective date. Saves nothing.

    Each row is "create" (a new dated price), "replace" (the item already has
    a price on that date) or "skip" with the reason."""
    if mode not in ("percent", "amount", "purchase"):
        raise PriceRowError("Choose a percentage, a fixed amount or the last purchase rate.")
    try:
        value = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise PriceRowError("Enter the revision as a number.")
    if not value.is_finite() or (value == 0 and mode != "purchase"):
        raise PriceRowError("Enter a revision other than zero.")
    if mode in ("percent", "purchase") and value <= -100:
        raise PriceRowError("A decrease must be less than 100%.")
    on_date = parse_date(effective_date)
    if not on_date:
        raise PriceRowError("Choose the effective date for the new prices.")
    ids = _clean_ids(item_ids)
    if not ids:
        raise PriceRowError("Select at least one item to revise.")
    if len(ids) > MAX_ROWS:
        raise PriceRowError("Revise at most %d items at a time." % MAX_ROWS)

    items = list(Item.objects.filter(id__in=ids).select_related(
        "category", "storage_uom", "consumption_uom").order_by("item_code"))
    grouped = _entries_by_item(ids)
    purchases = last_purchase_rates(ids) if mode == "purchase" else {}
    rows = []
    counts = {"create": 0, "replace": 0, "skip": 0}
    for item in items:
        base = _in_force(grouped.get(item.id, []), on_date)
        row = _item_info(item)
        row.update({
            "current_price": _text(base.price) if base else None,
            "current_date": _iso(base.effective_date) if base else None,
            "new_price": None,
            "change_pct": None,
            "effective_date": on_date.isoformat(),
            "action": "skip",
            "message": "",
        })
        new = None
        if not item.is_active:
            row["message"] = "Item is inactive"
        elif mode == "purchase":
            # Priced from what was last paid, restated in the item's unit, so
            # an item with no price yet can be priced this way too.
            purchase = purchases.get(item.id)
            cost = (purchase_rate_per_price_unit(item, purchase["rate"], purchase["unit"])
                    if purchase else None)
            if purchase is None:
                row["message"] = "No purchase rate to work from"
            elif cost is None or cost <= 0:
                row["message"] = "Bought per %s, priced per %s: units do not match" % (
                    purchase["unit"] or "unit", _unit(item) or "unit")
            else:
                new = _money(cost * (1 + value / 100))
                row["base_rate"] = str(cost)
                row["message"] = "From last purchase %s on %s" % (cost, purchase["date"])
        elif base is None:
            row["message"] = "No price in force on %s to revise" % on_date.strftime("%d.%m.%Y")
        elif mode == "percent":
            new = _money(base.price * (1 + value / 100))
        else:
            new = _money(base.price + value)

        if new is not None:
            if new <= 0:
                row["message"] = "Revised price would be zero or less"
            else:
                row["new_price"] = str(new)
                row["change_pct"] = _pct(new, base.price) if base else None
                if (mode == "purchase" and row["change_pct"] is not None
                        and abs(Decimal(row["change_pct"])) > LARGE_CHANGE_PCT):
                    # A price entered per Kg on an item whose unit is Bag reads
                    # as 50 times too low next to a per-Kg bill, and repricing
                    # from it would multiply it by fifty. Said before saving.
                    row["message"] += ("; a change of over %s%%, check the item's unit"
                                       % LARGE_CHANGE_PCT)
                    row["large_change"] = True
                if base and base.effective_date == on_date:
                    row["action"] = "replace"
                    replaces = "Replaces the price already set for this date"
                    row["message"] = ("%s; %s" % (row["message"], replaces.lower())
                                      if row["message"] else replaces)
                else:
                    row["action"] = "create"
        counts[row["action"]] += 1
        rows.append(row)
    return {"rows": rows, "counts": counts}


# --- upload ------------------------------------------------------------------

_CODE_HEADERS = ("item code", "item_code", "code")
_PRICE_HEADERS = ("new price", "new_price", "price", "rate")
_DATE_HEADERS = ("effective date", "effective_date", "date")


def _read_upload(upload):
    name = (getattr(upload, "name", "") or "").lower()
    if name.endswith(".csv"):
        raw = upload.read()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        table = [row for row in csv.reader(io.StringIO(text))]
    elif name.endswith(".xlsx"):
        import openpyxl
        try:
            workbook = openpyxl.load_workbook(upload, read_only=True, data_only=True)
        except Exception:
            raise PriceRowError("The file could not be read as an Excel workbook.")
        table = [list(row) for row in workbook.active.iter_rows(values_only=True)]
    else:
        raise PriceRowError("Upload an Excel (.xlsx) or CSV (.csv) file.")
    if not table:
        raise PriceRowError("The file is empty.")
    headers = [str(cell or "").strip().lower() for cell in table[0]]
    return headers, table[1:]


def _column(headers, names):
    for name in names:
        if name in headers:
            return headers.index(name)
    return None


def _cell(row, col):
    if col is None or col >= len(row):
        return None
    return row[col]


def _blank(value):
    return value is None or str(value).strip() == ""


def parse_price_upload(upload, default_date=None):
    """Rows of an uploaded price file matched to items by Item Code. Saves
    nothing.

    Rows with a blank New Price are left out: the template lists every item,
    and only the ones filled in are being changed. A row without its own
    Effective Date takes default_date."""
    headers, body = _read_upload(upload)
    code_col = _column(headers, _CODE_HEADERS)
    price_col = _column(headers, _PRICE_HEADERS)
    date_col = _column(headers, _DATE_HEADERS)
    if code_col is None or price_col is None:
        raise PriceRowError("The file needs an Item Code column and a New Price (or Price) column.")
    fallback = parse_date(default_date)

    pending = []
    for row_num, row in enumerate(body, start=2):
        if _blank(_cell(row, price_col)):
            continue
        pending.append((row_num, str(_cell(row, code_col) or "").strip(),
                        _cell(row, price_col), _cell(row, date_col)))
    if not pending:
        raise PriceRowError("No rows with a new price were found in the file.")
    if len(pending) > MAX_ROWS:
        raise PriceRowError("Upload at most %d prices at a time." % MAX_ROWS)

    items = {item.item_code.upper(): item for item in Item.objects.all()}
    grouped = _entries_by_item([item.id for item in items.values()])
    seen = set()
    rows = []
    counts = {"create": 0, "replace": 0, "unchanged": 0, "error": 0}
    for row_num, code, raw_price, raw_date in pending:
        item = items.get(code.upper()) if code else None
        row = {
            "row": row_num, "item_code": code,
            "item": item.id if item else None,
            "item_name": item.description if item else "",
            "current_price": None, "new_price": None, "change_pct": None,
            "effective_date": None, "action": "error", "message": "",
        }
        try:
            price = parse_price(raw_price)
            price_ok = True
        except PriceRowError:
            price, price_ok = None, False
        on_date = fallback if _blank(raw_date) else parse_date(raw_date)

        if not code:
            row["message"] = "Item code is missing"
        elif item is None:
            row["message"] = "No item with code %s" % code
        elif not item.is_active:
            row["message"] = "Item is inactive"
        elif not price_ok:
            row["message"] = "Price is not a number"
        elif price <= 0:
            row["message"] = "Price must be more than zero"
        elif not _blank(raw_date) and on_date is None:
            row["message"] = "Effective date not understood (use YYYY-MM-DD or DD-MM-YYYY)"
        elif on_date is None:
            row["message"] = "No effective date: fill the column or choose a date"
        elif (item.id, on_date) in seen:
            row["message"] = "Same item and date appear earlier in the file"
        else:
            seen.add((item.id, on_date))
            base = _in_force(grouped.get(item.id, []), on_date)
            row.update({
                "current_price": _text(base.price) if base else None,
                "new_price": str(price),
                "change_pct": _pct(price, base.price) if base else None,
                "effective_date": on_date.isoformat(),
            })
            if base and base.effective_date == on_date:
                if base.price == price:
                    row["action"] = "unchanged"
                    row["message"] = "Same as the price already set for this date"
                else:
                    row["action"] = "replace"
                    row["message"] = "Replaces the price already set for this date"
            else:
                row["action"] = "create"
        counts[row["action"]] += 1
        rows.append(row)
    return {"rows": rows, "counts": counts}


# --- saving ------------------------------------------------------------------

def apply_price_rows(rows, *, source, note="", can_replace=True):
    """Save dated prices, all of them or none.

    rows: [{"item": id, "price": "45.15", "effective_date": "YYYY-MM-DD"}].
    A new date adds an entry; a date the item is already priced on replaces
    that price, which needs can_replace (Edit rights)."""
    from inventory.price_audit import price_change

    if not isinstance(rows, list) or not rows:
        raise PriceRowError("There are no prices to save.")
    if len(rows) > MAX_ROWS:
        raise PriceRowError("Save at most %d prices at a time." % MAX_ROWS)

    cleaned = []
    seen = set()
    for index, row in enumerate(rows, start=1):
        row = row if isinstance(row, dict) else {}
        item_id = str(row.get("item") or "").strip()
        if not item_id.isdigit():
            raise PriceRowError("Row %d: item is missing." % index)
        try:
            price = parse_price(row.get("price"))
        except PriceRowError:
            raise PriceRowError("Row %d: price is not a number." % index)
        if price is None or price <= 0:
            raise PriceRowError("Row %d: price must be more than zero." % index)
        on_date = parse_date(row.get("effective_date"))
        if on_date is None:
            raise PriceRowError("Row %d: effective date is missing." % index)
        key = (int(item_id), on_date)
        if key in seen:
            raise PriceRowError("Row %d: the same item and date appear twice." % index)
        seen.add(key)
        cleaned.append((int(item_id), on_date, price))

    item_ids = {item_id for item_id, _, _ in cleaned}
    found = set(Item.objects.filter(id__in=item_ids).values_list("id", flat=True))
    if item_ids - found:
        raise PriceRowError("One or more items no longer exist. Preview again.")

    existing = {
        (entry.item_id, entry.effective_date): entry
        for entry in ItemPriceList.objects.filter(
            item_id__in=item_ids, effective_date__in={d for _, d, _ in cleaned})
    }
    replacing = [(i, d, p) for i, d, p in cleaned
                 if (i, d) in existing and existing[(i, d)].price != p]
    if replacing and not can_replace:
        raise PriceRowError(
            "%d item%s already priced on that date. Changing an existing price "
            "needs Edit rights on the Item Price List."
            % (len(replacing), " is" if len(replacing) == 1 else "s are"))

    created = updated = unchanged = 0
    with transaction.atomic(), price_change(source, note):
        for item_id, on_date, price in cleaned:
            entry = existing.get((item_id, on_date))
            if entry is None:
                ItemPriceList.objects.create(item_id=item_id, price=price, effective_date=on_date)
                created += 1
            elif entry.price != price:
                entry.price = price
                entry.save(update_fields=["price"])
                updated += 1
            else:
                unchanged += 1
    return {"created": created, "updated": updated, "unchanged": unchanged}


def price_template_workbook(today=None):
    """An .xlsx of every item with its current price and an empty New Price
    column, to fill in and upload."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Prices"
    headers = ["Item Code", "Item Name", "Category", "Unit", "Current Price",
               "Current Since", "New Price", "Effective Date"]
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for col in ("G", "H"):
        sheet["%s1" % col].fill = PatternFill("solid", fgColor="FFF4CC")

    for row in price_overview(today=today):
        if not row["is_active"]:
            continue
        active = row["status"] == STATUS_ACTIVE
        sheet.append([
            row["item_code"], row["item_name"], row["category"], row["unit"],
            float(row["price"]) if active else None,
            row["effective_date"] if active else None,
            None, None,
        ])
    for col, width in zip("ABCDEFGH", (14, 36, 18, 8, 14, 14, 12, 15)):
        sheet.column_dimensions[col].width = width
    sheet.freeze_panes = "A2"

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
