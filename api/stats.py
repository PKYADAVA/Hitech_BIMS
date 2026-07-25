"""Dashboard stats — one aggregated call powering the mobile Home KPIs + trend.

Kept deliberately cheap: a handful of indexed COUNT/SUM queries, no per-row
Python. Returns today's headline numbers for each module plus a 7-day mortality
trend for the Home chart.
"""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.viewsets import V1ViewMixin
from broiler.models import BroilerBatch, BroilerFarm, DailyEntry
from hatchery.models import EggPurchase, HatchEntry
from notification.models import SmsMessage

_OK = ["sent", "delivered", "mocked"]
_FAIL = ["failed", "rejected", "expired", "invalid"]


class StatsOverviewView(V1ViewMixin, APIView):
    """GET /api/v1/stats/overview — headline KPIs + a 7-day mortality trend."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        today = timezone.localdate()
        days = [today - timedelta(days=i) for i in range(6, -1, -1)]  # oldest → today

        de_today = DailyEntry.objects.filter(date=today)
        mort_by_day = {d: 0 for d in days}
        for r in (
            DailyEntry.objects.filter(date__gte=days[0])
            .values("date")
            .annotate(m=Sum("mortality"))
        ):
            if r["date"] in mort_by_day:
                mort_by_day[r["date"]] = int(r["m"] or 0)

        broiler = {
            "entries_today": de_today.count(),
            "mortality_today": int(de_today.aggregate(s=Sum("mortality"))["s"] or 0),
            "active_batches": BroilerBatch.objects.filter(is_closed=False).count(),
            "farms": BroilerFarm.objects.count(),
            "mortality_7d": [
                {"label": d.strftime("%a"), "value": mort_by_day[d]} for d in days
            ],
        }

        hatch_today = HatchEntry.objects.filter(hatch_date=today)
        hatchery = {
            "egg_purchases_today": EggPurchase.objects.filter(date=today).count(),
            "hatch_entries_today": hatch_today.count(),
            "chicks_today": int(hatch_today.aggregate(s=Sum("chicks_total"))["s"] or 0),
        }

        sms_today = SmsMessage.objects.filter(created_at__date=today)
        sms = {
            "total_today": sms_today.count(),
            "sent_today": sms_today.filter(status__in=_OK).count(),
            "failed_today": sms_today.filter(status__in=_FAIL).count(),
        }

        return Response({"date": str(today), "broiler": broiler, "hatchery": hatchery, "sms": sms})
