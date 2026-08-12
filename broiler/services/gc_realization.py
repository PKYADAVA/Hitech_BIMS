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
  company actually paid: feed, chicks and medicine each priced through
  ``inventory.services.valuation.compute_issue_rate`` — the same engine
  ``StockIssue`` re-costing uses — at the source warehouse's own cost ledger,
  as of each transfer's own date, per that Item's configured valuation method
  (Standard Costing / Weighted Average / FIFO / LIFO). This is the company's
  own economics, procurement price swings and all.

None of that pricing happens in this module. It comes straight from
``_build_batch_costing`` called with ``fetch_type="management"`` — the same
function the Batch History Report's own Management view uses — so the two
pages can never disagree about what a batch's feed or chicks cost the
company. This module only decides how to *compare* that figure against the
Standard and Farmer bases; see broiler.views._build_batch_costing for the
pricing itself, including why chicks needed their own lookup
(``ChicksPurchaseItem`` prices through the purchase header's Item, not a
line, and bills on the chargeable count after mortality/shortage/weak-chick
reconciliation — not a raw received quantity).

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

#: The Standard column's medicine cost per bird — a flat figure, by request,
#: rather than GrowingChargeScheme.medicine_cost. That field only carries a
#: real number when a scheme's medicine_cost_basis is "Fixed" (its own help
#: text says so); every scheme in practice runs "Actual" or "Master" basis, so
#: the field sits at its default 0 and Standard's medicine line went blank
#: with it. Standard needs a number regardless of what any scheme's basis is
#: set to, so this is it — independent of every scheme, not read from one.
STANDARD_MEDICINE_COST_PER_BIRD = Decimal("3.00")

#: Fallback for the Standard column's avg. live weight per bird when no
#: scheme was matched at all — scheme.standard_avg_weight is the normal
#: source (editable from the report itself), this only covers the case where
#: there is no scheme row to have stored an edited value on.
STANDARD_AVG_WEIGHT_PER_BIRD = Decimal("2.00")


def _d(value):
    return Decimal(str(value)) if value not in (None, "", "No Data") else ZERO


def _div(numerator, denominator, places=Q2):
    n, d = _d(numerator), _d(denominator)
    return (n / d).quantize(places) if d else ZERO


def _pct(numerator, denominator):
    return _div(numerator * 100, denominator)


def build_gc_realization(batch, report, management_report, scheme):
    """The three-column comparison for one batch.

    ``report``/``management_report`` are already-built
    ``_build_batch_report(batch, fetch_type="farmer"/"management")`` —
    reused rather than rebuilt, on the same principle every other report in
    this module follows: the Growing Charge Statement, the Production P&L and
    this comparison must never independently recompute a batch's mortality or
    feed consumption and risk disagreeing about it. Two passes rather than one
    because the two columns need different costing bases for the same real
    events, and ``_build_batch_costing`` is what already knows how to price
    each — feed, chicks and medicine through the real valuation engine (see
    ``inventory.services.valuation.compute_issue_rate``) for the management
    pass, the scheme's own rates for the farmer one.

    Returns ``{"particulars": [...], "scenarios": [...], "has_scheme": bool}``.
    A missing scheme collapses to just the real, actual-basis figures under
    "Farmer Realization" and "Management Realization" — Standard has nothing
    to be computed from, and is shown as "No Data" rather than zero, the same
    convention ``_build_batch_costing`` already uses.
    """
    from django.utils import timezone

    from broiler.views import _actual_gc_rate, _gc_settlement_autofill

    bc = report["batch_costing"]
    mbc = management_report["batch_costing"]

    # Physical facts about this one batch — the same for all three scenario
    # rows, the same reason chicks_placed is: a costing basis changes what a
    # bird cost, never when it was placed or how old the flock is.
    placement_date = bc.get("placement_date")
    # Days since the last Daily Entry — the same staleness figure the Live
    # Flock Summary and Feed Scheduling reports already show, computed the
    # same way (_build_batch_costing carries no entry-recency field of its
    # own, so this reads the batch's own entries directly rather than
    # inventing a second definition of "gap").
    from broiler.models import DailyEntry

    latest_entry_date = (DailyEntry.objects.filter(batch=batch)
                         .order_by("-date").values_list("date", flat=True).first())
    gap_days = (timezone.localdate() - latest_entry_date).days if latest_entry_date else None
    placed = _d(bc.get("chicks_placed"))
    actual_survivors = _d(bc.get("sold_birds"))
    actual_sold_weight = _d(bc.get("sold_weight"))
    actual_avg_sale_rate = _d(bc.get("avg_sale_rate"))
    actual_feed_consumed = _d(bc.get("feed_consumed"))
    actual_mort_pct = _d(bc.get("total_mort_pct"))
    actual_mort_no = _d(bc.get("mortality"))
    # Weight per bird, from the sale when there has been one.
    #
    # bc["avg_body_weight"] is sold_weight / sold_birds, so it reads 0.000 for
    # every flock that has not lifted yet — and this report opens on live
    # flocks. Until a real sale happens the honest figure is the last weighing
    # taken on the flock, which is what a supervisor would quote if asked what
    # the birds weigh. It is superseded the moment birds are actually sold:
    # a sale is measured on a weighbridge, a weighing is a sample.
    actual_avg_weight = _d(bc.get("avg_body_weight"))
    weighed_from_sale = bool(actual_avg_weight)
    if not weighed_from_sale:
        last_weight_g = (DailyEntry.objects
                         .filter(batch=batch, avg_weight_gms__gt=0)
                         .order_by("-date", "-id")
                         .values_list("avg_weight_gms", flat=True).first())
        if last_weight_g:
            # The curve and the daily entry hold grams; every weight on this
            # report is kilos.
            actual_avg_weight = (_d(last_weight_g) / Decimal("1000")).quantize(Q4)
    # Days old today, not bc["mean_age"] — that field is a weighted average
    # age *at sale*, computed from bird_sale_rows, so it reads 0 for every
    # live (unsold) batch, which is the default filter this report opens on.
    # "Age" here means the same thing it does on the Live Flock Summary
    # Report: how old the flock is right now.
    current_age = (timezone.localdate() - placement_date).days if placement_date else None

    has_scheme = bool(scheme)
    # Editable per scheme, from the report itself (see the Standard row's
    # Medicine Cost cell) — this is scheme.standard_medicine_cost, not
    # scheme.medicine_cost; see that field's own comment for why they're kept
    # apart. Falls back to the constant only when no scheme was matched at
    # all, since there is then nowhere to have stored an edited value.
    std_med_rate = _d(scheme.standard_medicine_cost) if has_scheme else STANDARD_MEDICINE_COST_PER_BIRD
    # Editable the same way, and for the same reason: the Breed Standard curve
    # is age-matched, but it's a second master this batch's breed has to have
    # a row for at exactly this age, and the report wants one flat number for
    # the scheme, settable in place rather than dependent on that.
    std_avg_weight = _d(scheme.standard_avg_weight) if has_scheme else STANDARD_AVG_WEIGHT_PER_BIRD

    if not has_scheme:
        std_survivors = ZERO
        std_mort_pct = ZERO
        std_chick_rate = std_feed_rate = std_admin_rate = ZERO
        std_fcr = ZERO
    else:
        std_mort_pct = _d(scheme.standard_mortality)
        std_survivors = (placed * (Decimal("100") - std_mort_pct) / Decimal("100")).quantize(Decimal("1"))
        std_fcr = _d(scheme.standard_fcr)
        std_chick_rate = _d(scheme.chick_cost)
        std_feed_rate = _d(scheme.feed_cost)
        std_admin_rate = _d(scheme.farmer_admin_cost)

    std_live_weight = (std_survivors * std_avg_weight).quantize(Q2)

    # Birds still on the farm, and what they weigh at today's body weight.
    # Cost and feed were spent on the birds that left and the birds still here
    # alike, so every per-kilo figure divides by both — measuring against the
    # sold weight alone overstates a flock mid-lift. A fully sold flock is
    # unaffected: nothing is standing, so the total is the sold weight it
    # always was.
    actual_available_birds = _available_birds(placed, actual_mort_no, actual_survivors)
    actual_available_weight = (actual_available_birds * actual_avg_weight).quantize(Q2)
    actual_live_weight = (actual_sold_weight + actual_available_weight).quantize(Q2)

    # --- Standard column ---------------------------------------------------
    # The weight a growing charge is actually earned on, per column.
    standard_delivered = std_live_weight
    actual_delivered = actual_sold_weight

    standard = _cost_column(
        chick_qty=std_survivors, chick_rate=std_chick_rate,
        feed_qty=(std_fcr * std_live_weight).quantize(Q2) if has_scheme else ZERO,
        feed_rate=std_feed_rate,
        med_qty=placed, med_rate=std_med_rate,
        admin_qty=placed, admin_rate=std_admin_rate,
        birds_sold=std_survivors, live_weight=std_live_weight,
    )

    # --- Farmer Realization: real performance, standard rates --------------
    # Medicine is unconditionally real here — the farmer report's own actual
    # spend (bc["med_cost"]), not gated behind the scheme's medicine_cost_basis
    # the way a farmer's *settlement* charge would be. This column shows what
    # medicine actually cost this flock, the same convention Management's own
    # medicine line already follows (see its own comment a few lines down).
    # Divided by chicks placed, not medicine consumed, for the same reason:
    # "Medicine Cost" reads ₹/bird everywhere else in this table.
    real_med_cost_farmer = _d(bc.get("med_cost"))
    farmer_med_rate = _div(real_med_cost_farmer, placed) if placed else ZERO
    farmer = _cost_column(
        chick_qty=std_survivors, chick_rate=std_chick_rate,
        feed_qty=actual_feed_consumed, feed_rate=std_feed_rate,
        med_qty=placed, med_rate=farmer_med_rate, med_amount=real_med_cost_farmer,
        admin_qty=placed, admin_rate=std_admin_rate,
        birds_sold=actual_survivors, live_weight=actual_live_weight,
    )

    # --- Management Realization: real performance, real cost ---------------
    # feed_cost/chick_cost here come straight from the management-basis batch
    # report, which prices every transfer through the real valuation engine
    # (inventory.services.valuation.compute_issue_rate) — each one at its
    # source warehouse's own cost ledger, as of its own date, per that Item's
    # configured valuation method (Weighted Average / FIFO / LIFO / Standard).
    # That supersedes this module's own earlier feed-only purchase-average and
    # "no better data" chick-cost note — chicks now get the same real pricing
    # feed already had, once ChicksPurchaseItem is what's actually behind it.
    real_feed_cost = _d(mbc.get("feed_cost"))
    real_feed_rate = _div(real_feed_cost, actual_feed_consumed) if real_feed_cost else std_feed_rate
    real_chick_cost = _d(mbc.get("chick_cost"))
    real_chick_rate = _div(real_chick_cost, placed) if placed else ZERO
    # Unconditionally real, the same as feed and chicks above, and the same as
    # Farmer's own medicine line a few lines up — neither is gated behind the
    # scheme's medicine_cost_basis, which answers a settlement question (is
    # the farmer *billed* on real consumption or the flat rate), not "what did
    # medicine actually cost this flock". Both realization columns show that
    # regardless of how the scheme is configured to settle.
    #
    # Divided by chicks placed, not medicine consumed — "Medicine Cost" is a
    # ₹/bird figure everywhere else in this table (see Farmer's own version,
    # a few lines up, and Standard's), and medicine quantity is measured in
    # whatever unit that item uses (ml, doses, tablets), not birds. Dividing
    # the real spend by a non-bird quantity would answer "what did a unit of
    # medicine cost", not "what did medicine cost per bird" — a different
    # question from the one this column is asking everywhere else in the row.
    real_med_cost = _d(mbc.get("med_cost"))
    real_med_rate = _div(real_med_cost, placed) if placed else ZERO

    management = _cost_column(
        chick_qty=placed, chick_rate=real_chick_rate, chick_amount=real_chick_cost,
        feed_qty=actual_feed_consumed, feed_rate=real_feed_rate,
        feed_amount=real_feed_cost if real_feed_cost else None,
        med_qty=placed, med_rate=real_med_rate, med_amount=real_med_cost,
        admin_qty=placed, admin_rate=std_admin_rate,
        birds_sold=actual_survivors, live_weight=actual_live_weight,
    )

    # The weight each column's growing charge is actually earned on. Set here,
    # before the settlement loop below reads it.
    standard["delivered_weight"] = standard_delivered
    farmer["delivered_weight"] = actual_delivered
    management["delivered_weight"] = actual_delivered

    # --- GC rate / penalty-incentive, reusing the settlement's own engine ---
    # std_cost is the scheme's own master figure (bc["std_prod_per_kg"]), the
    # exact baseline GrowingChargeSettlement itself uses — not this report's
    # own Standard column total, which can legitimately differ from it (the
    # master figure is a separately-entered number, not derived from the
    # chick/feed/medicine/admin breakdown).
    std_cost_ref = _d(bc.get("std_prod_per_kg"))
    base_gc_rate = _d(bc.get("base_gc_rate"))
    # Standard Prod Cost means something different per column, not one figure
    # repeated three times:
    #  - Standard shows its own production_cost_per_kg — the hypothetical
    #    build-up of *this* column's chick/feed/medicine/admin, not the
    #    scheme's separate master field (which can legitimately disagree with
    #    what those add up to).
    #  - Farmer shows the scheme's own master figure (std_cost_ref /
    #    bc["std_prod_per_kg"]) — the fixed promise the farmer is measured
    #    against, i.e. it genuinely comes "from the schema" here.
    #  - Management shows nothing. It is set below, deliberately, along with
    #    Diff from Std Cost and Penalty/Incentive: the farmer is settled once,
    #    on the Farmer basis, so there is no management-basis promise for this
    #    column to be measured against. (An earlier draft of this comment said
    #    Management showed mbc["production_cost_per_kg"] here; it never did,
    #    and the block that blanks it explains why.)
    if has_scheme:
        standard["std_prod_per_kg"] = standard["production_cost_per_kg"]
        farmer["std_prod_per_kg"] = std_cost_ref
    else:
        standard["std_prod_per_kg"] = farmer["std_prod_per_kg"] = None
    for column in (standard, farmer):
        # Fed this column's own Standard Prod Cost, not the single scheme
        # master figure every column used to share — Standard's slab lookup
        # has to compare its own build-up against itself too, the same
        # baseline Diff from Std Cost uses below, or the two would disagree
        # about whether Standard is "at standard" (Diff reads 0 while the
        # slab engine, fed a genuinely different number, produces a nonzero
        # Penalty/Incentive for a row that never deviated from its own promise).
        gc_rate = _actual_gc_rate(scheme, column["std_prod_per_kg"], column["production_cost_per_kg"],
                                  base_gc_rate) if has_scheme else ZERO
        column["base_gc_rate"] = base_gc_rate
        # Standard minus Actual, not the other way round — negative reads as
        # "cost overrun" (unfavourable), positive as "came in under standard",
        # matching the sign Penalty/Incentive already carries.
        column["diff_from_std_cost"] = (column["std_prod_per_kg"] - column["production_cost_per_kg"]).quantize(Q2) \
            if has_scheme else ZERO
        column["penalty_incentive"] = (gc_rate - base_gc_rate).quantize(Q4)
        column["actual_gc_rate"] = gc_rate.quantize(Q4)
        # Earned on delivered weight, not on the whole flock. The growing
        # charge is paid for birds handed over; a bird still in the shed has
        # not been grown to completion and nothing is owed on it yet. That is
        # a different weight from the one the cost ratios divide by — those
        # measure what has been *spent*, which covers every bird alive.
        #
        # Standard has no unsold remainder by construction (it rears exactly
        # what it sells), so its two weights are the same figure.
        column["farmer_gc_income_payable"] = (
            gc_rate * column["delivered_weight"]).quantize(Q2)

    # Management has no growing charge settlement of its own to compute — the
    # farmer is paid once, on the Farmer basis, regardless of which costing
    # lens the company is looking at its own numbers through. Management
    # mirrors Farmer's Actual GC Rate and Farmer GC Income Payable for
    # reference rather than running a second, spurious settlement against its
    # own real production cost — and Standard Prod Cost / Diff from Std Cost /
    # Penalty-Incentive stay blank here for the same reason: there is no
    # "management basis" promise to measure this column against.
    management["base_gc_rate"] = base_gc_rate
    management["std_prod_per_kg"] = None
    management["diff_from_std_cost"] = None
    management["penalty_incentive"] = None
    management["actual_gc_rate"] = farmer["actual_gc_rate"]
    management["farmer_gc_income_payable"] = farmer["farmer_gc_income_payable"]

    # --- The rest of the scheme's own incentive/decentive slabs ------------
    # Sales/Mortality/FCR/Summer Incentives and the Mortality/FCR-Recovery
    # Decentives — every incentive/decentive band on the Growing Charge
    # master besides the Production-Cost one already broken out above as
    # Actual GC Rate / PC Incentive-Decentive. These come straight from
    # broiler.views._gc_settlement_autofill — the exact function
    # GrowingChargeSettlement itself defaults its own fields from — reused
    # rather than reimplemented, so this table can never disagree with what
    # a real settlement would actually compute.
    #
    # One real settlement, shown on both realization columns: like Actual GC
    # Rate above, these are settled once on the Farmer basis regardless of
    # which costing lens is being read, so Management mirrors Farmer instead
    # of running its own. Standard has no settlement of its own to draw
    # from — these slabs are keyed on the flock's real mortality/CFCR/sale
    # rate/production cost, not a hypothetical one this module could invent.
    if has_scheme:
        settlement = _gc_settlement_autofill(batch, scheme, report=report)
        for column in (farmer, management):
            column["sales_incentive"] = settlement["sales_incentives"].quantize(Q2)
            column["mortality_incentive"] = settlement["mortality_incentives"].quantize(Q2)
            column["fcr_incentive"] = settlement["fcr_incentives"].quantize(Q2)
            column["summer_incentive"] = settlement["summer_incentives"].quantize(Q2)
            column["mortality_decentive"] = settlement["mortality_deduction"].quantize(Q2)
            column["fcr_recovery_decentive"] = settlement["fcr_deduction"].quantize(Q2)
    else:
        for column in (farmer, management):
            column["sales_incentive"] = column["mortality_incentive"] = column["fcr_incentive"] = None
            column["summer_incentive"] = column["mortality_decentive"] = column["fcr_recovery_decentive"] = None
    for key in ("sales_incentive", "mortality_incentive", "fcr_incentive",
               "summer_incentive", "mortality_decentive", "fcr_recovery_decentive"):
        standard[key] = None

    # --- market price / revenue / profit ------------------------------------
    # Standard has no sale of its own to price from — it is charged at the
    # break-even the master implies: what the standard cost would need to sell
    # for to clear the standard growing-charge margin. Farmer and Management
    # share the one real sale this flock actually had.
    standard["market_price"] = (std_cost_ref + base_gc_rate).quantize(Q4) if has_scheme else ZERO
    farmer["market_price"] = actual_avg_sale_rate
    management["market_price"] = actual_avg_sale_rate

    # What each row's own real production cost would need to sell at to clear
    # the Base GC Rate margin — the same break-even Standard's own Market
    # Price already is, extended to Farmer/Management so their real sale rate
    # (Market Price, just above) can be read against it directly. Fed each
    # column's own production_cost_per_kg rather than the shared master
    # figure std_cost_ref uses, the same distinction Standard Prod Cost draws
    # elsewhere in this row.
    for column in (standard, farmer, management):
        column["breakeven_sale_rate"] = (column["production_cost_per_kg"] + column["base_gc_rate"]).quantize(Q4) \
            if has_scheme else None

    for column in (standard, farmer, management):
        column["total_market_revenue"] = (column["market_price"] * column["live_weight"]).quantize(Q2)
        column["market_sale_profit"] = (column["total_market_revenue"]
                                        - column["total_production_cost"]).quantize(Q2)
        column["profit_per_kg"] = _div(column["market_sale_profit"], column["live_weight"])
        column["profit_per_bird"] = _div(column["market_sale_profit"], column["birds_sold"])

    for column in (standard, farmer, management):
        # What the company actually keeps: the market sale profit after
        # paying out the growing charge it owes the farmer for this column's
        # own live weight — not a comparison against the Standard scenario.
        column["total_company_revenue"] = (column["market_sale_profit"]
                                           - column["farmer_gc_income_payable"]).quantize(Q2)

    def scenario(key, label, column, mort_pct, mort_no, avg_weight, feed_consumed):
        # placement_date, current_age and gap_days are the same physical
        # batch under every costing lens, so they come from the enclosing
        # scope rather than being threaded through each of the three calls
        # below. Actual Medicine Cost stays blank for Standard specifically —
        # that column reports real spend, and Standard is fully hypothetical,
        # so placed x flat rate (what column["med_amount"] would otherwise
        # show here) is not an "actual" figure however the arithmetic reads.
        # Blank on Standard because that column is hypothetical and has no
        # actual spend to report. Everywhere else the real figure stands, zero
        # included: on this table a blank means "no figure to give" and 0.00
        # means "nil", and a flock that genuinely bought no medicine was
        # saying the spend was unknown.
        actual_med = None if key == "standard" else column["med_amount"]
        values = _row(column, placed, mort_pct, mort_no, avg_weight, feed_consumed,
                     has_scheme, placement_date, current_age, gap_days, actual_med)
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
        "scheme_id": scheme.id if scheme else None,
        "standard_medicine_cost": std_med_rate,
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


def _available_birds(placed, mort_no, birds_sold):
    """Birds still on the farm: placed, less those lost, less those lifted.

    Never negative — a flock whose recorded sales exceed what its entries say
    survived is a data problem to fix, not a negative head count to display.
    """
    return max(_d(placed) - _d(mort_no) - _d(birds_sold), ZERO)


def _row(column, placed, mort_pct, mort_no, avg_weight, feed_consumed, has_scheme,
         placement_date, age, gap_days, actual_medicine_cost):
    """Flatten one column into the particular-keyed dict the template reads."""
    # Standard sells everything it rears, so nothing is left standing there and
    # its whole live weight is sold weight.
    available_birds = _available_birds(placed, mort_no, column["birds_sold"])
    available_weight = (available_birds * _d(avg_weight)).quantize(Q2)
    return {
        "placement_date": placement_date,
        "age": age,
        "gap_days": gap_days,
        "chicks_placed": placed,
        "chick_cost_rate": column["chick_rate"],
        "feed_cost_rate": column["feed_rate"],
        "standard_fcr": _div(column["feed_qty"], column["live_weight"], Decimal("0.0001")),
        "medicine_cost_rate": column["med_rate"],
        "actual_medicine_cost": actual_medicine_cost,
        "actual_feed_consumption": feed_consumed,
        "admin_cost_rate": column["admin_rate"],
        "free_mortality_pct": mort_pct,
        "mortality_no": mort_no,
        "avg_live_weight": avg_weight,
        "market_price": column["market_price"],
        "breakeven_sale_rate": column["breakeven_sale_rate"],
        "base_gc_rate": column["base_gc_rate"],
        "birds_sold": column["birds_sold"],
        # What went over a weighbridge, what is still standing, and the two
        # together — the live weight this flock has produced so far, which is
        # what every ratio below and the whole breakeven / GC-payable chain
        # now divide by.
        #
        # Cost and feed were spent on the birds that left and the birds still
        # here alike, so measuring either against the sold weight alone
        # overstates it on a flock mid-lift. A fully sold flock is unaffected:
        # nothing is standing, so the total is the sold weight it always was.
        "sold_weight": (column["live_weight"] - available_weight).quantize(Q2),
        "available_birds": available_birds,
        "available_weight": available_weight,
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
        "std_prod_per_kg": column["std_prod_per_kg"],
        "diff_from_std_cost": column["diff_from_std_cost"],
        "penalty_incentive": column["penalty_incentive"],
        "actual_gc_rate": column["actual_gc_rate"],
        "sales_incentive": column["sales_incentive"],
        "mortality_incentive": column["mortality_incentive"],
        "fcr_incentive": column["fcr_incentive"],
        "summer_incentive": column["summer_incentive"],
        "mortality_decentive": column["mortality_decentive"],
        "fcr_recovery_decentive": column["fcr_recovery_decentive"],
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
    ("placement_date", "Placement Date", "", "date"),
    ("age", "Age", "days", 0),
    ("gap_days", "Entry Gap Days", "days", 0),
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
    ("breakeven_sale_rate", "Breakeven Sale Rate", "₹/kg", 4),
    ("base_gc_rate", "Base GC Rate", "₹/kg", 2),
    ("std_prod_per_kg", "Standard Prod Cost", "₹/kg", 2),
    ("birds_sold", "Birds Sold", "", 0),
    ("sold_weight", "Sold Weight", "kg", 2),
    ("available_birds", "Available Birds", "", 0),
    ("available_weight", "Available Weight", "kg", 2),
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
    ("penalty_incentive", "PC Incentive/Decentive", "₹/kg", 4),
    ("actual_gc_rate", "Actual GC Rate", "₹/kg", 4),
    ("sales_incentive", "Sales Incentive", "₹", 2),
    ("mortality_incentive", "Mortality Incentive", "₹", 2),
    ("fcr_incentive", "FCR Incentive", "₹", 2),
    ("summer_incentive", "Summer Incentive", "₹", 2),
    ("mortality_decentive", "Mortality Decentive", "₹", 2),
    ("fcr_recovery_decentive", "FCR Recovery Decentive", "₹", 2),
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
    "mortality_no", "birds_sold", "sold_weight", "available_birds",
    "available_weight", "total_live_weight", "total_feed_required",
    "total_feed_cost", "total_chick_cost", "total_medicine_cost",
    "total_admin_cost", "total_production_cost", "farmer_gc_income_payable",
    "sales_incentive", "mortality_incentive", "fcr_incentive", "summer_incentive",
    "mortality_decentive", "fcr_recovery_decentive",
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


def build_gc_realization_grid(batches, scheme_override_id=None):
    """The multi-farm listing: one Standard/Farmer/Management triplet per
    batch, and a Total row summing the additive columns across all of them.

    ``batches`` is an iterable of ``BroilerBatch``, already scoped and ordered
    by the caller — data-scoping and "which batches belong on this report" are
    the view's job, the same division every other report in this module keeps.

    ``scheme_override_id``, when given, is the filter bar's own "Schema"
    dropdown, hand-picked the same way the Batch History Report's Schema
    dropdown already overrides ``_match_growing_charge_scheme``'s pick (see
    that view's own comment). It is *not* a filter on each batch's own
    auto-match winner: two schemes can legitimately overlap the same branch
    and date range (e.g. a region's general scheme and a "Summer" scheme both
    covering April-July), and ``_match_growing_charge_scheme`` only ever
    surfaces one of them per batch — the other would never be selectable at
    all if this only kept batches that already "won" the auto-match. Instead,
    a batch is included whenever the picked scheme's own region/branch/date
    range actually covers it (the same test ``_match_growing_charge_scheme``
    itself applies before ranking), and is then costed under that scheme
    specifically, replacing whatever it would have auto-matched to.
    """
    from broiler.views import _build_batch_report, _match_growing_charge_scheme, _placement_date

    override_scheme = None
    if scheme_override_id:
        from broiler.models import GrowingChargeScheme
        override_scheme = GrowingChargeScheme.objects.filter(id=scheme_override_id).first()

    groups = []
    for batch in batches:
        placement = _placement_date(batch)
        if override_scheme:
            branch = batch.broiler_farm.branch
            eligible = (placement is not None
                       and override_scheme.region_id == branch.region_id
                       and override_scheme.from_date <= placement <= override_scheme.to_date
                       and (override_scheme.branch_id is None or override_scheme.branch_id == branch.id))
            if not eligible:
                continue
            scheme = override_scheme
        else:
            scheme = _match_growing_charge_scheme(batch, placement)
        report = _build_batch_report(batch, fetch_type="farmer", scheme_override=scheme)
        # A second pass at the same batch, this time asking for the
        # management-basis costing — which is what now carries feed/chick/
        # medicine priced through the real valuation engine (see
        # broiler.views._build_batch_costing) rather than a rate this module
        # would otherwise have to work out a second, different way.
        management_report = _build_batch_report(batch, fetch_type="management", scheme_override=scheme)
        result = build_gc_realization(batch, report, management_report, scheme)
        groups.append({
            "farm_name": batch.broiler_farm.farm_name,
            "batch_name": batch.batch_name,
            "batch_id": batch.pk,
            "has_scheme": result["has_scheme"],
            "scenarios": result["scenarios"],
            # For the Standard row's inline-editable Medicine Cost cell — the
            # value edited there lives on the scheme, not the batch, so every
            # batch sharing one scheme shows (and edits) the same number.
            "scheme_id": result["scheme_id"],
            "scheme_code": result["scheme_code"],
            "standard_medicine_cost": result["standard_medicine_cost"],
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
    """``values`` (a particular-keyed dict) as an ordered list of
    ``{"key": ..., "text": ...}`` dicts, one per :data:`PARTICULARS` entry, in
    that exact order.

    Built here rather than looked up by key in the template: Django templates
    have no built-in "index a dict by a loop variable" operation, and this
    project's own template-tag library for that (``broiler_extras``) no
    longer has a source file behind it — nothing to extend safely. An ordered
    list the template can simply iterate needs no such lookup at all, and
    keeps the per-particular decimal formatting in one place instead of
    scattered across template filters.

    A dict per cell rather than a bare string so the template can pick one out
    by its ``key`` — the Standard row's Medicine Cost cell renders as an
    editable field instead of plain text, and a plain list would give the
    template nothing to match against.
    """
    cells = []
    for key, _label, _unit, places in PARTICULARS:
        value = values.get(key)
        if value is None:
            text = "—"
        elif places == "date":
            text = value.strftime("%d.%m.%Y")
        elif places == 0:
            text = f"{int(value):,}"
        else:
            text = f"{Decimal(str(value)):,.{places}f}"
        cells.append({"key": key, "text": text})
    return cells
