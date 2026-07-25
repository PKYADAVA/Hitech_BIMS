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

from account.api import register as register_account
from account.models import ChartOfAccount
from broiler.api import register as register_broiler
from hatchery.api import ChangeRequestReviewView
from hatchery.api import register as register_hatchery
from inventory.api import register as register_inventory
from inventory.models import Item, Warehouse
from notification.api import (
    DeviceRegisterView,
    DeviceTestView,
    SmsMessageRetryView,
    SmsSettingsSerializer,
    SmsTemplateSendView,
)
from notification.models import SmsMessage, SmsSettings, SmsTemplate
from purchase.models import Supplier
from sales.models import Customer

from .auth import LoginView, LogoutView, MeView, RefreshView
from .health import HealthView, ReadyView
from .stats import StatsOverviewView
from .viewsets import register_model

app_name = "api"

router = DefaultRouter()
register_broiler(router)
register_hatchery(router)
register_account(router)
register_inventory(router)


def register_shared(router: DefaultRouter) -> None:
    """Cross-app reference data used as FK pickers by multiple domains."""
    register_model(router, "items", Item, read_only=True,
                   search_fields=["item_code", "description"], ordering=["item_code"])
    register_model(router, "warehouses", Warehouse, read_only=True,
                   search_fields=["code", "name"], ordering=["name"])
    register_model(router, "customers", Customer, read_only=True,
                   search_fields=["code", "name"], ordering=["name"])
    register_model(router, "suppliers", Supplier, read_only=True,
                   search_fields=["code", "name"], ordering=["name"])
    register_model(router, "accounts", ChartOfAccount, read_only=True,
                   search_fields=["code", "description"], ordering=["code"])


def register_sms(router: DefaultRouter) -> None:
    """SMS management (notification app): templates, message history, settings."""
    # Templates are fully manageable (create/edit/delete/toggle active).
    register_model(router, "sms/templates", SmsTemplate,
                   search_fields=["key", "name", "module", "transaction"],
                   ordering=["module", "name"])
    # History is a read-only log (writes happen via send/retry actions).
    register_model(router, "sms/messages", SmsMessage, read_only=True,
                   search_fields=["party_name", "mobile", "document_no"], cursor=True)
    # Gateway settings — editable; api_key is write-only (never returned on read).
    register_model(router, "sms/settings", SmsSettings, serializer=SmsSettingsSerializer)


register_shared(router)
register_sms(router)

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
    path("stats/overview", StatsOverviewView.as_view(), name="stats-overview"),
    # SMS actions (not plain CRUD) — declared before the router so they win.
    path("sms/templates/<int:pk>/send", SmsTemplateSendView.as_view(), name="sms-template-send"),
    path("sms/messages/<int:pk>/retry", SmsMessageRetryView.as_view(), name="sms-message-retry"),
    # Push notifications: device registration + a user-triggered test.
    path("devices/register", DeviceRegisterView.as_view(), name="device-register"),
    path("devices/test", DeviceTestView.as_view(), name="device-test"),
    path("hatchery/change-requests/<int:pk>/<str:decision>",
         ChangeRequestReviewView.as_view(), name="change-request-review"),
    path("", include(router.urls)),
]
