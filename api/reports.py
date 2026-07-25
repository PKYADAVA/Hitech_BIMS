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
from broiler.models import BroilerBatch, DailyEntry
from hatchery.models import EggPurchase, EggPurchaseItem, HatchEntry


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
