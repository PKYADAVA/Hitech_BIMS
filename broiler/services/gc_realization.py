"""Standard vs Farmer Realization vs Management Realization — one batch, three
cost lenses, side by side.

The Growing Charge Statement answers "what is the farmer owed?" and the
Production P&L answers "what did this flock make or lose, at prices actually
paid?" This answers a third, narrower question: how much of the gap between
those two is the farmer's problem to bear, and how much is the company's own
procurement risk?

Three columns, one row of physical facts (birds placed, birds sold, sold
weight — one flock only has one of each) and three different costing bases
layered on top of them:

* **Standard** — a fully hypothetical run of the batch, priced entirely off
  the Growing Charge Master for this branch: standard mortality, standard
  FCR, the master's chick/feed/medicine/admin rates, and the age-appropriate
  standard body weight from the Breed Standard curve. Nothing here is real —
  it is the scheme's own promise of what this batch *should* cost.
* **Farmer Realization** — the flock's real performance (actual mortality,
  actual feed consumed, actual sale weight) costed at the *same standard
  rates* as the Standard column. This is deliberate, not an oversight: the
  farmer's chick charge is assessed against the scheme's standard survivor
  count, not the batch's actual one, so a bad mortality week shows up as a
  separate mortality decentive (see broiler.views._actual_gc_rate) rather
  than silently inflating the farmer's base chick cost. Feed, priced at the
  master rate but the real quantity consumed, is the one place the farmer's
  own performance already flows through.
* **Management Realization** — the same real performance, costed at what the
  company actually paid: feed at the weighted average of real purchase
  invoices (see purchase_cost.purchase_rates), chicks at the batch's real
  placement cost (the closest this system can get to an invoice rate today —
  see the note on chick costing below). This is the company's own economics,
  procurement price swings and all.

**Why chick cost has no true "real purchase cost" of its own.** Chicks are
bought into a branch warehouse and reach a batch only through a Stock
Transfer, which is valued at the Item Price Master rate, not a traceable
invoice. There is no per-batch invoice to weight-average, the way there is
for feed. So Management's chick cost reuses the batch's own placement amount
(``batch_costing["chick_cost"]``) — the same figure the Production P&L
already treats as the best available answer to "what did these chicks cost."

Nothing here writes anything. This is a comparison, not a settlement — the
farmer is still paid whatever GrowingChargeSettlement computes; this exists
so someone can see, before or after that settlement, how much of the
difference between the scheme's promise and the company's real spend came
from the farmer's own performance versus the price the company itself paid.
"""
from __future__ import annotations

from decimal import Decimal

Q2 = Decimal("0.01")
Q4 = Decimal("0.0001")
ZERO = Decimal("0.00")


def _d(value):
    return Decimal(str(value)) if value not in (None, "", "No Data") else ZERO


def _div(numerator, denominator, places=Q2):
    n, d = _d(numerator), _d(denominator)
    return (n / d).quantize(places) if d else ZERO


def _pct(numerator, denominator):
    return _div(numerator * 100, denominator)


def build_gc_realization(batch, report, scheme):
    """The three-column comparison for one batch.

    ``report`` is an already-built ``_build_batch_report(batch,
    fetch_type="farmer")`` — reused rather than rebuilt, on the same principle
    every other report in this module follows: the Growing Charge Statement,
    the Production P&L and this comparison must never independently recompute
    a batch's mortality or feed consumption and risk disagreeing about it.

    Returns ``{"particulars": [...], "scenarios": [...], "has_scheme": bool}``.
    A missing scheme collapses to just the real, actual-basis figures under
    "Farmer Realization" and "Management Realization" — Standard has nothing
    to be computed from, and is shown as "No Data" rather than zero, the same
    convention ``_build_batch_costing`` already uses.
    """
    from broiler.services.purchase_cost import purchase_rates, value_consumption
    from broiler.views import _actual_gc_rate, _breed_standard_at

    bc = report["batch_costing"]

    placed = _d(bc.get("chicks_placed"))
    actual_survivors = _d(bc.get("sold_birds"))
    actual_sold_weight = _d(bc.get("sold_weight"))
    actual_avg_sale_rate = _d(bc.get("avg_sale_rate"))
    actual_feed_consumed = _d(bc.get("feed_consumed"))
    actual_mort_pct = _d(bc.get("total_mort_pct"))
    actual_mort_no = _d(bc.get("mortality"))
    actual_avg_weight = _d(bc.get("avg_body_weight"))
    mean_age = _d(bc.get("mean_age"))

    has_scheme = bool(scheme)
    if not has_scheme:
        std_survivors = ZERO
        std_avg_weight = ZERO
        std_mort_pct = ZERO
        std_chick_rate = std_feed_rate = std_med_rate = std_admin_rate = ZERO
        std_fcr = ZERO
    else:
        std_mort_pct = _d(scheme.standard_mortality)
        std_survivors = (placed * (Decimal("100") - std_mort_pct) / Decimal("100")).quantize(Decimal("1"))
        std_fcr = _d(scheme.standard_fcr)
        std_chick_rate = _d(scheme.chick_cost)
        std_feed_rate = _d(scheme.feed_cost)
        std_med_rate = _d(scheme.medicine_cost)
        std_admin_rate = _d(scheme.farmer_admin_cost)
        # The scheme has no body-weight field of its own — that lives on the
        # Breed Standard curve, keyed by (breed, age), which is the master this
        # batch's own breed already points at. Reuses the same exact-age-else-
        # nearest-below lookup the Live Flock Summary Report already relies on.
        age = int(mean_age.to_integral_value()) if mean_age > 0 else None
        std_row = _breed_standard_at(batch.breed_id, age)
        std_avg_weight = _d(std_row.body_weight) if std_row else ZERO

    std_live_weight = (std_survivors * std_avg_weight).quantize(Q2)

    # --- Standard column ---------------------------------------------------
    standard = _cost_column(
        chick_qty=std_survivors, chick_rate=std_chick_rate,
        feed_qty=(std_fcr * std_live_weight).quantize(Q2) if has_scheme else ZERO,
        feed_rate=std_feed_rate,
        med_qty=placed, med_rate=std_med_rate,
        admin_qty=placed, admin_rate=std_admin_rate,
        birds_sold=std_survivors, live_weight=std_live_weight,
    )

    # --- Farmer Realization: real performance, standard rates --------------
    # Medicine follows the scheme's own basis: a scheme configured for actual
    # medicine cost is answered with the batch's real spend, not the flat
    # per-bird rate, for both realization columns — Standard alone stays
    # hypothetical regardless of the basis, since it has no real spend to show.
    med_qty, med_rate, med_amount = _medicine_actual_or_rate(
        scheme, has_scheme, bc, placed, std_med_rate)
    farmer = _cost_column(
        chick_qty=std_survivors, chick_rate=std_chick_rate,
        feed_qty=actual_feed_consumed, feed_rate=std_feed_rate,
        med_qty=med_qty, med_rate=med_rate, med_amount=med_amount,
        admin_qty=placed, admin_rate=std_admin_rate,
        birds_sold=actual_survivors, live_weight=actual_sold_weight,
    )

    # --- Management Realization: real performance, real cost ---------------
    feed_item_ids = _feed_item_ids(report)
    real_feed_rates = purchase_rates(feed_item_ids, on_or_before=bc.get("sale_start_date")) \
        if feed_item_ids else {}
    real_feed_cost, feed_unpriced = value_consumption(
        _feed_rows_for_pricing(report), real_feed_rates)
    # No purchase to price feed from at all -> nothing to fall back to except
    # the master rate, flagged rather than silently substituted.
    real_feed_rate = _div(real_feed_cost, actual_feed_consumed) if real_feed_cost else std_feed_rate

    # Chicks have no invoice to weight-average (see module docstring); the
    # batch's own real placement spend is the best available "real" figure.
    real_chick_cost = _d(bc.get("chick_cost"))
    real_chick_rate = _div(real_chick_cost, placed) if placed else ZERO

    management = _cost_column(
        chick_qty=placed, chick_rate=real_chick_rate, chick_amount=real_chick_cost,
        feed_qty=actual_feed_consumed, feed_rate=real_feed_rate,
        feed_amount=real_feed_cost if real_feed_cost else None,
        med_qty=med_qty, med_rate=med_rate, med_amount=med_amount,
        admin_qty=placed, admin_rate=std_admin_rate,
        birds_sold=actual_survivors, live_weight=actual_sold_weight,
    )

    # --- GC rate / penalty-incentive, reusing the settlement's own engine ---
    # std_cost is the scheme's own master figure (bc["std_prod_per_kg"]), the
    # exact baseline GrowingChargeSettlement itself uses — not this report's
    # own Standard column total, which can legitimately differ from it (the
    # master figure is a separately-entered number, not derived from the
    # chick/feed/medicine/admin breakdown).
    std_cost_ref = _d(bc.get("std_prod_per_kg"))
    base_gc_rate = _d(bc.get("base_gc_rate"))
    for column in (standard, farmer, management):
        gc_rate = _actual_gc_rate(scheme, std_cost_ref, column["production_cost_per_kg"],
                                  base_gc_rate) if has_scheme else ZERO
        column["base_gc_rate"] = base_gc_rate
        column["diff_from_std_cost"] = (column["production_cost_per_kg"] - std_cost_ref).quantize(Q2) \
            if has_scheme else ZERO
        column["penalty_incentive"] = (gc_rate - base_gc_rate).quantize(Q4)
        column["actual_gc_rate"] = gc_rate.quantize(Q4)
        column["farmer_gc_income_payable"] = (gc_rate * column["live_weight"]).quantize(Q2)

    # --- market price / revenue / profit ------------------------------------
    # Standard has no sale of its own to price from — it is charged at the
    # break-even the master implies: what the standard cost would need to sell
    # for to clear the standard growing-charge margin. Farmer and Management
    # share the one real sale this flock actually had.
    standard["market_price"] = (std_cost_ref + base_gc_rate).quantize(Q4) if has_scheme else ZERO
    farmer["market_price"] = actual_avg_sale_rate
    management["market_price"] = actual_avg_sale_rate

    for column in (standard, farmer, management):
        column["total_market_revenue"] = (column["market_price"] * column["live_weight"]).quantize(Q2)
        column["market_sale_profit"] = (column["total_market_revenue"]
                                        - column["total_production_cost"]).quantize(Q2)
        column["profit_per_kg"] = _div(column["market_sale_profit"], column["live_weight"])
        column["profit_per_bird"] = _div(column["market_sale_profit"], column["birds_sold"])

    std_profit = standard["market_sale_profit"]
    for column in (standard, farmer, management):
        # How much better or worse off the company is under this column's
        # basis than under the Standard scenario — zero for Standard itself,
        # by construction.
        column["total_company_revenue"] = (column["market_sale_profit"] - std_profit).quantize(Q2)

    def scenario(key, label, column, mort_pct, mort_no, avg_weight, feed_consumed):
        values = _row(column, placed, mort_pct, mort_no, avg_weight, feed_consumed, has_scheme)
        return {"key": key, "label": label, "values": values, "cells": _format_cells(values)}

    scenarios = [
        scenario("standard", "Standard", standard,
                std_mort_pct, std_mort_no(placed, std_mort_pct), std_avg_weight, None),
        scenario("farmer", "Farmer Realization", farmer,
                actual_mort_pct, actual_mort_no, actual_avg_weight, actual_feed_consumed),
        scenario("management", "Management Realization", management,
                actual_mort_pct, actual_mort_no, actual_avg_weight, actual_feed_consumed),
    ]

    return {
        "particulars": PARTICULARS,
        "scenarios": scenarios,
        "has_scheme": has_scheme,
        "scheme_code": scheme.scheme_code if scheme else "",
        # Named rather than silently folded into the rate: a feed item this
        # flock ate with no purchase behind it would otherwise make
        # Management's feed cost look cheaper than it really was.
        "feed_unpriced": sorted(feed_unpriced),
    }


def std_mort_no(placed, std_mort_pct):
    return (placed * std_mort_pct / Decimal("100")).quantize(Decimal("1"))


def _cost_column(*, chick_qty, chick_rate, feed_qty, feed_rate, med_qty, med_rate,
                  admin_qty, admin_rate, birds_sold, live_weight,
                  chick_amount=None, feed_amount=None, med_amount=None):
    chick_amount = (chick_amount if chick_amount is not None
                    else (chick_qty * chick_rate).quantize(Q2))
    feed_amount = (feed_amount if feed_amount is not None
                   else (feed_qty * feed_rate).quantize(Q2))
    med_amount = (med_amount if med_amount is not None
                  else (med_qty * med_rate).quantize(Q2))
    admin_amount = (admin_qty * admin_rate).quantize(Q2)
    total_cost = (chick_amount + feed_amount + med_amount + admin_amount).quantize(Q2)
    feed_per_bird = _div(feed_qty, birds_sold, Q4)
    return {
        "chick_qty": chick_qty, "chick_rate": chick_rate, "chick_amount": chick_amount,
        "feed_qty": feed_qty, "feed_rate": feed_rate, "feed_amount": feed_amount,
        "feed_per_bird": feed_per_bird,
        "med_qty": med_qty, "med_rate": med_rate, "med_amount": med_amount,
        "admin_rate": admin_rate, "admin_amount": admin_amount,
        "birds_sold": birds_sold, "live_weight": live_weight,
        "total_production_cost": total_cost,
        "production_cost_per_kg": _div(total_cost, live_weight),
        "production_cost_per_bird": _div(total_cost, birds_sold),
    }


def _medicine_actual_or_rate(scheme, has_scheme, bc, placed, std_med_rate):
    """(quantity, rate, amount) for the medicine line, per the scheme's own
    ``medicine_cost_basis`` — "actual" prices this flock's real consumption,
    anything else charges the flat per-bird rate. Standard never sees this: it
    always uses the flat rate, since it has no real consumption to show."""
    from broiler.models import GrowingChargeScheme

    if has_scheme and scheme.medicine_cost_basis == GrowingChargeScheme.MedicineCostBasis.ACTUAL:
        amount = _d(bc.get("med_cost"))
        return placed, _div(amount, placed), amount
    return placed, std_med_rate, None


def _feed_item_ids(report):
    from inventory.models import Item

    codes = [r.get("item") for r in (report.get("feed_summary") or []) if r.get("item")]
    if not codes:
        return []
    return list(Item.objects.filter(description__in=codes).values_list("id", flat=True))


def _feed_rows_for_pricing(report):
    """This batch's feed consumption as ``{item_id, quantity}`` rows, resolved
    from the feed summary's item codes — the same join production_pl.py's
    ``_consumption_rows`` does, kept local so this module has no import-order
    dependency on it."""
    from inventory.models import Item

    feed_rows = report.get("feed_summary") or []
    codes = [r.get("item") for r in feed_rows if r.get("item")]
    by_code = {i.description: i.id for i in Item.objects.filter(description__in=codes)} if codes else {}
    return [{"item_id": by_code.get(r.get("item")), "quantity": _d(r.get("consumed"))}
            for r in feed_rows]


def _row(column, placed, mort_pct, mort_no, avg_weight, feed_consumed, has_scheme):
    """Flatten one column into the particular-keyed dict the template reads."""
    return {
        "chicks_placed": placed,
        "chick_cost_rate": column["chick_rate"],
        "feed_cost_rate": column["feed_rate"],
        "standard_fcr": _div(column["feed_qty"], column["live_weight"], Decimal("0.0001")),
        "medicine_cost_rate": column["med_rate"],
        "actual_medicine_cost": column["med_amount"] if column["med_amount"] else None,
        "actual_feed_consumption": feed_consumed,
        "admin_cost_rate": column["admin_rate"],
        "free_mortality_pct": mort_pct,
        "mortality_no": mort_no,
        "avg_live_weight": avg_weight,
        "market_price": column["market_price"],
        "base_gc_rate": column["base_gc_rate"],
        "birds_sold": column["birds_sold"],
        "total_live_weight": column["live_weight"],
        "total_feed_required": column["feed_qty"],
        "feed_required_per_bird": column["feed_per_bird"],
        "total_feed_cost": column["feed_amount"],
        "total_chick_cost": column["chick_amount"],
        "total_medicine_cost": column["med_amount"],
        "total_admin_cost": column["admin_amount"],
        "total_production_cost": column["total_production_cost"],
        "production_cost_per_kg": column["production_cost_per_kg"],
        "production_cost_per_bird": column["production_cost_per_bird"],
        "diff_from_std_cost": column["diff_from_std_cost"],
        "penalty_incentive": column["penalty_incentive"],
        "actual_gc_rate": column["actual_gc_rate"],
        "farmer_gc_income_payable": column["farmer_gc_income_payable"],
        "total_market_revenue": column["total_market_revenue"],
        "market_sale_profit": column["market_sale_profit"],
        "profit_per_kg": column["profit_per_kg"],
        "profit_per_bird": column["profit_per_bird"],
        "total_company_revenue": column["total_company_revenue"],
    }


#: Column order + display metadata for the horizontal table. Kept as one
#: ordered list, read by both the JSON API and the template, so a row added
#: here appears in the same place on both without being listed twice.
PARTICULARS = [
    ("chicks_placed", "Number of Chicks Placed", "", 0),
    ("chick_cost_rate", "Chick Cost", "₹/bird", 2),
    ("feed_cost_rate", "Feed Cost", "₹/kg", 2),
    ("standard_fcr", "FCR", "", 4),
    ("medicine_cost_rate", "Medicine Cost", "₹/bird", 2),
    ("actual_medicine_cost", "Actual Medicine Cost", "₹", 2),
    ("actual_feed_consumption", "Actual Total Feed Consumption", "kg", 2),
    ("admin_cost_rate", "Admin Cost", "₹/bird", 2),
    ("free_mortality_pct", "Mortality %", "%", 2),
    ("mortality_no", "Mortality No.", "", 0),
    ("avg_live_weight", "Avg Live Weight per Bird", "kg", 3),
    ("market_price", "Market Price", "₹/kg", 4),
    ("base_gc_rate", "Base GC Rate", "₹/kg", 2),
    ("birds_sold", "Birds Sold", "", 0),
    ("total_live_weight", "Total Live Weight", "kg", 2),
    ("total_feed_required", "Total Feed Required", "kg", 2),
    ("feed_required_per_bird", "Feed Required/Bird", "kg", 4),
    ("total_feed_cost", "Total Feed Cost", "₹", 2),
    ("total_chick_cost", "Total Chick Cost", "₹", 2),
    ("total_medicine_cost", "Total Medicine Cost", "₹", 2),
    ("total_admin_cost", "Total Admin Cost", "₹", 2),
    ("total_production_cost", "Total Production Cost", "₹", 2),
    ("production_cost_per_kg", "Production Cost per kg", "₹", 4),
    ("production_cost_per_bird", "Production Cost per bird", "₹", 4),
    ("diff_from_std_cost", "Diff from Std Cost", "₹/kg", 2),
    ("penalty_incentive", "Penalty/Incentive", "₹/kg", 4),
    ("actual_gc_rate", "Actual GC Rate", "₹/kg", 4),
    ("farmer_gc_income_payable", "Farmer GC Income Payable", "₹", 2),
    ("total_market_revenue", "Total Market Revenue", "₹", 2),
    ("market_sale_profit", "Market Sale Profit", "₹", 2),
    ("profit_per_kg", "Profit/Loss per kg", "₹", 4),
    ("profit_per_bird", "Profit/Loss per bird", "₹", 4),
    ("total_company_revenue", "Total Company Revenue (vs Standard)", "₹", 2),
]


# ---------------------------------------------------------------------------
# Multi-farm grid — one triplet per batch, plus a totals row
# ---------------------------------------------------------------------------

#: Columns whose Total row is a straight sum across every batch's triplet —
#: the physical/₹ quantities. Everything else in PARTICULARS is a rate or
#: ratio, which a naive sum would make meaningless (summing three farms'
#: "Chick Cost ₹/bird" describes nothing real).
ADDITIVE = {
    "chicks_placed", "actual_medicine_cost", "actual_feed_consumption",
    "mortality_no", "birds_sold", "total_live_weight", "total_feed_required",
    "total_feed_cost", "total_chick_cost", "total_medicine_cost",
    "total_admin_cost", "total_production_cost", "farmer_gc_income_payable",
    "total_market_revenue", "market_sale_profit", "total_company_revenue",
}

#: Total-row rate columns, recomputed as a genuine weighted average of the
#: summed additive figures rather than left blank or naively summed —
#: ``(numerator field, denominator field, decimal places)``.
DERIVED_TOTALS = {
    "standard_fcr": ("total_feed_required", "total_live_weight", Decimal("0.0001")),
    "feed_required_per_bird": ("total_feed_required", "birds_sold", Decimal("0.0001")),
    "production_cost_per_kg": ("total_production_cost", "total_live_weight", Q4),
    "production_cost_per_bird": ("total_production_cost", "birds_sold", Q4),
    "market_price": ("total_market_revenue", "total_live_weight", Decimal("0.0001")),
    "profit_per_kg": ("market_sale_profit", "total_live_weight", Q4),
    "profit_per_bird": ("market_sale_profit", "birds_sold", Q4),
}


def build_gc_realization_grid(batches):
    """The multi-farm listing: one Standard/Farmer/Management triplet per
    batch, and a Total row summing the additive columns across all of them.

    ``batches`` is an iterable of ``BroilerBatch``, already scoped and ordered
    by the caller — data-scoping and "which batches belong on this report" are
    the view's job, the same division every other report in this module keeps.
    """
    from broiler.views import _build_batch_report, _match_growing_charge_scheme, _placement_date

    groups = []
    for batch in batches:
        scheme = _match_growing_charge_scheme(batch, _placement_date(batch))
        report = _build_batch_report(batch, fetch_type="farmer", scheme_override=scheme)
        result = build_gc_realization(batch, report, scheme)
        groups.append({
            "farm_name": batch.broiler_farm.farm_name,
            "batch_name": batch.batch_name,
            "batch_id": batch.pk,
            "has_scheme": result["has_scheme"],
            "scenarios": result["scenarios"],
        })

    return {
        "particulars": PARTICULARS,
        "groups": groups,
        "totals": _totals_row(groups),
        "has_any_batch": bool(groups),
    }


def _totals_row(groups):
    """One row per scenario — Standard, Farmer Realization, Management
    Realization — each the sum of that scenario's additive figures across
    every batch in the grid, with the rate columns re-derived from those sums
    rather than summed directly.
    """
    by_key = {"standard": {}, "farmer": {}, "management": {}}
    for group in groups:
        for scenario in group["scenarios"]:
            bucket = by_key[scenario["key"]]
            for field in ADDITIVE:
                value = scenario["values"].get(field)
                if value is None:
                    continue
                bucket[field] = bucket.get(field, ZERO) + _d(value)

    rows = []
    for key, label in (("standard", "Standard"), ("farmer", "Farmer Realization"),
                       ("management", "Management Realization")):
        values = dict(by_key[key])
        for field, (num_field, den_field, places) in DERIVED_TOTALS.items():
            values[field] = _div(values.get(num_field), values.get(den_field), places)
        rows.append({"key": key, "label": label, "values": values,
                     "cells": _format_cells(values)})
    return rows


def _format_cells(values):
    """``values`` (a particular-keyed dict) as an ordered list of display
    strings, one per :data:`PARTICULARS` entry, in that exact order.

    Built here rather than looked up by key in the template: Django templates
    have no built-in "index a dict by a loop variable" operation, and this
    project's own template-tag library for that (``broiler_extras``) no
    longer has a source file behind it — nothing to extend safely. An ordered
    list the template can simply iterate needs no such lookup at all, and
    keeps the per-particular decimal formatting in one place instead of
    scattered across template filters.
    """
    cells = []
    for key, _label, _unit, places in PARTICULARS:
        value = values.get(key)
        if value is None:
            cells.append("—")
        elif places == 0:
            cells.append(f"{int(value):,}")
        else:
            cells.append(f"{Decimal(str(value)):,.{places}f}")
    return cells
