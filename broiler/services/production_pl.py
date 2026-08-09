"""Production Profit & Loss for one batch, at the prices actually paid.

The Growing Charge Statement answers "what is the farmer owed?" against the
rates in the Growing Charge Master. This answers "what did this flock make or
lose for the company?" — and for that, only money actually spent counts, so
every cost here is priced from purchases (see purchase_cost).

Built on what the system records today. Several lines a poultry P&L normally
carries — litter and manure sales, labour, electricity, depreciation — have no
transaction behind them in this ERP, so they are reported as untracked rather
than as zero. A zero says the flock earned nothing from manure; untracked says
nobody recorded it, and only one of those is true.
"""
from __future__ import annotations

from decimal import Decimal

from .purchase_cost import purchase_rates, value_consumption

Q2 = Decimal("0.01")
ZERO = Decimal("0.00")


def _d(value):
    return Decimal(str(value or 0))


def _div(numerator, denominator):
    n, d = _d(numerator), _d(denominator)
    return (n / d).quantize(Q2) if d else ZERO


#: Cost and revenue lines this ERP has no transaction for. Listed rather than
#: omitted so the report can show the head and say plainly that nothing is
#: recorded against it — an absent row reads as a complete statement.
UNTRACKED_REVENUE = ["Bird Transfer Income", "Litter Sales", "Gunny Bag Sales",
                     "Manure Sales", "Scrap Sales", "Insurance Claim", "Other Income"]
GROWING_HEADS = ["Labour", "Electricity", "Diesel", "Water", "Gas",
                 "Repair & Maintenance", "Biosecurity", "Supervisor Salary",
                 "Miscellaneous"]
ADMIN_HEADS = ["Office Expense Allocation", "Accounting Charges", "Depreciation",
               "Interest Allocation", "Insurance"]
UNTRACKED_COST = GROWING_HEADS + ADMIN_HEADS


def build_production_pl(report, batch):
    """The P&L for a batch, from an already-built batch report.

    Takes the report rather than rebuilding it: the Growing Charge Statement
    has already collected this flock's placements, feed movement, medicine and
    sales, and gathering them twice would be two chances for the two pages to
    disagree about the same batch.
    """
    costing = report.get("batch_costing") or {}
    sales = report.get("bird_sales") or []

    # --- revenue ---------------------------------------------------------
    live_bird_sales = sum((_d(r.get("amount")) for r in sales), ZERO)
    revenue_lines = [{"label": "Live Bird Sales", "amount": live_bird_sales,
                      "tracked": True}]
    revenue_lines += [{"label": name, "amount": None, "tracked": False}
                      for name in UNTRACKED_REVENUE]
    total_revenue = live_bird_sales

    # --- what the flock consumed, priced from purchases -------------------
    consumption, item_ids = _consumption_rows(report)
    rates = purchase_rates(item_ids, on_or_before=costing.get("sale_start_date"))

    feed_cost, feed_unpriced = value_consumption(
        [r for r in consumption if r["kind"] == "feed"], rates)
    medicine_cost, med_unpriced = value_consumption(
        [r for r in consumption if r["kind"] == "medicine"], rates)

    # Chicks are bought as a placement, so what was paid for them is on the
    # placement itself rather than in a feed store's purchase history.
    chick_cost = sum((_d(r.get("amount")) for r in (report.get("chick_placements") or [])), ZERO)

    tracked_cost = (chick_cost + feed_cost + medicine_cost).quantize(Q2)
    # Grouped the way the statement is read: five named blocks, each with its
    # own total, then one grand total. Two of the five have nothing behind them
    # in this system yet and say so rather than showing a total of zero.
    cost_blocks = [
        {"title": "Chick Cost", "accent": "#2a78d6", "total": chick_cost.quantize(Q2),
         "tracked": True,
         "lines": [{"label": "Chick Placement", "amount": chick_cost.quantize(Q2),
                    "tracked": True}]},
        {"title": "Feed Cost", "accent": "#1baf7a", "total": feed_cost, "tracked": True,
         "lines": [{"label": "Feed Consumed", "amount": feed_cost, "tracked": True}]},
        {"title": "Medicine & Health Cost", "accent": "#e87ba4", "total": medicine_cost,
         "tracked": True,
         "lines": [{"label": "Medicine & Vaccine Consumed", "amount": medicine_cost,
                    "tracked": True}]},
        {"title": "Growing Expenses", "accent": "#4a3aa7", "total": None, "tracked": False,
         "lines": [{"label": n, "amount": None, "tracked": False} for n in GROWING_HEADS]},
        {"title": "Administrative Cost", "accent": "#eda100", "total": None,
         "tracked": False,
         "lines": [{"label": n, "amount": None, "tracked": False} for n in ADMIN_HEADS]},
    ]
    cost_lines = [line for block in cost_blocks for line in block["lines"]]

    # --- the result -------------------------------------------------------
    sold_weight = _d(costing.get("sold_weight"))
    sold_birds = _d(costing.get("sold_birds"))
    placed = _d(costing.get("chicks_placed"))
    gross_profit = (total_revenue - tracked_cost).quantize(Q2)

    return {
        "revenue_lines": revenue_lines,
        "total_revenue": total_revenue.quantize(Q2),
        "cost_blocks": cost_blocks,
        "cost_lines": cost_lines,
        "total_cost": tracked_cost,
        "gross_profit": gross_profit,
        "profit_pct": _div(gross_profit * 100, total_revenue),
        "profit_per_bird_placed": _div(gross_profit, placed),
        "profit_per_bird_sold": _div(gross_profit, sold_birds),
        "profit_per_kg": _div(gross_profit, sold_weight),
        "kpis": {
            "average_sale_rate": _div(total_revenue, sold_weight),
            "cost_per_kg_live_weight": _div(tracked_cost, sold_weight),
            "feed_cost_per_kg": _div(feed_cost, sold_weight),
            "chick_cost_per_bird": _div(chick_cost, placed),
            "medicine_cost_per_bird": _div(medicine_cost, placed),
            "fcr": costing.get("fcr"),
            "cfcr": costing.get("cfcr"),
            "eef": costing.get("eef"),
            "mortality_pct": costing.get("total_mort_pct"),
            "livability_pct": costing.get("livability_pct"),
            "avg_weight": costing.get("avg_body_weight"),
        },
        # Named, not swallowed: a total that silently drops an item reads as a
        # cheaper flock rather than an incomplete one.
        "unpriced_items": sorted(feed_unpriced | med_unpriced),
        "untracked_note": (
            "Growing and administrative costs are not recorded against a batch "
            "in this system, so this statement covers chick, feed and medicine "
            "only. Profit shown is before those costs."
        ),
    }


def _consumption_rows(report):
    """What the flock ate and was treated with, as ``{item_id, quantity, kind}``.

    Feed is summarised by item code on the batch report, so the codes are
    resolved back to items here; medicine consumption already names its item.
    """
    from inventory.models import Item

    feed_rows = report.get("feed_summary") or []
    codes = [r.get("item") for r in feed_rows if r.get("item")]
    by_code = {}
    if codes:
        for item in Item.objects.filter(description__in=codes):
            by_code[item.description] = item.id

    rows, item_ids = [], set()
    for row in feed_rows:
        item_id = by_code.get(row.get("item"))
        rows.append({"item_id": item_id, "quantity": _d(row.get("consumed")),
                     "kind": "feed"})
        if item_id:
            item_ids.add(item_id)
    for row in report.get("medicine_consumption") or []:
        item_id = row.get("item_id")
        rows.append({"item_id": item_id, "quantity": _d(row.get("quantity")),
                     "kind": "medicine"})
        if item_id:
            item_ids.add(item_id)
    return rows, item_ids
