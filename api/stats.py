"""Dashboard stats — one aggregated call powering the mobile Home KPIs + trend.

Kept deliberately cheap: a handful of indexed COUNT/SUM queries, no per-row
Python. Returns today's headline numbers for each module plus a 7-day mortality
trend for the Home chart.
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from account.models import ChartOfAccount, Voucher
from alerthub.models import NotificationRecipient
from api.viewsets import V1ViewMixin
from broiler.models import Branch, BroilerBatch, BroilerFarm, DailyEntry, Supervisor
from hatchery.models import EggPurchase, HatchEntry
from hr.models import SupervisorTripVisit
from purchase.models import GeneralPurchase
from sales.models import SalesInvoice
from user.services.scoping import (customers_for, farms_for, is_unscoped,
                                   suppliers_for, warehouses_for)
from inventory.models import Item, StockTransfer, Warehouse
from notification.models import SmsMessage

_OK = ["sent", "delivered", "mocked"]
_FAIL = ["failed", "rejected", "expired", "invalid"]


class StatsOverviewView(V1ViewMixin, APIView):
    """GET /api/v1/stats/overview — headline KPIs + a 7-day mortality trend."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        today = timezone.localdate()
        # An explicit day, so the phone can answer "what did yesterday look
        # like?" without a second screen — the same Date box the ERP's own
        # dashboard filter bar carries. A date that will not parse is ignored
        # rather than rejected: a half-typed dd-mm-yyyy should show today, not
        # an error.
        asked = parse_date((request.query_params.get("date") or "").strip() or "x")
        if asked and asked <= timezone.localdate():
            today = asked
        # Every figure below is the signed-in user's, not the company's. A
        # supervisor scoped to one branch was being shown the whole business's
        # placements, feed and flock counts — the same leak the web reports
        # had, one layer further out.
        farms = farms_for(request.user)
        # Kept before the narrowing below: the filter lists are built from it,
        # so each picker still offers everything the user could choose next.
        scope = farms

        # Branch, Line and Supervisor narrow which farms count, exactly as the
        # ERP's dashboard filter bar does. Applied to the *scoped* queryset, so
        # naming a branch in the query string can only ever narrow what the
        # user may already see — never widen it.
        for param, field in (("branch", "branch_id"),
                             ("line", "line"),
                             ("supervisor", "supervisor_id")):
            value = (request.query_params.get(param) or "").strip()
            if not value:
                continue
            if field.endswith("_id") and not value.isdigit():
                continue
            farms = farms.filter(**{field: value})

        farm_ids = list(farms.values_list("id", flat=True))

        # The dashboard's two filters. A farm named in the query string is
        # intersected with what the user may see rather than trusted — the
        # picker only offers their own farms, but the query string is not the
        # picker.
        chosen = (request.query_params.get("farm") or "").strip()
        if chosen.isdigit() and int(chosen) in farm_ids:
            farm_ids = [int(chosen)]

        # "Today" is the default; the others widen the window the day figures
        # cover, so the same panel answers "this week" without a second screen.
        period = (request.query_params.get("period") or "today").strip().lower()
        span = {"today": 1, "week": 7, "month": 30}.get(period, 1)
        since = today - timedelta(days=span - 1)
        days = [today - timedelta(days=i) for i in range(6, -1, -1)]  # oldest → today

        de_today = DailyEntry.objects.filter(date=today, farm_id__in=farm_ids)
        mort_by_day = {d: 0 for d in days}
        for r in (
            DailyEntry.objects.filter(date__gte=days[0], farm_id__in=farm_ids)
            .values("date")
            .annotate(m=Sum("mortality"))
        ):
            if r["date"] in mort_by_day:
                mort_by_day[r["date"]] = int(r["m"] or 0)

        broiler = {
            "entries_today": de_today.count(),
            "mortality_today": int(de_today.aggregate(s=Sum("mortality"))["s"] or 0),
            "active_batches": BroilerBatch.objects.filter(
                is_closed=False, broiler_farm_id__in=farm_ids).count(),
            "farms": len(farm_ids),
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

        inventory = {
            "items": Item.objects.count(),
            "transfers_today": StockTransfer.objects.filter(date=today).count(),
        }

        broiler.update(self._today_overview(today, farm_ids, since))

        visits_today = SupervisorTripVisit.objects.filter(
            checked_in_at__date=today, farm_id__in=farm_ids)
        visits = {
            "today": visits_today.count(),
            "completed": visits_today.filter(checked_out_at__isnull=False).count(),
            # Only what has actually been visited is "done"; a check-in with no
            # check-out is still in progress, not a completed visit.
            "rows": [
                {
                    "farm": v.farm.farm_name if v.farm_id else "",
                    "purpose": v.purpose or "",
                    "at": timezone.localtime(v.checked_in_at).strftime("%H:%M")
                          if v.checked_in_at else "",
                    "done": v.checked_out_at is not None,
                }
                for v in visits_today.select_related("farm")
                                     .order_by("checked_in_at")[:5]
            ],
        }

        # The ERP's own alert system, not the audit trail. alerts.Alert
        # records every model change — JWT tokens and permission rows included,
        # 1,690 of them unread and none of it news to a supervisor. alerthub is
        # the rule-driven one the ERP's bell and notification centre read, and
        # its notifications are addressed to particular users, so this is the
        # signed-in user's feed rather than everyone's.
        mine = (NotificationRecipient.objects
                .filter(user=request.user)
                .select_related("notification"))
        unread = mine.filter(is_read=False)
        alerts = {
            "pending": unread.count(),
            "high": unread.filter(
                notification__priority__in=["high", "critical"]).count(),
            "rows": [
                {
                    "title": r.notification.title,
                    "severity": r.notification.priority,
                    "at": timezone.localtime(r.notification.created_at).strftime("%H:%M"),
                }
                for r in unread.order_by("-notification__created_at")[:5]
            ],
        }

        # The counts the reference's System Summary strip shows.
        system = {
            "users": get_user_model().objects.filter(is_active=True).count(),
            "farms": len(farm_ids),
            "stores": warehouses_for(request.user).count(),
            "items": Item.objects.count(),
            "batches": BroilerBatch.objects.filter(
                is_closed=False, broiler_farm_id__in=farm_ids).count(),
        }

        # Purchase and Sales money, for the strips above those lists: what was
        # billed today and what has been billed this month. Scoped by the
        # party the user may see, the same rule their registers use.
        month_start = today.replace(day=1)

        def billed(model, party_field, allowed):
            qs = model.objects.filter(date__lte=today)
            if allowed is not None:
                qs = qs.filter(**{"%s__in" % party_field: allowed})
            return {
                "today": float(qs.filter(date=today)
                               .aggregate(s=Sum("net_amount"))["s"] or 0),
                "month": float(qs.filter(date__gte=month_start)
                               .aggregate(s=Sum("net_amount"))["s"] or 0),
            }

        suppliers = (None if is_unscoped(request.user)
                     else suppliers_for(request.user).values_list("id", flat=True))
        customers = (None if is_unscoped(request.user)
                     else customers_for(request.user).values_list("id", flat=True))
        purchase = billed(GeneralPurchase, "supplier_id", suppliers)
        sales = billed(SalesInvoice, "customer_id", customers)

        account = {
            "vouchers_today": Voucher.objects.filter(date=today).count(),
            "accounts": ChartOfAccount.objects.count(),
        }

        return Response({
            "date": str(today),
            "filters": {"farm": chosen if chosen.isdigit() else "",
                        "period": period if period in ("today", "week", "month") else "today"},
            # The pickers' options: only what this user may look at, and —
            # for farms — only what the *other* filters still leave standing,
            # so choosing a branch does not leave a farm from elsewhere on
            # offer. The branch, line and supervisor lists come off the user's
            # whole scope rather than the narrowed set, or picking one would
            # empty the list it was picked from.
            "farm_options": [{"id": f.id, "name": f.farm_name}
                             for f in farms.order_by("farm_name")[:200]],
            "branch_options": [{"id": b.id, "name": b.branch_name} for b in
                               Branch.objects.filter(
                                   id__in=scope.values_list("branch_id", flat=True))
                               .order_by("branch_name")[:200]],
            "line_options": [{"id": line, "name": line} for line in
                             scope.exclude(line="").exclude(line=None)
                             .values_list("line", flat=True).distinct()
                             .order_by("line")[:200]],
            "supervisor_options": [{"id": sv.id, "name": sv.name} for sv in
                                   Supervisor.objects.filter(
                                       id__in=scope.values_list("supervisor_id", flat=True))
                                   .order_by("name")[:200]],
            "broiler": broiler,
            "hatchery": hatchery,
            "sms": sms,
            "inventory": inventory,
            "account": account,
            "purchase": purchase,
            "sales": sales,
            "visits": visits,
            "alerts": alerts,
            "system": system,
        })

    @staticmethod
    def _today_overview(today, farm_ids, since=None):
        """The four figures the dashboard's Today's Overview panel shows.

        Mortality is a percentage of the birds actually alive, not a raw count:
        a hundred deaths means one thing across 5,000 birds and another across
        50,000, and the count alone is what the old payload offered.

        FCR uses the Live Flock Summary's definition, not a simpler one —
        feed consumed over the weight the flock is *carrying now*, which is the
        weight already sold plus the live weight still on the farm. Dropping
        the sold half, as a first cut of this did, overstates FCR on any batch
        that has started selling. See ``broiler.views.live_flock_summary_report``.
        """
        from broiler.models import BirdSale

        # `since` is the start of the chosen window — the same day as `today`
        # unless the user widened it to a week or a month.
        since = since or today
        entries_today = DailyEntry.objects.filter(date__gte=since, date__lte=today,
                                                  farm_id__in=farm_ids)
        feed_today = entries_today.aggregate(a=Sum("feed_1_qty"), b=Sum("feed_2_qty"))
        feed_kg_today = float((feed_today["a"] or 0) + (feed_today["b"] or 0))

        placed_today = (StockTransfer.objects
                        .filter(date__gte=since, date__lte=today,
                                to_location_type="farm",
                                to_farm_id__in=farm_ids,
                                item__category__name__icontains="chick")
                        .aggregate(s=Sum("quantity"))["s"] or 0)

        live_total = 0.0
        weight_now_kg = 0.0
        feed_total_kg = 0.0
        for batch in BroilerBatch.objects.filter(is_closed=False,
                                                 broiler_farm_id__in=farm_ids):
            entries = DailyEntry.objects.filter(batch=batch)
            placed = float(StockTransfer.objects
                           .filter(to_batch=batch, item__category__name__icontains="chick")
                           .aggregate(s=Sum("quantity"))["s"] or 0)
            lost = entries.aggregate(m=Sum("mortality"), c=Sum("culls"))
            sold = BirdSale.objects.filter(batch=batch).aggregate(
                q=Sum("birds"), w=Sum("net_weight"))
            sold_birds = float(sold["q"] or 0)
            sold_weight = float(sold["w"] or 0)

            available = max(placed - float(lost["m"] or 0) - float(lost["c"] or 0)
                            - sold_birds, 0.0)
            avg_bwt = float(entries.exclude(avg_weight_gms=0)
                            .order_by("-date", "-id")
                            .values_list("avg_weight_gms", flat=True).first() or 0)
            feed = entries.aggregate(a=Sum("feed_1_qty"), b=Sum("feed_2_qty"))

            live_total += available
            weight_now_kg += sold_weight + available * (avg_bwt / 1000.0)
            feed_total_kg += float((feed["a"] or 0) + (feed["b"] or 0))

        mortality_today = float(entries_today.aggregate(s=Sum("mortality"))["s"] or 0)

        return {
            "birds_placed_today": int(placed_today),
            "feed_kg_today": round(feed_kg_today, 2),
            "mortality_pct_today": (round(100 * mortality_today / live_total, 2)
                                    if live_total else 0.0),
            # None, not a number, when nothing has been weighed or sold yet:
            # feed over a near-zero weight produced an FCR of 23 on a farm whose
            # birds simply had not been weighed, which reads as a catastrophe
            # rather than as missing data.
            "fcr": round(feed_total_kg / weight_now_kg, 3) if weight_now_kg > 0 else None,
            "live_birds": int(live_total),
        }
