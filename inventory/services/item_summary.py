"""Item Summary engine — per storage location, per item stock and value.

Unlike the warehouse-only Stock Report, this covers **every** storage location
(Warehouse *and* Broiler Farm) and carries valuation through, so each row shows
Opening / IN / OUT / Closing as Quantity, Price and Amount.

Movements collected (each normalised to location + item + date + qty + cost):

  IN   general purchase received, transfer in, stock received, 'Add'
       adjustment, medicine/vaccine transfer in
  OUT  transfer out, stock issued, 'Deduct' adjustment, medicine/vaccine
       transfer out, and at farms the daily-entry feed consumption and
       medicine/vaccine consumption

Price is the perpetual weighted average at that location: inflows carry their
own unit cost, outflows leave at the running average. Quantities are never
clamped, so a location whose out-movements exceed its in-movements shows a
negative balance rather than silently absorbing the discrepancy.
"""

from decimal import Decimal

Z = Decimal("0")


def _d(v):
    return Decimal(str(v)) if v is not None else Z


def _collect(from_date=None, to_date=None, category_id=None, item_id=None,
             location_type=None, location_id=None, farm_consumption=True):
    """All stock movements as dicts, newest-last. ``to_date`` caps the replay;
    ``from_date`` is *not* applied here because everything before it forms the
    opening balance.

    ``farm_consumption=False`` leaves out the farm's own daily-entry feed and
    medicine issues. The daily-entry grid chains those itself, row by row, and
    needs the balance they are drawn *from* — counting them here as well would
    subtract every one of them twice.
    """
    from purchase.models import ChicksPurchaseItem, GeneralPurchaseItem
    from inventory.models import (StockTransfer, StockReceiveItem, StockIssueItem,
                                  InventoryAdjustmentItem, MedicineTransferItem)
    from broiler.models import DailyEntry, MedicineVaccineEntry
    from hatchery.models import ChickSaleItem, EggPurchaseItem

    moves = []

    def add(date, loc_type, loc_id, item_pk, direction, qty, cost=None, order=0):
        qty = _d(qty)
        if not date or not loc_id or not item_pk or qty <= 0:
            return
        if to_date and date > to_date:
            return
        if location_type and (loc_type != location_type or str(loc_id) != str(location_id)):
            return
        moves.append({"date": date, "loc": (loc_type, loc_id), "item": item_pk,
                      "dir": direction, "qty": qty, "cost": _d(cost), "order": order})

    def scope(qs, field="item_id"):
        if item_id:
            qs = qs.filter(**{field: item_id})
        if category_id:
            qs = qs.filter(**{field.replace("_id", "") + "__category_id": category_id})
        return qs

    # ---------------- inflows ----------------
    for r in scope(GeneralPurchaseItem.objects.exclude(farm_warehouse=None)).select_related("purchase"):
        # Billed on Sent or Received quantity per the header's basis; reading
        # rcv_qty alone loses every purchase entered on the Sent basis.
        qty = _d(r.effective_qty()) + _d(r.free_qty)
        cost = (_d(r.amount) / qty) if (qty > 0 and r.amount) else _d(r.rate)
        add(r.purchase.date, "warehouse", r.farm_warehouse_id, r.item_id, "in", qty, cost, 0)

    for r in scope(StockTransfer.objects.all()):
        to_id = r.to_farm_id if r.to_location_type == "farm" else r.to_warehouse_id
        add(r.date, r.to_location_type, to_id, r.item_id, "in", r.quantity, r.rate, 1)
        from_id = r.from_farm_id if r.from_location_type == "farm" else r.from_warehouse_id
        add(r.date, r.from_location_type, from_id, r.item_id, "out", r.quantity, None, 5)

    for r in scope(StockReceiveItem.objects.all()).select_related("receive"):
        loc_id = r.farm_id if r.location_type == "farm" else r.warehouse_id
        add(r.receive.date, r.location_type, loc_id, r.item_id, "in", r.quantity, r.rate, 2)

    for r in scope(InventoryAdjustmentItem.objects.all()).select_related("adjustment"):
        adj = r.adjustment
        loc_id = adj.farm_id if adj.location_type == "farm" else adj.warehouse_id
        direction = "in" if r.adjustment_type == "Add" else "out"
        add(adj.date, adj.location_type, loc_id, r.item_id, direction, r.quantity,
            r.rate if direction == "in" else None, 3 if direction == "in" else 6)

    for r in scope(MedicineTransferItem.objects.all()).select_related("transfer"):
        t = r.transfer
        to_id = t.to_farm_id if t.to_location_type == "farm" else t.to_warehouse_id
        add(t.date, t.to_location_type, to_id, r.item_id, "in", r.quantity, r.rate, 4)
        from_id = t.from_farm_id if t.from_location_type == "farm" else t.from_warehouse_id
        add(t.date, t.from_location_type, from_id, r.item_id, "out", r.quantity, None, 7)

    # Chicks Purchase: item lives on the header. total_qty is what physically
    # arrived (Received + Free); received_qty alone would drop the free chicks.
    for r in scope(ChicksPurchaseItem.objects.exclude(farm_warehouse=None),
                   "purchase__item_id").select_related("purchase"):
        qty = _d(r.total_qty)
        cost = (_d(r.amount) / qty) if (qty > 0 and r.amount) else _d(r.rate)
        add(r.purchase.date, "warehouse", r.farm_warehouse_id, r.purchase.item_id,
            "in", qty, cost, 0)

    # Egg Purchase (hatchery): received qty falls back to sent, plus free eggs.
    for r in scope(EggPurchaseItem.objects.exclude(egg_purchase__warehouse=None)
                   ).select_related("egg_purchase"):
        qty = _d(r.rcv_qty) or _d(r.sent_qty)
        qty += _d(r.free_qty)
        cost = (_d(r.amount) / qty) if (qty > 0 and r.amount) else _d(r.rate)
        add(r.egg_purchase.date, "warehouse", r.egg_purchase.warehouse_id, r.item_id,
            "in", qty, cost, 0)

    # ---------------- outflows ----------------
    for r in scope(StockIssueItem.objects.all()).select_related("issue"):
        loc_id = r.farm_id if r.location_type == "farm" else r.warehouse_id
        add(r.issue.date, r.location_type, loc_id, r.item_id, "out", r.quantity, None, 8)

    # Farm consumption: feed fed on a daily entry, and medicine/vaccine issued.
    if not farm_consumption:
        moves.sort(key=lambda m: (m["date"], m["order"]))
        return moves

    daily = DailyEntry.objects.all()
    for r in daily:
        for item_pk, qty in ((r.feed_1_id, r.feed_1_qty), (r.feed_2_id, r.feed_2_qty)):
            if not item_pk:
                continue
            if item_id and str(item_pk) != str(item_id):
                continue
            add(r.date, "farm", r.farm_id, item_pk, "out", qty, None, 9)

    for r in scope(MedicineVaccineEntry.objects.all()):
        add(r.date, "farm", r.farm_id, r.item_id, "out", r.qty, None, 10)

    # Chick Sale (hatchery): total_qty left the stock point - sale_qty omits
    # mortality and culls, which physically left as well.
    for r in scope(ChickSaleItem.objects.exclude(sale__warehouse=None)
                   ).select_related("sale"):
        add(r.sale.date, "warehouse", r.sale.warehouse_id, r.item_id,
            "out", r.total_qty, None, 11)

    moves.sort(key=lambda m: (m["date"], m["order"]))
    return moves


def item_summary(from_date=None, to_date=None, category_id=None, item_id=None,
                 location_type=None, location_id=None, allowed_locations=None):
    """Rows of {location, item, opening/in/out/closing x (qty, price, amount)},
    grouped by storage location. Category filtering is applied after collection
    for the daily-entry feed lines, which carry no category join.

    ``allowed_locations`` is ``{"warehouse": ids, "farm": ids}`` limiting which
    storage locations may appear, for a caller enforcing data scoping. A value
    of ``None`` for either kind means no limit on it — distinct from an empty
    set, which is a real limit that permits nothing. Locations are dropped
    before grouping, so each group's subtotals cover only what is shown.
    """
    from inventory.models import Item, Warehouse
    from broiler.models import BroilerFarm

    moves = _collect(from_date, to_date, category_id, item_id, location_type, location_id)

    # Replay per (location, item), carrying a perpetual weighted average.
    books = {}
    for m in moves:
        key = (m["loc"], m["item"])
        b = books.setdefault(key, {
            "qty": Z, "value": Z, "avg": Z,
            "open_qty": Z, "open_price": Z, "open_amount": Z,
            "in_qty": Z, "in_amount": Z, "out_qty": Z, "out_amount": Z,
        })
        if m["dir"] == "in":
            price = m["cost"]
            amount = m["qty"] * price
            b["qty"] += m["qty"]
            b["value"] += amount
        else:
            price = (b["value"] / b["qty"]) if b["qty"] > 0 else b["avg"]
            amount = m["qty"] * price
            b["qty"] -= m["qty"]
            b["value"] -= amount
        if b["qty"] > 0:
            b["avg"] = b["value"] / b["qty"]
        elif m["dir"] == "in":
            b["avg"] = m["cost"]

        if from_date and m["date"] < from_date:
            b["open_qty"], b["open_price"], b["open_amount"] = b["qty"], b["avg"], b["value"]
            continue
        if m["dir"] == "in":
            b["in_qty"] += m["qty"]
            b["in_amount"] += amount
        else:
            b["out_qty"] += m["qty"]
            b["out_amount"] += amount

    if not books:
        return []

    item_ids = {k[1] for k in books}
    items = {i.id: i for i in Item.objects.filter(id__in=item_ids).select_related("category")}
    wh_ids = {k[0][1] for k in books if k[0][0] == "warehouse"}
    farm_ids = {k[0][1] for k in books if k[0][0] == "farm"}
    names = {("warehouse", w.id): w.name for w in Warehouse.objects.filter(id__in=wh_ids)}
    names.update({("farm", f.id): f.farm_name for f in BroilerFarm.objects.filter(id__in=farm_ids)})

    def price(amount, qty):
        return (amount / qty) if qty else Z

    rows = []
    for (loc, item_pk), b in books.items():
        it = items.get(item_pk)
        if not it:
            continue
        # Category filter for sources that could not be joined during collection.
        if category_id and str(it.category_id) != str(category_id):
            continue
        if allowed_locations is not None:
            permitted = allowed_locations.get(loc[0])
            if permitted is not None and loc[1] not in permitted:
                continue
        rows.append({
            "location": names.get(loc, ""),
            "location_type": loc[0], "location_id": loc[1],
            "category": it.category.name if it.category_id else "",
            "item": it.description, "item_id": it.id,
            "open_qty": b["open_qty"], "open_price": b["open_price"], "open_amount": b["open_amount"],
            "in_qty": b["in_qty"], "in_price": price(b["in_amount"], b["in_qty"]),
            "in_amount": b["in_amount"],
            "out_qty": b["out_qty"], "out_price": price(b["out_amount"], b["out_qty"]),
            "out_amount": b["out_amount"],
            "close_qty": b["qty"], "close_price": b["avg"], "close_amount": b["value"],
        })

    rows.sort(key=lambda r: (r["location"], r["item"]))

    # Group into locations, each with its own subtotal row.
    groups = []
    for r in rows:
        if not groups or groups[-1]["location"] != r["location"]:
            groups.append({"location": r["location"], "rows": [], "total": {
                k: Z for k in ("open_qty", "open_amount", "in_qty", "in_amount",
                               "out_qty", "out_amount", "close_qty", "close_amount")}})
        g = groups[-1]
        g["rows"].append(r)
        for k in g["total"]:
            g["total"][k] += r[k]

    for g in groups:
        t = g["total"]
        t["open_price"] = price(t["open_amount"], t["open_qty"])
        t["in_price"] = price(t["in_amount"], t["in_qty"])
        t["out_price"] = price(t["out_amount"], t["out_qty"])
        t["close_price"] = price(t["close_amount"], t["close_qty"])
    return groups


def negative_stock(as_of_date=None, item_id=None, location_type=None, location_id=None):
    """Locations/items whose running stock balance is negative as of a date.

    A negative balance means out-movements (issues, transfers out, deduct
    adjustments, farm consumption) exceed the in-movements recorded at that
    location — i.e. stock left a place it was never booked into. Each row also
    carries the date the balance *first* went negative, which is where the
    correction usually belongs.
    """
    from inventory.models import Item, Warehouse
    from broiler.models import BroilerFarm

    moves = _collect(None, as_of_date, None, item_id, location_type, location_id)

    balance = {}
    since = {}
    for m in moves:
        key = (m["loc"], m["item"])
        bal = balance.get(key, Z)
        bal = bal + m["qty"] if m["dir"] == "in" else bal - m["qty"]
        balance[key] = bal
        if bal < 0:
            since.setdefault(key, m["date"])
        else:
            since.pop(key, None)          # recovered — forget the old breach

    negatives = {k: v for k, v in balance.items() if v < 0}
    if not negatives:
        return []

    items = {i.id: i for i in Item.objects.filter(id__in={k[1] for k in negatives})
             .select_related("category")}
    names = {("warehouse", w.id): w.name for w in Warehouse.objects.filter(
        id__in={k[0][1] for k in negatives if k[0][0] == "warehouse"})}
    names.update({("farm", f.id): f.farm_name for f in BroilerFarm.objects.filter(
        id__in={k[0][1] for k in negatives if k[0][0] == "farm"})})

    rows = []
    for (loc, item_pk), qty in negatives.items():
        it = items.get(item_pk)
        if not it:
            continue
        rows.append({
            "location": names.get(loc, ""),
            "location_type": loc[0], "location_id": loc[1],
            "category": it.category.name if it.category_id else "",
            "item": it.description, "item_id": it.id,
            "quantity": qty,
            "since": since.get((loc, item_pk)),
        })
    rows.sort(key=lambda r: (r["location"], r["item"]))
    return rows

def location_item_stock(location_type, location_id, item_id, as_of_date=None):
    """Running stock balance of one item at one location as of a date.

    Warehouses have inventory.models.warehouse_item_stock for this; farms do
    not, so this replays the same normalised movement set used by the reports —
    including the farm-only outflows (daily-entry feed and medicine/vaccine
    consumption).
    """
    balance = Z
    for m in _collect(None, as_of_date, None, item_id, location_type, location_id):
        balance = balance + m["qty"] if m["dir"] == "in" else balance - m["qty"]
    return balance


def farm_receipts_balance(farm_id, item_id, as_of_date=None):
    """What has been delivered to a farm, net of everything except its own
    consumption entries.

    The opening balance a daily entry's stock column should start from. It used
    to start from zero, so a farm with 2,337 kg of Starter Feed delivered
    showed 0, and the column drifted further negative with every day fed —
    reporting consumption against receipts it could not see.

    Consumption is left out because the caller subtracts it row by row: the
    grid is a chain, and each row's opening is the one before it closing.
    """
    balance = Z
    for m in _collect(None, as_of_date, None, item_id, "farm", farm_id,
                      farm_consumption=False):
        balance = balance + m["qty"] if m["dir"] == "in" else balance - m["qty"]
    return balance
