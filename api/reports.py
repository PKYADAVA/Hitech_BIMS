"""Mobile report endpoints.

Each returns the same generic shape so one mobile screen renders any report::

    { "generated": "2026-07-25",
      "totals": { "<label>": <number>, ... },
      "rows":   [ { "<field>": <value>, ... }, ... ] }
"""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Sum
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.viewsets import V1ViewMixin
from broiler.models import BirdSale, BroilerBatch, DailyEntry
from hatchery.models import (
    ChickSale,
    DeliveryChallan,
    EggPurchase,
    EggPurchaseItem,
    HatchEntry,
    TraySetting,
)
from inventory.models import StockTransfer


def _f(x) -> float:
    """Decimal/None → rounded float for JSON."""
    return round(float(x or 0), 2)


def _i(x) -> int:
    """Decimal/None → int for JSON (birds, eggs, chicks…)."""
    return int(float(x or 0))


class LiveFlockReportView(V1ViewMixin, APIView):
    """GET /reports/live-flock — one row per open batch with running aggregates."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        today = timezone.localdate()
        # Select only the columns we need (avoids depending on every model column
        # being migrated locally, e.g. a newly-added FK not yet migrated).
        batches = BroilerBatch.objects.filter(is_closed=False).values(
            "id", "batch_name", "lot_no", "start_date",
            "broiler_farm__farm_name", "broiler_farm__farm_code",
        )

        rows = []
        for b in batches:
            bid = b["id"]
            agg = DailyEntry.objects.filter(batch_id=bid).aggregate(
                mort=Sum("mortality"),
                culls=Sum("culls"),
                f1=Sum("feed_1_qty"),
                f2=Sum("feed_2_qty"),
                n=Count("id"),
            )
            latest = (
                DailyEntry.objects.filter(batch_id=bid)
                .order_by("-date", "-id")
                .values_list("avg_weight_gms", flat=True)
                .first()
            )
            start = b["start_date"]
            rows.append({
                "batch": b["batch_name"] or f"Batch #{bid}",
                "farm": b["broiler_farm__farm_name"] or b["broiler_farm__farm_code"] or "—",
                "age_days": (today - start).days if start else None,
                "entries": agg["n"] or 0,
                "mortality": int(agg["mort"] or 0),
                "culls": int(agg["culls"] or 0),
                "feed_qty": round(float((agg["f1"] or 0) + (agg["f2"] or 0)), 2),
                "avg_weight_g": round(float(latest), 1) if latest is not None else None,
            })

        totals = {
            "Open batches": len(rows),
            "Mortality": sum(r["mortality"] for r in rows),
            "Culls": sum(r["culls"] for r in rows),
        }
        return Response({"generated": str(today), "totals": totals, "rows": rows})


class HatchPerformanceReportView(V1ViewMixin, APIView):
    """GET /reports/hatch-performance — recent hatches with egg→chick yield."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = (
            HatchEntry.objects.order_by("-hatch_date", "-id")
            .values("transaction_no", "hatch_date", "eggs_total", "chicks_total")[:100]
        )
        rows = []
        total_eggs = 0.0
        total_chicks = 0.0
        for e in qs:
            eggs = float(e["eggs_total"] or 0)
            chicks = float(e["chicks_total"] or 0)
            total_eggs += eggs
            total_chicks += chicks
            rows.append({
                "hatch": e["transaction_no"] or "—",
                "hatch_date": str(e["hatch_date"]) if e["hatch_date"] else "",
                "eggs": int(eggs),
                "chicks": int(chicks),
                "hatch_pct": round(chicks / eggs * 100, 1) if eggs else None,
            })

        totals = {
            "Hatches": len(rows),
            "Eggs": int(total_eggs),
            "Chicks": int(total_chicks),
            "Hatch %": round(total_chicks / total_eggs * 100, 1) if total_eggs else 0,
        }
        return Response({"generated": str(timezone.localdate()), "totals": totals, "rows": rows})


class MortalityTrendReportView(V1ViewMixin, APIView):
    """GET /reports/mortality-trend — daily mortality/culls across all batches (30d)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        today = timezone.localdate()
        start = today - timedelta(days=29)
        agg = (
            DailyEntry.objects.filter(date__gte=start)
            .values("date")
            .annotate(m=Sum("mortality"), c=Sum("culls"), n=Count("id"))
            .order_by("-date")
        )
        rows = [
            {
                "date": str(r["date"]),
                "mortality": int(r["m"] or 0),
                "culls": int(r["c"] or 0),
                "entries": r["n"],
            }
            for r in agg
        ]
        totals = {
            "Days": len(rows),
            "Mortality": sum(r["mortality"] for r in rows),
            "Culls": sum(r["culls"] for r in rows),
        }
        return Response({"generated": str(today), "totals": totals, "rows": rows})


class EggIntakeReportView(V1ViewMixin, APIView):
    """GET /reports/egg-intake — recent egg purchases with received quantity."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        purchases = list(
            EggPurchase.objects.order_by("-date", "-id")
            .values("id", "transaction_no", "date", "supplier__name")[:100]
        )
        rows = []
        total_recv = 0.0
        for p in purchases:
            it = EggPurchaseItem.objects.filter(egg_purchase_id=p["id"]).aggregate(
                recv=Sum("rcv_qty"), boxes=Sum("no_of_boxes"), amt=Sum("total_amount")
            )
            recv = float(it["recv"] or 0)
            total_recv += recv
            rows.append({
                "purchase": p["transaction_no"] or f"#{p['id']}",
                "date": str(p["date"]) if p["date"] else "",
                "supplier": p["supplier__name"] or "—",
                "received": int(recv),
                "boxes": int(float(it["boxes"] or 0)),
                "amount": round(float(it["amt"] or 0), 2),
            })
        totals = {"Purchases": len(rows), "Eggs received": int(total_recv)}
        return Response({"generated": str(timezone.localdate()), "totals": totals, "rows": rows})


# --------------------------------------------------------------------------- #
# Broiler — mobile snapshots of the web Reports tab (recent rows + totals).    #
# --------------------------------------------------------------------------- #
class BatchSummaryReportView(V1ViewMixin, APIView):
    """GET /reports/batch-summary — every batch (open + closed) with running
    mortality/culls/feed and latest body weight (web: Batch History Report)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        today = timezone.localdate()
        batches = list(
            BroilerBatch.objects.order_by("-start_date", "-id").values(
                "id", "batch_name", "start_date", "is_closed",
                "broiler_farm__farm_name", "broiler_farm__farm_code",
            )[:100]
        )
        rows = []
        for b in batches:
            agg = DailyEntry.objects.filter(batch_id=b["id"]).aggregate(
                mort=Sum("mortality"), culls=Sum("culls"),
                f1=Sum("feed_1_qty"), f2=Sum("feed_2_qty"),
            )
            latest = (
                DailyEntry.objects.filter(batch_id=b["id"])
                .order_by("-date", "-id").values_list("avg_weight_gms", flat=True).first()
            )
            start = b["start_date"]
            rows.append({
                "batch": b["batch_name"] or f"Batch #{b['id']}",
                "farm": b["broiler_farm__farm_name"] or b["broiler_farm__farm_code"] or "—",
                "status": "Closed" if b["is_closed"] else "Open",
                "age_days": (today - start).days if start and not b["is_closed"] else None,
                "mortality": _i(agg["mort"]),
                "culls": _i(agg["culls"]),
                "feed_qty": _f((agg["f1"] or 0) + (agg["f2"] or 0)),
                "avg_weight_g": round(float(latest), 1) if latest is not None else None,
            })
        totals = {
            "Batches": len(rows),
            "Open": sum(1 for r in rows if r["status"] == "Open"),
            "Mortality": sum(r["mortality"] for r in rows),
        }
        return Response({"generated": str(today), "totals": totals, "rows": rows})


class ChicksPlacementReportView(V1ViewMixin, APIView):
    """GET /reports/chicks-placement — chick placements (warehouse→farm stock
    transfers of a chicks-category item) with ordered/received/loss + amount."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = (
            StockTransfer.objects
            .filter(to_location_type="farm", item__category__name__icontains="chick")
            .select_related("to_farm", "to_batch", "source_hatchery")
            .order_by("-date", "-id")[:100]
        )
        rows, t_ord, t_recv, t_mort = [], 0, 0, 0
        for t in qs:
            ordered = _i(t.chicks_ordered)
            received = _i(t.quantity)
            mortality = _i(t.transit_mortality)
            t_ord += ordered
            t_recv += received
            t_mort += mortality
            rows.append({
                "placement": t.trnum or f"#{t.id}",
                "date": str(t.date) if t.date else "",
                "farm": t.to_farm.farm_name if t.to_farm_id else "—",
                "batch": t.to_batch.batch_name if t.to_batch_id else "—",
                "hatchery": t.source_hatchery.hatchery_name if t.source_hatchery_id else "—",
                "ordered": ordered,
                "received": received,
                "transit_mortality": mortality,
                "culls": _i(t.culls),
                "amount": _f(_f(t.quantity) * _f(t.rate)),
            })
        totals = {"Placements": len(rows), "Ordered": t_ord, "Received": t_recv, "Transit mortality": t_mort}
        return Response({"generated": str(timezone.localdate()), "totals": totals, "rows": rows})


class FeedDispatchReportView(V1ViewMixin, APIView):
    """GET /reports/feed-dispatch — recent feed-item stock movements (dispatch/
    return) with bag quantity (web: Feed Dispatch & Stock Report, simplified)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = (
            StockTransfer.objects
            .filter(item__category__name__icontains="feed")
            .select_related("from_warehouse", "to_farm", "to_warehouse", "item")
            .order_by("-date", "-id")[:100]
        )
        rows, total_bags = [], 0.0
        for t in qs:
            bags = _f(t.quantity)
            total_bags += bags
            dest = (
                t.to_farm.farm_name if t.to_farm_id
                else t.to_warehouse.name if t.to_warehouse_id else "—"
            )
            rows.append({
                "transfer": t.trnum or f"#{t.id}",
                "date": str(t.date) if t.date else "",
                "item": (t.item.description or t.item.item_code) if t.item_id else "—",
                "from": t.from_warehouse.name if t.from_warehouse_id else "—",
                "to": dest,
                "bags": bags,
                "dc_no": t.dc_no or "",
            })
        totals = {"Movements": len(rows), "Total bags": round(total_bags, 2)}
        return Response({"generated": str(timezone.localdate()), "totals": totals, "rows": rows})


class DayRecordReportView(V1ViewMixin, APIView):
    """GET /reports/day-record — one row per daily entry on the most recent day
    that has entries: mortality/culls/feed consumed/body weight per farm+batch."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        sel_date = (
            DailyEntry.objects.order_by("-date").values_list("date", flat=True).first()
            or timezone.localdate()
        )
        entries = list(
            DailyEntry.objects.filter(date=sel_date).values(
                "farm__farm_name", "farm__farm_code", "batch__batch_name",
                "mortality", "culls", "feed_1_qty", "feed_2_qty", "avg_weight_gms",
            ).order_by("farm__farm_code")
        )
        rows = []
        for e in entries:
            rows.append({
                "farm": e["farm__farm_name"] or e["farm__farm_code"] or "—",
                "batch": e["batch__batch_name"] or "—",
                "mortality": _i(e["mortality"]),
                "culls": _i(e["culls"]),
                "feed_kg": _f((e["feed_1_qty"] or 0) + (e["feed_2_qty"] or 0)),
                "avg_weight_g": _f(e["avg_weight_gms"]) if e["avg_weight_gms"] is not None else None,
            })
        totals = {
            "Entries": len(rows),
            "Mortality": sum(r["mortality"] for r in rows),
            "Culls": sum(r["culls"] for r in rows),
            "Feed (kg)": round(sum(r["feed_kg"] for r in rows), 2),
        }
        return Response({"generated": str(sel_date), "totals": totals, "rows": rows})


class LiftingReportView(V1ViewMixin, APIView):
    """GET /reports/lifting — register of recent bird sales (liftings): party,
    birds, weight, rate and amount (web: Lifting Report, simplified)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = (
            BirdSale.objects.select_related("customer", "farmer")
            .order_by("-date", "-id")[:100]
        )
        rows, t_birds, t_wt, t_amt = [], 0, 0.0, 0.0
        for s in qs:
            party = (
                s.customer.name if s.customer_id
                else s.farmer.farmer_name if s.farmer_id else "—"
            )
            birds = _i(s.birds)
            weight = _f(s.net_weight)
            amount = _f(s.amount)
            t_birds += birds
            t_wt += weight
            t_amt += amount
            rows.append({
                "sale_no": s.sale_no or f"#{s.id}",
                "date": str(s.date) if s.date else "",
                "party": party,
                "type": s.sale_type or "",
                "birds": birds,
                "weight": weight,
                "avg_weight": _f(s.avg_weight),
                "rate": _f(s.rate),
                "amount": amount,
            })
        totals = {
            "Liftings": len(rows),
            "Birds": t_birds,
            "Weight": round(t_wt, 2),
            "Amount": round(t_amt, 2),
        }
        return Response({"generated": str(timezone.localdate()), "totals": totals, "rows": rows})


# --------------------------------------------------------------------------- #
# Hatchery — mobile snapshots of the web Reports tab.                          #
# --------------------------------------------------------------------------- #
class IncubationReportView(V1ViewMixin, APIView):
    """GET /reports/incubation — grading → tray setting → hatch outcome, one row
    per tray setting (eggs set, saleable chicks, hatch %, net cost)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = (
            TraySetting.objects
            .select_related("hatchery", "grading__supplier", "grading__item")
            .order_by("-setting_date", "-id")[:100]
        )
        rows, t_eggs, t_chicks = [], 0, 0
        for ts in qs:
            g = ts.grading
            try:
                he = ts.hatch_entry
            except HatchEntry.DoesNotExist:
                he = None
            eggs_set = _i(ts.total_eggs_set())
            saleable = _i(he.chicks_total) if he else 0
            t_eggs += eggs_set
            t_chicks += saleable
            rows.append({
                "setting_no": ts.setting_no or "—",
                "setting_date": str(ts.setting_date) if ts.setting_date else "",
                "hatchery": ts.hatchery.hatchery_name if ts.hatchery_id else "—",
                "supplier": g.supplier.name if g and g.supplier_id else "—",
                "eggs_set": eggs_set,
                "saleable_chicks": saleable,
                "hatch_pct": round(saleable / eggs_set * 100, 1) if eggs_set else None,
                "net_cost": _f(he.net_amount) if he else 0,
            })
        totals = {
            "Settings": len(rows),
            "Eggs set": t_eggs,
            "Saleable chicks": t_chicks,
            "Hatch %": round(t_chicks / t_eggs * 100, 1) if t_eggs else 0,
        }
        return Response({"generated": str(timezone.localdate()), "totals": totals, "rows": rows})


class DeliveryChallanReportView(V1ViewMixin, APIView):
    """GET /reports/delivery-challan — recent chick delivery challans with units,
    quantity, tax and amount."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = (
            DeliveryChallan.objects.select_related("customer")
            .prefetch_related("items", "chick_sales")
            .order_by("-date", "-id")[:100]
        )
        rows, t_qty, t_amt = [], 0.0, 0.0
        for dc in qs:
            units = sum((float(r.units or 0) for r in dc.items.all()), 0.0)
            qty = _f(dc.total_quantity())
            amount = _f(dc.grand_total())
            t_qty += qty
            t_amt += amount
            rows.append({
                "challan_no": dc.challan_no or "—",
                "date": str(dc.date) if dc.date else "",
                "customer": dc.customer.name if dc.customer_id else "—",
                "vehicle": dc.vehicle_no or "",
                "units": round(units, 2),
                "quantity": qty,
                "tax": _f(dc.total_tax()),
                "amount": amount,
                "status": "Billed" if dc.chick_sales.all() else "Pending",
            })
        totals = {"Challans": len(rows), "Quantity": round(t_qty, 2), "Amount": round(t_amt, 2)}
        return Response({"generated": str(timezone.localdate()), "totals": totals, "rows": rows})


class ChickSaleReportView(V1ViewMixin, APIView):
    """GET /reports/chick-sale — chick sale invoices with quantities, rate,
    freight and final amount."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = (
            ChickSale.objects.select_related("customer")
            .prefetch_related("items")
            .order_by("-date", "-id")[:100]
        )
        rows, t_birds, t_amt = [], 0, 0.0
        for cs in qs:
            birds = _i(sum((r.sale_qty or 0) for r in cs.items.all()))
            final = _f(cs.final_amount)
            t_birds += birds
            t_amt += final
            rows.append({
                "bill_no": cs.bill_no or "—",
                "date": str(cs.date) if cs.date else "",
                "customer": cs.customer.name if cs.customer_id else "—",
                "birds": birds,
                "billed_qty": _f(cs.total_net_qty()),
                "avg_rate": _f(cs.avg_amount),
                "freight": _f(cs.freight_amount),
                "final_amount": final,
            })
        totals = {"Sales": len(rows), "Birds": t_birds, "Amount": round(t_amt, 2)}
        return Response({"generated": str(timezone.localdate()), "totals": totals, "rows": rows})
