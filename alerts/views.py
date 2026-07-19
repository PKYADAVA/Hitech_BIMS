"""REST API for the alert feed and audit trail.

Deliberately built on DRF's ``filters.SearchFilter``/``OrderingFilter`` plus a
few explicit query params, rather than pulling in ``django-filter`` (not a
project dependency), so there are no new packages to install. Every queryset is
run through :func:`alerts.permissions.scope_alerts`, so the API can never leak
an alert a user is not entitled to.
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone
from rest_framework import filters, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from .conf import config
from .models import Alert, AuditLog
from .constants import Action, Severity
from .permissions import IsAuthenticatedOwnerOrStaff, scope_alerts
from .serializers import AlertSerializer, AuditLogSerializer


@login_required
def alert_center(request):
    """Full-page notification centre. Data is loaded via the API client-side.

    Rendered inside the project's base layout so it inherits the navbar/theme;
    the filter dropdowns are populated from the enum choices so they never drift
    from the model.
    """
    return render(
        request,
        "alerts/alert_center.html",
        {
            "active_tab": "alerts",
            "severity_choices": Severity.choices,
            "action_choices": Action.choices,
        },
    )


class AlertPagination(PageNumberPagination):
    page_size_query_param = "page_size"
    max_page_size = 200

    @property
    def page_size(self):  # read lazily so tests can override the setting
        return config.DEFAULT_PAGE_SIZE


def _apply_common_filters(request, queryset):
    """Shared query-param filtering for both viewsets."""
    p = request.query_params
    if p.get("severity"):
        queryset = queryset.filter(severity=p["severity"])
    if p.get("action"):
        queryset = queryset.filter(action=p["action"])
    if p.get("event_type"):
        queryset = queryset.filter(event_type=p["event_type"])
    if p.get("model_name"):
        queryset = queryset.filter(model_name__iexact=p["model_name"])
    if p.get("object_id"):
        queryset = queryset.filter(object_id=str(p["object_id"]))
    if p.get("performed_by"):
        queryset = queryset.filter(performed_by_id=p["performed_by"])
    if p.get("date_from"):
        queryset = queryset.filter(created_at__date__gte=p["date_from"])
    if p.get("date_to"):
        queryset = queryset.filter(created_at__date__lte=p["date_to"])
    return queryset


class AlertViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """GET list/detail, DELETE, plus read-state actions.

    Endpoints:
        GET    /api/alerts/                 list (filter/search/paginate)
        GET    /api/alerts/{id}/            detail
        DELETE /api/alerts/{id}/            delete one
        GET    /api/alerts/unread_count/    {"unread": N}
        POST   /api/alerts/{id}/mark_read/  mark one read
        POST   /api/alerts/mark_all_read/   mark all (in scope) read
    """

    serializer_class = AlertSerializer
    permission_classes = [IsAuthenticatedOwnerOrStaff]
    pagination_class = AlertPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["title", "message", "object_display", "actor_label"]
    ordering_fields = ["created_at", "severity", "event_type"]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = Alert.objects.with_related()
        qs = scope_alerts(qs, self.request.user)
        qs = _apply_common_filters(self.request, qs)
        if self.request.query_params.get("is_read") in {"true", "false"}:
            qs = qs.filter(is_read=self.request.query_params["is_read"] == "true")
        return qs

    @action(detail=False, methods=["get"])
    def unread_count(self, request):
        count = scope_alerts(Alert.objects.unread(), request.user).count()
        return Response({"unread": count})

    @action(detail=True, methods=["post"])
    def mark_read(self, request, pk=None):
        alert = self.get_object()
        alert.mark_read()
        return Response(self.get_serializer(alert).data)

    @action(detail=False, methods=["post"])
    def mark_all_read(self, request):
        updated = scope_alerts(Alert.objects.unread(), request.user).update(
            is_read=True, read_at=timezone.now()
        )
        return Response({"marked_read": updated}, status=status.HTTP_200_OK)


class AuditLogViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Read-only audit trail. Staff-only — the forensic record is privileged."""

    serializer_class = AuditLogSerializer
    permission_classes = [IsAdminUser]
    pagination_class = AlertPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["object_display", "actor_label", "reason"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return _apply_common_filters(self.request, AuditLog.objects.select_related("performed_by"))
