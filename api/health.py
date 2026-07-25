"""Health & readiness probes for load balancers / orchestrators.

The audit flagged the absence of these — without them a proxy can't tell a
booting/broken instance from a healthy one, blocking zero-downtime deploys.

* ``/api/v1/health``  — liveness: process is up (no dependency checks).
* ``/api/v1/ready``   — readiness: the DB is reachable; returns 503 if not.
"""
from __future__ import annotations

from django.db import connection
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .envelope import EnvelopeJSONRenderer


class HealthView(APIView):
    renderer_classes = [EnvelopeJSONRenderer]
    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request):
        return Response({"status": "ok"})


class ReadyView(APIView):
    renderer_classes = [EnvelopeJSONRenderer]
    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except Exception:
            return Response({"status": "unavailable", "database": "down"}, status=503)
        return Response({"status": "ready", "database": "up"})
