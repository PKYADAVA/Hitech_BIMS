"""Stock issue valuation engine.

Computes the *cost* at which a unit leaves a warehouse when it is issued,
honouring the Item's ``valuation_method``. This is what makes management /
COGS reporting reflect real inventory cost instead of a hand-typed rate.

Supported methods:
  - Standard Costing  -> the item's ``standard_cost_per_unit``.
  - Weighted Average  -> perpetual moving average of the item at that
                         warehouse, replayed in date order up to the issue
                         date (issues leave at the running average).
  - FIFO / LIFO       -> cost of the units taken from the oldest / newest
                         remaining purchase-cost layers.
  - FEFO              -> no per-layer expiry is tracked, so it falls back to
                         FIFO (earliest-in first).

All figures are reconciled across every cost-bearing warehouse movement:
general purchases received here, stock received, stock transferred in, and
"Add" inventory adjustments (inflows, each carrying a unit cost); stock
transferred out, stock issued, and "Deduct" adjustments (outflows).

The current issue being (re)saved is excluded via ``exclude_issue_id`` so an
item is valued at the state *before* this issue; ``prior_consumed`` lets a
multi-line submission draw down FIFO/LIFO layers cumulatively within itself.
"""

from decimal import Decimal

Z = Decimal("0")


def _q(v):
    return v if v is not None else Z


def _dcap(qs, field, as_of_date):
    return qs.filter(**{f"{field}__lte": as_of_date}) if as_of_date else qs


def warehouse_inflow_layers(item_id, warehouse_id, as_of_date=None):
    """Cost-bearing inflows of ``item`` at ``warehouse`` as (date, seq, qty,
    unit_cost) tuples, oldest first. ``seq`` breaks ties on the same date so
    ordering is deterministic across runs."""
    from purchase.models import ChicksPurchaseItem, GeneralPurchaseItem
    from inventory.models import (StockReceiveItem, StockTransfer,
                                  InventoryAdjustmentItem, MedicineTransferItem)
    from hatchery.models import EggPurchaseItem
    layers = []

    for r in _dcap(GeneralPurchaseItem.objects.filter(
            item_id=item_id, farm_warehouse_id=warehouse_id
    ).select_related("purchase"), "purchase__date", as_of_date):
        qty = _q(r.rcv_qty) + _q(r.free_qty)
        if qty <= 0:
            continue
        # Landed unit cost = net line amount spread over received + free qty;
        # fall back to the bare rate if the amount wasn't computed.
        unit_cost = (_q(r.amount) / qty) if r.amount else _q(r.rate)
        layers.append((r.purchase.date, ("a", r.id), qty, unit_cost))

    for r in _dcap(StockReceiveItem.objects.filter(
            item_id=item_id, location_type="warehouse", warehouse_id=warehouse_id
    ).select_related("receive"), "receive__date", as_of_date):
        qty = _q(r.quantity)
        if qty <= 0:
            continue
        layers.append((r.receive.date, ("b", r.id), qty, _q(r.rate)))

    for r in _dcap(StockTransfer.objects.filter(
            item_id=item_id, to_location_type="warehouse", to_warehouse_id=warehouse_id
    ), "date", as_of_date):
        qty = _q(r.quantity)
        if qty <= 0:
            continue
        # Transferred-in stock carries the rate recorded on the transfer.
        layers.append((r.date, ("c", r.id), qty, _q(r.rate)))

    for r in _dcap(InventoryAdjustmentItem.objects.filter(
            item_id=item_id, adjustment_type="Add",
            adjustment__location_type="warehouse", adjustment__warehouse_id=warehouse_id
    ).select_related("adjustment"), "adjustment__date", as_of_date):
        qty = _q(r.quantity)
        if qty <= 0:
            continue
        layers.append((r.adjustment.date, ("d", r.id), qty, _q(r.rate)))

    for r in _dcap(MedicineTransferItem.objects.filter(
            item_id=item_id, transfer__to_location_type="warehouse",
            transfer__to_warehouse_id=warehouse_id
    ).select_related("transfer"), "transfer__date", as_of_date):
        qty = _q(r.quantity)
        if qty <= 0:
            continue
        layers.append((r.transfer.date, ("e", r.id), qty, _q(r.rate)))

    # Chicks Purchase - the item is on the header, and rcv_qty already includes
    # the free chicks, so free_qty must not be added on top.
    for r in _dcap(ChicksPurchaseItem.objects.filter(
            purchase__item_id=item_id, farm_warehouse_id=warehouse_id
    ).select_related("purchase"), "purchase__date", as_of_date):
        qty = _q(r.rcv_qty)
        if qty <= 0:
            continue
        unit_cost = (_q(r.amount) / qty) if r.amount else _q(r.rate)
        layers.append((r.purchase.date, ("f", r.id), qty, unit_cost))

    # Egg Purchase (hatchery) - received qty falls back to sent when nothing was
    # booked as received, plus free eggs.
    for r in _dcap(EggPurchaseItem.objects.filter(
            item_id=item_id, egg_purchase__warehouse_id=warehouse_id
    ).select_related("egg_purchase"), "egg_purchase__date", as_of_date):
        qty = (_q(r.rcv_qty) or _q(r.sent_qty)) + _q(r.free_qty)
        if qty <= 0:
            continue
        unit_cost = (_q(r.total_amount) / qty) if r.total_amount else _q(r.rate)
        layers.append((r.egg_purchase.date, ("g", r.id), qty, unit_cost))

    layers.sort(key=lambda x: (x[0], x[1]))
    return layers


def warehouse_outflow_events(item_id, warehouse_id, as_of_date=None, exclude_issue_id=None):
    """Outflows of ``item`` at ``warehouse`` as (date, seq, qty) tuples,
    oldest first. Value is not needed — outflows leave at the method's cost."""
    from inventory.models import (StockTransfer, StockIssueItem,
                                  InventoryAdjustmentItem, MedicineTransferItem)
    from hatchery.models import ChickSaleItem
    events = []

    for r in _dcap(StockTransfer.objects.filter(
            item_id=item_id, from_location_type="warehouse", from_warehouse_id=warehouse_id
    ), "date", as_of_date):
        events.append((r.date, ("c", r.id), _q(r.quantity)))

    issued = _dcap(StockIssueItem.objects.filter(
        item_id=item_id, location_type="warehouse", warehouse_id=warehouse_id
    ).select_related("issue"), "issue__date", as_of_date)
    if exclude_issue_id:
        issued = issued.exclude(issue_id=exclude_issue_id)
    for r in issued:
        events.append((r.issue.date, ("x", r.id), _q(r.quantity)))

    for r in _dcap(InventoryAdjustmentItem.objects.filter(
            item_id=item_id, adjustment_type="Deduct",
            adjustment__location_type="warehouse", adjustment__warehouse_id=warehouse_id
    ).select_related("adjustment"), "adjustment__date", as_of_date):
        events.append((r.adjustment.date, ("d", r.id), _q(r.quantity)))

    for r in _dcap(MedicineTransferItem.objects.filter(
            item_id=item_id, transfer__from_location_type="warehouse",
            transfer__from_warehouse_id=warehouse_id
    ).select_related("transfer"), "transfer__date", as_of_date):
        events.append((r.transfer.date, ("e", r.id), _q(r.quantity)))

    # Chick Sale (hatchery) - total_qty left the stock point, mortality and
    # culls included.
    for r in _dcap(ChickSaleItem.objects.filter(
            item_id=item_id, sale__warehouse_id=warehouse_id
    ).select_related("sale"), "sale__date", as_of_date):
        events.append((r.sale.date, ("h", r.id), _q(r.total_qty)))

    events.sort(key=lambda x: (x[0], x[1]))
    return events


def weighted_average_rate(item_id, warehouse_id, as_of_date=None, exclude_issue_id=None):
    """Perpetual moving-average cost of ``item`` at ``warehouse`` as of the
    date. Returns Decimal 0 when nothing is on hand and there is no history."""
    inflows = warehouse_inflow_layers(item_id, warehouse_id, as_of_date)
    outflows = warehouse_outflow_events(item_id, warehouse_id, as_of_date, exclude_issue_id)

    # Merge, taking inflows before outflows on the same date so same-day
    # receipts are available to same-day issues.
    moves = [(d, 0, seq, qty, uc) for (d, seq, qty, uc) in inflows]
    moves += [(d, 1, seq, qty, None) for (d, seq, qty) in outflows]
    moves.sort(key=lambda x: (x[0], x[1], x[2]))

    qoh = Z
    value = Z
    last_avg = Z
    for _d, typ, _seq, qty, uc in moves:
        if typ == 0:  # inflow
            qoh += qty
            value += qty * uc
            if qoh > 0:
                last_avg = value / qoh
        else:  # outflow
            if qoh > 0:
                last_avg = value / qoh
                value -= qty * last_avg
                qoh -= qty
                if qoh <= 0:
                    qoh = Z
                    value = Z
    if qoh > 0:
        return value / qoh
    return last_avg


def fifo_lifo_rate(item_id, warehouse_id, quantity, newest_first,
                   as_of_date=None, exclude_issue_id=None, prior_consumed=Z):
    """Unit cost of ``quantity`` units taken from the oldest (FIFO) or newest
    (LIFO) remaining cost layers, after prior outflows have drawn down layers
    in the same order. Returns None when there are no layers at all."""
    inflows = warehouse_inflow_layers(item_id, warehouse_id, as_of_date)
    if not inflows:
        return None
    layers = [[qty, uc] for (_d, _seq, qty, uc) in inflows]  # oldest -> newest
    if newest_first:
        layers.reverse()  # newest -> oldest

    # Draw down what prior outflows (+ earlier lines in this submission) already
    # consumed, from the front of the ordering.
    already = sum((qty for (_d, _seq, qty) in
                   warehouse_outflow_events(item_id, warehouse_id, as_of_date, exclude_issue_id)), Z)
    already += prior_consumed
    idx = 0
    while already > 0 and idx < len(layers):
        take = min(already, layers[idx][0])
        layers[idx][0] -= take
        already -= take
        if layers[idx][0] <= 0:
            idx += 1
    layers = [l for l in layers[idx:] if l[0] > 0]

    need = Decimal(str(quantity or 0))
    cost = Z
    taken = Z
    for qty, uc in layers:
        if need <= 0:
            break
        t = min(need, qty)
        cost += t * uc
        taken += t
        need -= t
    if taken <= 0:
        # Everything is already consumed — value the shortfall at the last
        # known layer cost so the issue still gets a sensible rate.
        return layers[-1][1] if layers else (inflows[-1][3] if inflows else None)
    if need > 0:
        # Issuing more than is layered: extend at the last layer's cost.
        cost += need * (layers[-1][1] if layers else Z)
        taken += need
    return cost / taken


def _loc_name(location_type, warehouse, farm):
    obj = farm if location_type == "farm" else warehouse
    return (getattr(obj, "farm_name", None) or getattr(obj, "name", None) or "") if obj else ""


def item_ledger(item_id, warehouse_id, from_date=None, to_date=None):
    """Full item ledger at a warehouse — opening balance, one row per dated
    movement inside [from_date, to_date], and a closing balance — with a
    *perpetual weighted-average* price and value carried through every move.

    Each movement is either IN (purchase received here, transfer in, stock
    received, 'Add' adjustment) or OUT (transfer out, stock issued, 'Deduct'
    adjustment). Returns a dict: ``opening``/``closing`` ({qty, price, amount}),
    ``rows`` (the window movements) and ``totals`` (window in/out sums).
    """
    from purchase.models import ChicksPurchaseItem, GeneralPurchaseItem
    from inventory.models import (StockReceiveItem, StockTransfer, StockIssueItem,
                                  InventoryAdjustmentItem, MedicineTransferItem)
    from hatchery.models import ChickSaleItem, EggPurchaseItem

    moves = []

    def add(date, direction, order, qty, cost, type_label, slug, trnum, location, remarks):
        qty = _q(qty)
        if not date or qty <= 0:
            return
        moves.append({
            "date": date, "direction": direction, "order": order,
            "qty": qty, "cost": _q(cost), "type": type_label, "slug": slug,
            "trnum": trnum or "", "location": location or "", "remarks": remarks or "",
        })

    # ---- inflows ----
    for r in (GeneralPurchaseItem.objects.filter(item_id=item_id, farm_warehouse_id=warehouse_id)
              .select_related("purchase", "farm_warehouse")):
        qty = _q(r.rcv_qty) + _q(r.free_qty)
        cost = (_q(r.amount) / qty) if (qty > 0 and r.amount) else _q(r.rate)
        add(r.purchase.date, "in", (0, 0, r.id), qty, cost, "Purchase-RcvQty", "purchase",
            r.purchase.purchase_no, r.farm_warehouse.name if r.farm_warehouse_id else "",
            getattr(r.purchase, "remarks", "") or "")

    for r in (StockTransfer.objects.filter(item_id=item_id, to_location_type="warehouse", to_warehouse_id=warehouse_id)
              .select_related("from_warehouse", "from_farm")):
        add(r.date, "in", (0, 1, r.id), r.quantity, r.rate, "Transfer-In", "transfer-in",
            r.trnum, _loc_name(r.from_location_type, r.from_warehouse, r.from_farm), r.remarks)

    for r in (StockReceiveItem.objects.filter(item_id=item_id, location_type="warehouse", warehouse_id=warehouse_id)
              .select_related("receive", "warehouse")):
        add(r.receive.date, "in", (0, 2, r.id), r.quantity, r.rate, "Stock Received", "receive",
            r.receive.trnum, r.warehouse.name if r.warehouse_id else "", r.remarks)

    for r in (InventoryAdjustmentItem.objects.filter(item_id=item_id, adjustment_type="Add",
              adjustment__location_type="warehouse", adjustment__warehouse_id=warehouse_id)
              .select_related("adjustment", "adjustment__warehouse")):
        add(r.adjustment.date, "in", (0, 3, r.id), r.quantity, r.rate, "Adjustment +", "adjust-add",
            r.adjustment.trnum, r.adjustment.warehouse.name if r.adjustment.warehouse_id else "", r.remarks)

    for r in (MedicineTransferItem.objects.filter(
            item_id=item_id, transfer__to_location_type="warehouse",
            transfer__to_warehouse_id=warehouse_id).select_related("transfer")):
        t = r.transfer
        add(t.date, "in", (0, 4, r.id), r.quantity, r.rate, "Medicine-In", "medicine-in",
            t.trnum, _loc_name(t.from_location_type, t.from_warehouse, t.from_farm), r.remarks)

    for r in (ChicksPurchaseItem.objects.filter(
            purchase__item_id=item_id, farm_warehouse_id=warehouse_id)
            .select_related("purchase", "farm_warehouse")):
        qty = _q(r.rcv_qty)
        cost = (_q(r.amount) / qty) if (qty > 0 and r.amount) else _q(r.rate)
        add(r.purchase.date, "in", (0, 5, r.id), qty, cost, "Chicks Purchase", "purchase",
            r.purchase.purchase_no,
            r.farm_warehouse.name if r.farm_warehouse_id else "",
            getattr(r.purchase, "remarks", "") or "")

    for r in (EggPurchaseItem.objects.filter(
            item_id=item_id, egg_purchase__warehouse_id=warehouse_id)
            .select_related("egg_purchase", "egg_purchase__warehouse")):
        qty = (_q(r.rcv_qty) or _q(r.sent_qty)) + _q(r.free_qty)
        cost = (_q(r.total_amount) / qty) if (qty > 0 and r.total_amount) else _q(r.rate)
        add(r.egg_purchase.date, "in", (0, 6, r.id), qty, cost, "Egg Purchase", "purchase",
            r.egg_purchase.transaction_no,
            r.egg_purchase.warehouse.name if r.egg_purchase.warehouse_id else "",
            getattr(r.egg_purchase, "remarks", "") or "")

    # ---- outflows ----
    for r in (StockTransfer.objects.filter(item_id=item_id, from_location_type="warehouse", from_warehouse_id=warehouse_id)
              .select_related("to_warehouse", "to_farm")):
        add(r.date, "out", (1, 0, r.id), r.quantity, None, "Transfer-Out", "transfer-out",
            r.trnum, _loc_name(r.to_location_type, r.to_warehouse, r.to_farm), r.remarks)

    for r in (StockIssueItem.objects.filter(item_id=item_id, location_type="warehouse", warehouse_id=warehouse_id)
              .select_related("issue", "warehouse")):
        add(r.issue.date, "out", (1, 1, r.id), r.quantity, None, "Stock Issued", "issue",
            r.issue.trnum, r.warehouse.name if r.warehouse_id else "", r.remarks)

    for r in (InventoryAdjustmentItem.objects.filter(item_id=item_id, adjustment_type="Deduct",
              adjustment__location_type="warehouse", adjustment__warehouse_id=warehouse_id)
              .select_related("adjustment", "adjustment__warehouse")):
        add(r.adjustment.date, "out", (1, 2, r.id), r.quantity, None, "Adjustment -", "adjust-deduct",
            r.adjustment.trnum, r.adjustment.warehouse.name if r.adjustment.warehouse_id else "", r.remarks)

    for r in (ChickSaleItem.objects.filter(
            item_id=item_id, sale__warehouse_id=warehouse_id)
            .select_related("sale", "sale__warehouse")):
        add(r.sale.date, "out", (1, 4, r.id), r.total_qty, None, "Chick Sale", "chick-sale",
            r.sale.bill_no,
            r.sale.warehouse.name if r.sale.warehouse_id else "",
            getattr(r.sale, "remarks", "") or "")

    for r in (MedicineTransferItem.objects.filter(
            item_id=item_id, transfer__from_location_type="warehouse",
            transfer__from_warehouse_id=warehouse_id).select_related("transfer")):
        t = r.transfer
        add(t.date, "out", (1, 3, r.id), r.quantity, None, "Medicine-Out", "medicine-out",
            t.trnum, _loc_name(t.to_location_type, t.to_warehouse, t.to_farm), r.remarks)

    moves.sort(key=lambda m: (m["date"], m["order"]))

    qoh = Z
    value = Z
    avg = Z
    opening = {"qty": Z, "price": Z, "amount": Z}
    rows = []
    tot = {"in_qty": Z, "in_amount": Z, "out_qty": Z, "out_amount": Z}

    for m in moves:
        if to_date and m["date"] > to_date:
            break  # sorted — everything after is out of window too

        # Quantities and values are never clamped: a ledger must always satisfy
        # Opening + IN - OUT = Closing. Stock that goes negative means the data
        # has an out-movement with no matching in-movement, and the report has
        # to show that rather than silently absorb it.
        if m["direction"] == "in":
            line_price = m["cost"]
            line_amt = m["qty"] * line_price
            qoh += m["qty"]
            value += line_amt
        else:
            line_price = (value / qoh) if qoh > 0 else avg
            line_amt = m["qty"] * line_price
            qoh -= m["qty"]
            value -= line_amt
        if qoh > 0:
            avg = value / qoh
        elif m["direction"] == "in":
            # Nothing on hand to average against — the latest inward cost is the
            # best available unit price for the rows that follow.
            avg = m["cost"]

        if from_date and m["date"] < from_date:
            opening = {"qty": qoh, "price": avg, "amount": value}
            continue

        row = {
            "date": m["date"], "type": m["type"], "slug": m["slug"], "trnum": m["trnum"],
            "location": m["location"], "remarks": m["remarks"],
            "in_qty": None, "in_price": None, "in_amount": None,
            "out_qty": None, "out_price": None, "out_amount": None,
            "close_qty": qoh, "close_price": avg, "close_amount": value,
        }
        if m["direction"] == "in":
            row["in_qty"], row["in_price"], row["in_amount"] = m["qty"], line_price, line_amt
            tot["in_qty"] += m["qty"]
            tot["in_amount"] += line_amt
        else:
            row["out_qty"], row["out_price"], row["out_amount"] = m["qty"], line_price, line_amt
            tot["out_qty"] += m["qty"]
            tot["out_amount"] += line_amt
        rows.append(row)

    closing = {"qty": qoh, "price": avg, "amount": value}
    return {"opening": opening, "rows": rows, "closing": closing, "totals": tot}


def compute_issue_rate(item, warehouse_id, as_of_date, quantity,
                       exclude_issue_id=None, prior_consumed=Z):
    """The authoritative unit cost at which ``quantity`` of ``item`` is issued
    from ``warehouse_id`` on ``as_of_date``, per the item's valuation method.

    ``warehouse_id`` may be None (e.g. a farm-location issue), in which case
    there is no warehouse cost pool and the standard cost is used.
    """
    method = (item.valuation_method or "").strip()
    std = Decimal(str(item.standard_cost_per_unit or 0))

    if method == "Standard Costing" or not warehouse_id:
        return std

    if method == "Weighted Average":
        rate = weighted_average_rate(item.id, warehouse_id, as_of_date, exclude_issue_id)
        return rate if rate and rate > 0 else std

    if method in ("FIFO", "LIFO", "FEFO"):
        rate = fifo_lifo_rate(item.id, warehouse_id, quantity,
                              newest_first=(method == "LIFO"),
                              as_of_date=as_of_date, exclude_issue_id=exclude_issue_id,
                              prior_consumed=prior_consumed)
        return rate if rate and rate > 0 else std

    return std


def _sum_by_item(qs, value_fields, date_field, from_date=None, to_date=None):
    """{item_id: total} for ``qs``, summing ``value_fields`` and honouring an
    optional [from_date, to_date] window on ``date_field``."""
    from django.db.models import Sum
    if from_date:
        qs = qs.filter(**{f"{date_field}__gte": from_date})
    if to_date:
        qs = qs.filter(**{f"{date_field}__lte": to_date})
    agg = {f"_{f}": Sum(f) for f in value_fields}
    out = {}
    for row in qs.values("item_id").annotate(**agg):
        total = Z
        for f in value_fields:
            total += row[f"_{f}"] or Z
        if total:
            out[row["item_id"]] = out.get(row["item_id"], Z) + total
    return out


def warehouse_stock_summary(warehouse_id, from_date=None, to_date=None, item_id=None):
    """Per-item stock summary at a warehouse — Inventory > Reports > Stock Report.

    For every item with activity or a balance, returns opening, movements in
    the window bucketed as Purchase/Transfer-In vs Consumption/Transfer-Out,
    Sold / Sale Return, and closing. Quantities are in the item's storage unit,
    with the bag equivalent for items that define ``kg_per_bag``.

    Sold / Sale Return are always zero: sales in this system are not recorded
    against a warehouse (``SalesInvoiceItem`` has no location), so stock leaves
    a warehouse only via issue, transfer-out or a deduct adjustment. The columns
    are kept so the report matches the standard layout.
    """
    from purchase.models import GeneralPurchaseItem
    from inventory.models import (Item, StockReceiveItem, StockTransfer, StockIssueItem,
                                  InventoryAdjustmentItem, MedicineTransferItem)

    def scope(qs):
        return qs.filter(item_id=item_id) if item_id else qs

    purch = scope(GeneralPurchaseItem.objects.filter(farm_warehouse_id=warehouse_id))
    tr_in = scope(StockTransfer.objects.filter(to_location_type="warehouse", to_warehouse_id=warehouse_id))
    recv = scope(StockReceiveItem.objects.filter(location_type="warehouse", warehouse_id=warehouse_id))
    adj_add = scope(InventoryAdjustmentItem.objects.filter(
        adjustment_type="Add", adjustment__location_type="warehouse",
        adjustment__warehouse_id=warehouse_id))

    tr_out = scope(StockTransfer.objects.filter(from_location_type="warehouse", from_warehouse_id=warehouse_id))
    issued = scope(StockIssueItem.objects.filter(location_type="warehouse", warehouse_id=warehouse_id))
    adj_ded = scope(InventoryAdjustmentItem.objects.filter(
        adjustment_type="Deduct", adjustment__location_type="warehouse",
        adjustment__warehouse_id=warehouse_id))

    # (queryset, value fields, date field) for every inflow / outflow source.
    inflow_sources = [
        (purch, ["rcv_qty", "free_qty"], "purchase__date"),
        (tr_in, ["quantity"], "date"),
        (recv, ["quantity"], "receive__date"),
        (adj_add, ["quantity"], "adjustment__date"),
        (scope(MedicineTransferItem.objects.filter(
            transfer__to_location_type="warehouse",
            transfer__to_warehouse_id=warehouse_id)), ["quantity"], "transfer__date"),
    ]
    outflow_sources = [
        (tr_out, ["quantity"], "date"),
        (issued, ["quantity"], "issue__date"),
        (adj_ded, ["quantity"], "adjustment__date"),
        (scope(MedicineTransferItem.objects.filter(
            transfer__from_location_type="warehouse",
            transfer__from_warehouse_id=warehouse_id)), ["quantity"], "transfer__date"),
    ]

    def bucket(sources, start=None, end=None):
        merged = {}
        for qs, fields, date_field in sources:
            for item_pk, total in _sum_by_item(qs, fields, date_field, start, end).items():
                merged[item_pk] = merged.get(item_pk, Z) + total
        return merged

    # Opening = everything strictly before the window.
    day_before = None
    if from_date:
        from datetime import timedelta
        day_before = from_date - timedelta(days=1)
    open_in = bucket(inflow_sources, None, day_before) if from_date else {}
    open_out = bucket(outflow_sources, None, day_before) if from_date else {}

    win_in = bucket(inflow_sources, from_date, to_date)
    win_out = bucket(outflow_sources, from_date, to_date)

    item_ids = set(open_in) | set(open_out) | set(win_in) | set(win_out)
    if not item_ids:
        return []

    items = (Item.objects.filter(id__in=item_ids)
             .select_related("category", "storage_uom")
             .order_by("description"))

    def bags(qty, kg_per_bag):
        if kg_per_bag and Decimal(str(kg_per_bag)) > 0:
            return qty / Decimal(str(kg_per_bag))
        return Z

    rows = []
    for it in items:
        opening = open_in.get(it.id, Z) - open_out.get(it.id, Z)
        moved_in = win_in.get(it.id, Z)
        moved_out = win_out.get(it.id, Z)
        sold = Z          # sales are not warehouse-attributed - see docstring
        sale_return = Z
        closing = opening + moved_in - moved_out - sold + sale_return
        kpb = it.kg_per_bag
        rows.append({
            "category": it.category.name if it.category_id else "",
            "item": it.description,
            "item_id": it.id,
            "unit": (it.storage_uom.name if it.storage_uom_id else ""),
            "opening": opening, "opening_bags": bags(opening, kpb),
            "in": moved_in, "in_bags": bags(moved_in, kpb),
            "out": moved_out, "out_bags": bags(moved_out, kpb),
            "sold": sold, "sold_bags": bags(sold, kpb),
            "sale_return": sale_return, "sale_return_bags": bags(sale_return, kpb),
            "closing": closing, "closing_bags": bags(closing, kpb),
        })
    return rows
