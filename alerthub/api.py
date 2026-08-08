"""REST endpoints for the bell, the notification centre and the widget.

Every queryset starts from :meth:`Notification.for_user`, which applies both
targeting and scope. There is no code path in this module that reads
``Notification.objects`` without it — that is the property to preserve when
adding an endpoint here.
"""
from __future__ import annotations

from django.db import models
from django.db.models import Count, Prefetch, Q
from django.utils import timezone
from rest_framework import filters, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .constants import Priority
from .engine import mark_read, unread_count
from .models import Notification, NotificationPreference, NotificationRecipient
from .serializers import NotificationSerializer, PreferenceSerializer


class NotificationPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 200


class NotificationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                          viewsets.GenericViewSet):
    """Read-only feed plus read-state actions.

    Deliberately no delete. A notification is a record that someone was told
    something; the history and any later argument about who knew what depend on
    it surviving. "Clear" in the UI means mark read.
    """

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = NotificationPagination
    filter_backends = [filters.SearchFilter]
    search_fields = ["title", "message", "object_display", "voucher_no"]

    def get_queryset(self):
        user = self.request.user
        params = self.request.query_params

        # Prefetching *this user's* recipient row lets the serializer report
        # read state without a query per notification.
        mine = Prefetch(
            "recipients",
            queryset=NotificationRecipient.objects.filter(user=user),
            to_attr="_my_recipients",
        )
        qs = (
            Notification.objects.for_user(user)
            .not_dismissed_by(user)
            .select_related("branch", "farm", "warehouse", "org_centre")
            .prefetch_related(mine)
        )

        for param, field in (
            ("module", "module"),
            ("priority", "priority"),
            ("rule_key", "rule_key"),
        ):
            if params.get(param):
                qs = qs.filter(**{field: params[param]})

        for param, field in (
            ("branch", "branch_id"),
            ("farm", "farm_id"),
            ("warehouse", "warehouse_id"),
        ):
            value = params.get(param)
            if value and str(value).isdigit():
                qs = qs.filter(**{field: int(value)})

        if params.get("date_from"):
            qs = qs.filter(created_at__date__gte=params["date_from"])
        if params.get("date_to"):
            qs = qs.filter(created_at__date__lte=params["date_to"])

        read = params.get("is_read")
        if read in {"true", "false"}:
            qs = qs.filter(
                recipients__user=user, recipients__is_read=(read == "true")
            )

        if params.get("ordering") == "urgency":
            return qs.by_urgency()
        return qs.order_by("-created_at")

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "request": self.request}

    def paginate_queryset(self, queryset):
        page = super().paginate_queryset(queryset)
        return self._attach_recipients(page)

    def _attach_recipients(self, rows):
        if rows is None:
            return rows
        for row in rows:
            mine = getattr(row, "_my_recipients", None)
            row._my_recipient = mine[0] if mine else None
        return rows

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        self._attach_recipients([instance])
        return Response(self.get_serializer(instance).data)

    @action(detail=False, methods=["get"])
    def unread_count(self, request):
        """The bell badge. Cheap, and polled by every page."""
        return Response({"unread": unread_count(request.user)})

    @action(detail=True, methods=["post"])
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        mark_read(request.user, [notification.pk])
        return Response({"ok": True, "unread": unread_count(request.user)})

    @action(detail=True, methods=["post"])
    def dismiss(self, request, pk=None):
        """Clear one notification off *this* user's list.

        Read state and dismissal are different questions — "I have seen it" and
        "I am done with it" — so clearing marks read as well: something removed
        from the list must not keep the badge lit.

        Never a delete. The notification, and the record that this user was
        sent it, both survive; only their view of it changes.
        """
        notification = self.get_object()
        now = timezone.now()
        updated = NotificationRecipient.objects.filter(
            notification=notification, user=request.user, is_dismissed=False,
        ).update(
            is_dismissed=True, dismissed_at=now,
            is_read=True, read_at=models.F("read_at"),
        )
        # read_at only when it was genuinely unread, so clearing an old alert
        # does not rewrite when it was first seen.
        NotificationRecipient.objects.filter(
            notification=notification, user=request.user, read_at__isnull=True,
        ).update(read_at=now)
        return Response({
            "ok": bool(updated), "unread": unread_count(request.user),
        })

    @action(detail=False, methods=["post"])
    def mark_all_read(self, request):
        marked = mark_read(request.user)
        return Response({"marked_read": marked, "unread": unread_count(request.user)})

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """Counts behind the dashboard widget.

        One grouped query for the priority split, plus the handful of named
        tiles the widget shows. All of it is scoped, so two users on different
        branches see different numbers from the same endpoint.
        """
        user = request.user
        scoped = Notification.objects.for_user(user)
        unread = scoped.filter(recipients__user=user, recipients__is_read=False)

        counts = {
            row["priority"]: row["n"]
            for row in unread.values("priority").annotate(n=Count("id", distinct=True))
        }

        def by_keys(*keys):
            return unread.filter(rule_key__in=keys).distinct().count()

        return Response({
            "critical": counts.get(Priority.CRITICAL, 0),
            "high": counts.get(Priority.HIGH, 0),
            "medium": counts.get(Priority.MEDIUM, 0),
            "low": counts.get(Priority.LOW, 0),
            "unread": unread_count(user),
            "tiles": [
                {"key": "pending_approvals", "label": "Pending Approvals",
                 "icon": "fa-solid fa-file-signature",
                 "count": by_keys("finance.journal_approval_pending",
                                  "hr.leave_approval_pending",
                                  "purchase.approval_pending")},
                {"key": "low_stock", "label": "Low Stock",
                 "icon": "fa-solid fa-boxes-stacked",
                 "count": by_keys("inventory.low_stock",
                                  "inventory.negative_stock",
                                  "health.medicine_stock_low")},
                {"key": "payment_due", "label": "Payment Due",
                 "icon": "fa-solid fa-indian-rupee-sign",
                 "count": by_keys("finance.payment_due", "sales.payment_pending",
                                  "finance.receivable_overdue",
                                  "sales.overdue_customer")},
                {"key": "vaccination_due", "label": "Vaccination Due",
                 "icon": "fa-solid fa-syringe",
                 "count": by_keys("health.vaccination_due",
                                  "health.vaccination_overdue")},
                {"key": "high_mortality", "label": "High Mortality",
                 "icon": "fa-solid fa-kiwi-bird",
                 "count": by_keys("production.high_mortality",
                                  "production.cumulative_mortality")},
                {"key": "feed_shortage", "label": "Feed Shortage",
                 "icon": "fa-solid fa-wheat-awn",
                 "count": by_keys("feed.low_feed_stock")},
            ],
        })

    @action(detail=False, methods=["get"])
    def recent(self, request):
        """The bell's dropdown: newest unread first, urgency-ordered.

        A separate endpoint from ``list`` because the bell wants a fixed small
        page with a specific ordering, and giving it its own url keeps the
        polling request out of the centre's filter logic.
        """
        user = request.user
        mine = Prefetch(
            "recipients",
            queryset=NotificationRecipient.objects.filter(user=user),
            to_attr="_my_recipients",
        )
        rows = list(
            Notification.objects.for_user(user)
            .filter(recipients__user=user, recipients__is_read=False)
            .select_related("branch", "farm", "warehouse", "org_centre")
            .prefetch_related(mine)
            .by_urgency()[:10]
        )
        self._attach_recipients(rows)
        serializer = self.get_serializer(rows, many=True)
        return Response({"results": serializer.data,
                         "unread": unread_count(user)})


class PreferenceView(viewsets.ViewSet):
    """The signed-in user's own notification preferences.

    There is no id in any of these routes on purpose: a user may read and write
    their own preferences and nobody else's, so the identity comes from the
    session rather than the url.
    """

    permission_classes = [IsAuthenticated]

    def list(self, request):
        pref = NotificationPreference.for_user(request.user)
        return Response(PreferenceSerializer(pref).data)

    def create(self, request):
        pref = NotificationPreference.for_user(request.user)
        serializer = PreferenceSerializer(pref, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)
