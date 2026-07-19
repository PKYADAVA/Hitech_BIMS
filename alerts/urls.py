"""URLs for the alerts module — one namespaced include covers both surfaces.

Mounted at the project root (``include("alerts.urls")``), this exposes:

* ``/alerts/center/``   — the server-rendered Alert Center page (HTML shell;
  the table is hydrated client-side from the API).
* ``/api/alerts/``      — the DRF alert feed (list/detail/delete + actions).
* ``/api/audit-logs/``  — the read-only audit trail (staff only).

Keeping the API under ``/api/`` while the page sits at ``/alerts/`` — but both
in the same ``alerts`` namespace — means ``{% url 'alerts:alert_center' %}`` and
``{% url 'alerts:alert-list' %}`` both resolve without a second app config.
"""
from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AlertViewSet, AuditLogViewSet, alert_center

app_name = "alerts"

router = DefaultRouter()
router.register("alerts", AlertViewSet, basename="alert")
router.register("audit-logs", AuditLogViewSet, basename="auditlog")

urlpatterns = [
    path("alerts/center/", alert_center, name="alert_center"),
    path("api/", include(router.urls)),
]
