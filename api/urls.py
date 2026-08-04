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
from broiler.api import (
    BirdSaleFarmLookupView,
    DailyEntryLookupView,
    DailyEntryStockLookupView,
    MedicineItemLookupView,
    MedicineStockLookupView,
)
from broiler.api import register as register_broiler
from hatchery.api import ChangeRequestReviewView, TraySettingLookupView
from hatchery.api import register as register_hatchery
from inventory.api import register as register_inventory
from inventory.api_write import write_urls as inventory_write_urls
from inventory.models import Item, Warehouse
from hr.api import register as register_hr
from purchase.api import register as register_purchase
from purchase.api_write import write_urls as purchase_write_urls
from user.api import (RoleMobileModuleView, RoleModuleView, RolesAccessView,
                      RoleView, UserCreateView, UserRolesView)
from user.api import register as register_user
from sales.api import register as register_sales
from sales.api_write import write_urls as sales_write_urls
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

from .auth import (
    ChangePasswordView,
    LoginView,
    LogoutView,
    MeView,
    PermissionsView,
    RefreshView,
)
from .health import HealthView, ReadyView
from .reports import (
    BatchSummaryReportView,
    ChickSaleReportView,
    ChicksPlacementReportView,
    DayRecordReportView,
    DeliveryChallanReportView,
    EggIntakeReportView,
    FeedDispatchReportView,
    HatchPerformanceReportView,
    IncubationReportView,
    LiftingReportView,
    LiveFlockReportView,
    MortalityTrendReportView,
)
from .stats import StatsOverviewView
from .viewsets import register_model

app_name = "api"

router = DefaultRouter()
register_broiler(router)
register_hatchery(router)
register_account(router)
register_inventory(router)
register_sales(router)
register_purchase(router)
register_hr(router)
register_user(router)


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
    path("permissions", PermissionsView.as_view(), name="permissions"),
    path("change-password", ChangePasswordView.as_view(), name="change-password"),
]

urlpatterns = [
    path("health", HealthView.as_view(), name="health"),
    path("ready", ReadyView.as_view(), name="ready"),
    # OpenAPI schema + interactive docs (source of the generated mobile client).
    path("schema", SpectacularAPIView.as_view(), name="schema"),
    path("docs", SpectacularSwaggerView.as_view(url_name="api:schema"), name="docs"),
    path("auth/", include((auth_patterns, "auth"))),
    path("stats/overview", StatsOverviewView.as_view(), name="stats-overview"),
    # Bird Sale form: farm → active batch + owning farmer (declared before router).
    path("broiler/farm-lookup", BirdSaleFarmLookupView.as_view(), name="broiler-farm-lookup"),
    # Medicine/Vaccine Consumption: the two columns the phone form was missing.
    path("broiler/medicine-item-lookup", MedicineItemLookupView.as_view(),
         name="broiler-medicine-item-lookup"),
    path("broiler/medicine-stock-lookup", MedicineStockLookupView.as_view(),
         name="broiler-medicine-stock-lookup"),
    # Daily Entry form: the above plus feed phase, breed standards and live birds.
    path("broiler/daily-entry-lookup", DailyEntryLookupView.as_view(),
         name="broiler-daily-entry-lookup"),
    path("broiler/daily-entry-stock", DailyEntryStockLookupView.as_view(),
         name="broiler-daily-entry-stock"),
    # Hatch Entry form: tray setting → dates + source purchase figures.
    path("hatchery/tray-setting-lookup", TraySettingLookupView.as_view(), name="hatchery-tray-setting-lookup"),
    path("reports/live-flock", LiveFlockReportView.as_view(), name="report-live-flock"),
    path("reports/mortality-trend", MortalityTrendReportView.as_view(), name="report-mortality-trend"),
    path("reports/batch-summary", BatchSummaryReportView.as_view(), name="report-batch-summary"),
    path("reports/chicks-placement", ChicksPlacementReportView.as_view(), name="report-chicks-placement"),
    path("reports/feed-dispatch", FeedDispatchReportView.as_view(), name="report-feed-dispatch"),
    path("reports/day-record", DayRecordReportView.as_view(), name="report-day-record"),
    path("reports/lifting", LiftingReportView.as_view(), name="report-lifting"),
    path("reports/hatch-performance", HatchPerformanceReportView.as_view(), name="report-hatch-performance"),
    path("reports/egg-intake", EggIntakeReportView.as_view(), name="report-egg-intake"),
    path("reports/incubation", IncubationReportView.as_view(), name="report-incubation"),
    path("reports/delivery-challan", DeliveryChallanReportView.as_view(), name="report-delivery-challan"),
    path("reports/chick-sale", ChickSaleReportView.as_view(), name="report-chick-sale"),
    # SMS actions (not plain CRUD) — declared before the router so they win.
    path("sms/templates/<int:pk>/send", SmsTemplateSendView.as_view(), name="sms-template-send"),
    path("sms/messages/<int:pk>/retry", SmsMessageRetryView.as_view(), name="sms-message-retry"),
    # Push notifications: device registration + a user-triggered test.
    path("devices/register", DeviceRegisterView.as_view(), name="device-register"),
    path("devices/test", DeviceTestView.as_view(), name="device-test"),
    path("hatchery/change-requests/<int:pk>/<str:decision>",
         ChangeRequestReviewView.as_view(), name="change-request-review"),
    # Access management (admin): role module toggles + user role assignment.
    path("user/users/create", UserCreateView.as_view(), name="user-create"),
    path("user/access/roles", RolesAccessView.as_view(), name="access-roles"),
    path("user/roles/<int:pk>/module", RoleModuleView.as_view(), name="role-module"),
    path("user/roles/<int:pk>/mobile-module", RoleMobileModuleView.as_view(),
         name="role-mobile-module"),
    path("user/roles/<int:pk>", RoleView.as_view(), name="role-detail"),
    path("user/users/<int:pk>/roles", UserRolesView.as_view(), name="user-roles"),
    # Inventory + Purchase transaction writes — reuse the web posting logic
    # (declared before the router so they win over the read-only resource routes).
    *inventory_write_urls(),
    *purchase_write_urls(),
    *sales_write_urls(),
    path("", include(router.urls)),
]
