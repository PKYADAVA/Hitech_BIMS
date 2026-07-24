"""Root URLconf for the mobile API (mounted at ``/api/v1/``).

One shared :class:`DefaultRouter` collects every domain's resources: each domain
app exposes a ``register(router)`` function (see ``broiler/api.py`` /
``hatchery/api.py``) that this module calls. Adding a whole new domain to the
mobile API is therefore a two-line change here plus that domain's ``api.py`` —
no per-endpoint URL wiring.
"""
from __future__ import annotations

from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from broiler.api import register as register_broiler
from hatchery.api import register as register_hatchery

from .auth import LoginView, LogoutView, MeView, RefreshView
from .health import HealthView, ReadyView

app_name = "api"

router = DefaultRouter()
register_broiler(router)
register_hatchery(router)

auth_patterns = [
    path("login", LoginView.as_view(), name="login"),
    path("refresh", RefreshView.as_view(), name="refresh"),
    path("logout", LogoutView.as_view(), name="logout"),
    path("me", MeView.as_view(), name="me"),
]

urlpatterns = [
    path("health", HealthView.as_view(), name="health"),
    path("ready", ReadyView.as_view(), name="ready"),
    # OpenAPI schema + interactive docs (source of the generated mobile client).
    path("schema", SpectacularAPIView.as_view(), name="schema"),
    path("docs", SpectacularSwaggerView.as_view(url_name="api:schema"), name="docs"),
    path("auth/", include((auth_patterns, "auth"))),
    path("", include(router.urls)),
]
