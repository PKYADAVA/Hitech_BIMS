"""Production Cost — what a flock cost to grow, per batch and in aggregate.

Deliberately not the Production P&L. That page answers what a flock *made*,
and stops at revenue less cost. This one only ever looks at the cost side, and
asks the two questions a production manager brings to it: where did the money
go, and was it more than it should have been.

"More than it should have been" needs a standard to measure against, and there
is exactly one in this system — ``Item.standard_cost_per_unit``, the rate the
item master says a kilo of feed or a dose of medicine ought to cost. Actual is
what was really paid, taken from purchases the same way the P&L takes it, so
the variance between the two is a price variance on real consumption rather
than a guess.

Everything is assembled from the same batch report and the same P&L service
the other pages use. A flock's feed cost cannot read one way here and another
on the statement.
"""
from decimal import Decimal

ZERO = Decimal("0")
Q2 = Decimal("0.01")


def _d(value):
    if value in (None, ""):
        return ZERO
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _div(numerator, denominator):
    """None, not zero, when there is nothing to divide by.

    A cost per kilo on a flock that has sold no birds is not ₹0.00 — it is not
    yet knowable, and printing zero invites somebody to average it in.
    """
    n, d = _d(numerator), _d(denominator)
    return (n / d).quantize(Q2) if d else None


def standard_consumption_cost(rows):
    """What the flock's consumption would have cost at item-master rates.

    Returns ``(total, unpriced)``. An item with no standard cost on it is named
    rather than treated as free — the same rule the actual side follows for an
    item with no purchase behind it, and for the same reason: a total that
    silently drops a line reads as a cheaper flock.
    """
    from inventory.models import Item

    item_ids = {r.get("item_id") for r in rows if r.get("item_id")}
    rates = {i["id"]: _d(i["standard_cost_per_unit"])
             for i in Item.objects.filter(id__in=item_ids)
             .values("id", "standard_cost_per_unit")}
    total, unpriced = ZERO, set()
    for row in rows:
        item_id = row.get("item_id")
        rate = rates.get(item_id)
        if not rate:
            if row.get("name"):
                unpriced.add(row["name"])
            continue
        total += _d(row.get("quantity")) * rate
    return total.quantize(Q2), unpriced


def cost_rows_from_pl(pl):
    """The statement's cost blocks flattened to ``[(head, amount)]``.

    Keyed off the block titles the P&L service names, and the hand-entered
    blocks are split back into their own heads — a component chart that says
    "Growing Expenses ₹1.65 L" hides which of labour, electricity or diesel
    actually moved.
    """
    out = []
    for block in pl["cost_blocks"]:
        title = block["title"]
        if title in ("Growing Expenses", "Administrative Cost"):
            for line in block["lines"]:
                if line.get("amount") is not None:
                    out.append((line["label"], _d(line["amount"])))
        elif block.get("total") is not None:
            out.append((title, _d(block["total"])))
    return out


def build_production_cost(rows):
    """Aggregate a list of per-batch rows into the report's summary sections.

    Takes rows already built by the view (one report build per flock, shared
    with the P&L list) rather than rebuilding them, so the totals and the table
    cannot disagree.
    """
    birds_placed = sum((_d(r["placed"]) for r in rows), ZERO)
    live_birds = sum((_d(r["live_birds"]) for r in rows), ZERO)
    live_weight = sum((_d(r["weight"]) for r in rows), ZERO)
    feed_kg = sum((_d(r["feed_kg"]) for r in rows), ZERO)
    total_cost = sum((_d(r["total_cost"]) for r in rows), ZERO)
    std_cost = sum((_d(r["std_cost"]) for r in rows), ZERO)
    feed_cost = sum((_d(r["feed_cost"]) for r in rows), ZERO)
    mortality = sum((_d(r["mortality"]) for r in rows), ZERO)

    # Components across every flock selected, largest first: the chart exists
    # to answer "where did it go", and that is read from the top.
    components = {}
    for row in rows:
        for head, amount in row["components"]:
            components[head] = components.get(head, ZERO) + amount
    component_rows = [
        {"head": head, "amount": amount.quantize(Q2),
         "pct": _div(amount * 100, total_cost)}
        for head, amount in sorted(components.items(), key=lambda kv: -kv[1])
    ]

    variance = (total_cost - std_cost).quantize(Q2)
    # The standard split the same way the actual is, so the performance table
    # can put feed beside feed rather than only totals beside totals.
    std_feed = sum((_d(r["std_feed_cost"]) for r in rows), ZERO)
    std_other = (std_cost - std_feed)
    sale_value = sum((_d(r["sale_value"]) for r in rows), ZERO)
    sold_birds = sum((_d(r["sold_birds"]) for r in rows), ZERO)
    std_fcrs = [_d(r["std_fcr"]) for r in rows if r["std_fcr"]]

    def col(key):
        """Sum a block column, skipping flocks with nothing under it. None all
        the way across stays None — a head nobody filled in is not nil."""
        vals = [r[key] for r in rows if r.get(key) is not None]
        return sum(vals, ZERO).quantize(Q2) if vals else None

    return {
        "chick_cost": col("chick_cost"),
        "medicine_cost": col("medicine_cost"),
        "growing_cost": col("growing_cost"),
        "admin_cost": col("admin_cost"),
        "std_feed_cost": std_feed.quantize(Q2),
        "std_other_cost": std_other.quantize(Q2),
        "feed_variance": (feed_cost - std_feed).quantize(Q2),
        "feed_variance_pct": _div((feed_cost - std_feed) * 100, std_feed),
        "other_variance": ((total_cost - feed_cost) - std_other).quantize(Q2),
        "other_variance_pct": _div((total_cost - feed_cost - std_other) * 100, std_other),
        "feed_cost_pct": _div(feed_cost * 100, total_cost),
        "sale_value": sale_value.quantize(Q2),
        "sold_birds": sold_birds,
        # A plain mean is right here: it is a comparison of curves, not money,
        # and every flock's standard is read at its own age.
        "std_fcr": (sum(std_fcrs, ZERO) / len(std_fcrs)).quantize(Q2) if std_fcrs else None,
        "std_cost_per_bird": _div(std_cost, birds_placed),
        "variance_per_bird": (
            None if not birds_placed else (variance / birds_placed).quantize(Q2)),
        "birds_placed": birds_placed,
        "live_birds": live_birds,
        "mortality": mortality,
        "mortality_pct": _div(mortality * 100, birds_placed),
        "live_weight": live_weight.quantize(Q2),
        "avg_weight": _div(live_weight, live_birds),
        "feed_kg": feed_kg.quantize(Q2),
        "total_cost": total_cost.quantize(Q2),
        "feed_cost": feed_cost.quantize(Q2),
        "other_cost": (total_cost - feed_cost).quantize(Q2),
        "cost_per_kg": _div(total_cost, live_weight),
        "cost_per_bird": _div(total_cost, birds_placed),
        "feed_per_bird": _div(feed_kg, live_birds),
        # Weighted, never a mean of the rows: FCR is feed over weight, and
        # averaging four flocks' ratios lets a 200 kg flock pull as hard as a
        # 23,000 kg one.
        "fcr": _div(feed_kg, live_weight),
        "components": component_rows,
        "std_cost": std_cost.quantize(Q2),
        "std_cost_per_kg": _div(std_cost, live_weight),
        "variance": variance,
        "variance_pct": _div(variance * 100, std_cost),
        "variance_per_kg": (
            None if not live_weight else (variance / live_weight).quantize(Q2)),
        # Named, so a variance computed over incomplete consumption is not read
        # as a saving.
        "unpriced": sorted({name for r in rows for name in r["unpriced"]}),
        "no_standard": sorted({name for r in rows for name in r["no_standard"]}),
    }
