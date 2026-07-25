"""The mobile API app.

This app is purely additive: it owns the ``/api/v1/`` surface (JWT auth +
domain resources) and never touches the existing server-rendered web app,
which keeps running on session auth + ``WebAccessMiddleware``. Domain endpoints
live in each domain app's ``api.py`` and are wired here via the shared router,
so there is exactly one place that knows how to build a resource endpoint.
"""
from __future__ import annotations

from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "api"
    verbose_name = "Mobile API (v1)"
