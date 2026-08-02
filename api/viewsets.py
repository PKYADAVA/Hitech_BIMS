"""Base viewsets + the one-line resource registration helper.

``register_model(router, prefix, Model, ...)`` is what domain modules call — it
builds a serializer (via the factory) and a viewset, then registers it on the
shared v1 router. That single helper is why adding a resource is one line and
why there is no per-model plumbing to duplicate.

The base viewsets fold in everything a mobile-facing endpoint needs, once:

* the envelope renderer + v1 exception handler (confined to v1),
* auth (``IsAuthenticated``) and standard filter/search/order backends,
* automatic ``select_related``/``prefetch_related`` (kills the N+1 the audit
  flagged, without hand-tuning each viewset),
* an ``?updated_since=<iso>`` filter for delta/offline sync when the model has
  an ``updated_at`` column.
"""
from __future__ import annotations

from typing import Optional

from rest_framework import filters, mixins, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.routers import DefaultRouter

from .envelope import EnvelopeJSONRenderer
from .permissions import MatrixPermission
from .exceptions import api_exception_handler
from .pagination import CursorPagination, StandardPagination
from .serializers import serializer_factory


class V1ViewMixin:
    """Shared wiring that pins every v1 view to the envelope + v1 error shape."""

    renderer_classes = [EnvelopeJSONRenderer]

    def get_exception_handler(self):
        return api_exception_handler


# Query params the base layer interprets itself — never treated as filters.
_RESERVED_PARAMS = frozenset(
    {"page", "page_size", "cursor", "search", "ordering", "updated_since", "format"}
)
# Field types that shouldn't be exact-match filterable (free text / blobs / media).
_NON_FILTER_TYPES = frozenset(
    {"TextField", "FileField", "ImageField", "JSONField", "BinaryField"}
)


class AutoQuerysetMixin:
    """Auto relation-loading + generic filtering + delta-sync, shared by all resources."""

    def get_queryset(self):
        qs = super().get_queryset()
        model = qs.model

        select, prefetch = [], []
        for field in model._meta.get_fields():
            if getattr(field, "many_to_one", False) or getattr(field, "one_to_one", False):
                if getattr(field, "concrete", False):
                    select.append(field.name)
            elif getattr(field, "many_to_many", False) and getattr(field, "concrete", False):
                prefetch.append(field.name)
        if select:
            qs = qs.select_related(*select)
        if prefetch:
            qs = qs.prefetch_related(*prefetch)

        # Generic exact-match filtering: ?<field>=<value> for any concrete,
        # non-text field (incl. FK ids, so line items filter by ?parent=<id>).
        filterable = {
            f.name: f.attname if f.is_relation else f.name
            for f in model._meta.concrete_fields
            if f.get_internal_type() not in _NON_FILTER_TYPES
        }
        for key, value in self.request.query_params.items():
            if key in _RESERVED_PARAMS or key not in filterable:
                continue
            qs = qs.filter(**{filterable[key]: value})

        # Incremental sync: return only rows changed since a timestamp.
        since = self.request.query_params.get("updated_since")
        if since and _has_field(model, "updated_at"):
            qs = qs.filter(updated_at__gte=since)
        return scope_api_queryset(getattr(self.request, "user", None), qs)


class BaseModelViewSet(V1ViewMixin, AutoQuerysetMixin, viewsets.ModelViewSet):
    """Full CRUD resource (list/retrieve/create/update/partial_update/destroy)."""

    permission_classes = [IsAuthenticated, MatrixPermission]
    pagination_class = StandardPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    ordering = ["-id"]


class BaseReadOnlyViewSet(V1ViewMixin, AutoQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    """List + retrieve only — for master/reference data used as mobile pickers."""

    permission_classes = [IsAuthenticated, MatrixPermission]
    pagination_class = StandardPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    ordering = ["-id"]


#: model -> the scopes that apply to it and the path from the row to each.
#: Only where the link is unambiguous; anything else stays unscoped rather than
#: risk hiding rows the web app would show.
#: ``"mode": "any"`` switches a row from scope_multi (every dimension must
#: pass) to scope_any (one end is enough). Which one is right is a property of
#: the row, not a preference: a transfer has two ends, and requiring both to be
#: in scope hides the movement out of the user's own store — the one they most
#: need to see. Each entry below mirrors what the web view for the same model
#: does; copying the web is the point, since the API is that data by another
#: door and the two disagreeing is the bug.
API_SCOPES = {
    "broiler.Branch": {"branches": "id"},
    "broiler.BroilerFarm": {"branches": "branch_id", "farms": "id"},
    "broiler.BroilerBatch": {"branches": "broiler_farm__branch_id",
                             "farms": "broiler_farm_id"},
    "broiler.Supervisor": {"branches": "branch_id"},
    "broiler.DailyEntry": {"branches": "farm__branch_id", "farms": "farm_id"},
    "broiler.BirdSale": {"branches": "farm__branch_id", "farms": "farm_id"},
    "broiler.BroilerFarmShed": {"farms": "farm_id"},
    "inventory.Warehouse": {"sectors": "id"},
    "sales.Customer": {"customer_groups": "customer_group_id"},

    # Hatchery transactions — hatchery/views.py scopes each of these with
    # scope_any on exactly these fields.
    "hatchery.EggPurchase": {"mode": "any", "sectors": "warehouse_id"},
    "hatchery.ChickSale": {"mode": "any", "sectors": "warehouse_id"},
    "hatchery.DeliveryChallan": {"mode": "any",
                                 "sectors": "chick_sales__warehouse_id"},

    # Stock movements — inventory/views.py::_scope_by_items, same fields.
    "inventory.StockIssue": {"mode": "any", "sectors": "items__warehouse_id",
                             "farms": "items__farm_id"},
    "inventory.StockReceive": {"mode": "any", "sectors": "items__warehouse_id",
                               "farms": "items__farm_id"},

    # Transfers — inventory/views.py::_scope_transfer. Both ends of the
    # movement, either of which puts it in scope.
    "inventory.StockTransfer": {"mode": "any",
                                "sectors": ("from_warehouse_id", "to_warehouse_id"),
                                "farms": ("from_farm_id", "to_farm_id")},
    "inventory.MedicineTransfer": {"mode": "any",
                                   "sectors": ("from_warehouse_id", "to_warehouse_id"),
                                   "farms": ("from_farm_id", "to_farm_id")},

    # One location, recorded as either a warehouse or a farm —
    # inventory/views.py::_scope_adjustment.
    "inventory.InventoryAdjustment": {"mode": "any", "sectors": "warehouse_id",
                                      "farms": "farm_id"},

    # Sales — sales/views.py. `branch` on an invoice is a Warehouse, which is
    # why it maps to the sectors scope and not to branches.
    "sales.SalesInvoice": {"mode": "any", "sectors": "branch_id"},
    "sales.SalesReceipt": {"mode": "any", "sectors": "location_id"},

    # Purchase — purchase/views.py. The two purchase headers keep their
    # location on the lines, like stock issues and receives do.
    "purchase.GeneralPurchase": {"mode": "any",
                                 "sectors": "items__farm_warehouse_id"},
    "purchase.ChicksPurchase": {"mode": "any",
                                "sectors": "items__farm_warehouse_id"},
    "purchase.SupplierPayment": {"mode": "any", "sectors": "location_id"},

    # Account — account/views.py scopes the voucher list by its sector.
    "account.Voucher": {"mode": "any", "sectors": "sector_id"},
}


#: API models with no data scope, and why — the counterpart to API_SCOPES.
#:
#: An unscoped model returns every row to anyone whose matrix lets them read it,
#: which is right for reference data and wrong for anything with a location.
#: Nothing distinguished the two until this list existed: a model added to the
#: API simply arrived unscoped and nobody found out. A test now holds every
#: registered model to "scoped, or named here", so the next one forces the
#: decision instead of defaulting to open.
#:
#: Adding a scope is not free — a wrong path hides rows the web app shows,
#: which is worse than an unscoped read of data the matrix already permits. So
#: "the link exists" is not sufficient grounds; the web view for the same model
#: has to scope it the same way.
UNSCOPED_API_MODELS = {
    # Reference and configuration data: no branch, farm or warehouse dimension
    # to scope by. Everyone who may read them may read all of them.
    "account.BankCashMaster": "Master data, no location dimension",
    "account.ChartOfAccount": "Master data, no location dimension",
    "account.CompanyProfile": "One row for the whole company",
    "account.FinancialYear": "Company-wide",
    "account.OrganizationCentre": "Master data",
    "account.TermsConditions": "Master data",
    "broiler.Breed": "Master data",
    "broiler.BreedStandard": "Master data",
    "broiler.FarmerGroup": "Master data",
    "broiler.Region": "Above branch — scoping it would hide the tree",
    "hr.Department": "Master data",
    "hr.Designation": "Master data",
    "hr.Shift": "Master data",
    "inventory.Item": "Catalogue, not stock — quantities are scoped, items are not",
    "inventory.ItemCategory": "Master data",
    "inventory.ItemPriceList": "Master data",
    "inventory.Sector": "Master data",
    "inventory.UnitOfMeasurement": "Master data",
    "purchase.CreditTerm": "Master data",
    "purchase.TaxMaster": "Master data",
    "purchase.VendorGroup": "Master data — it is itself a scope dimension",
    "sales.CustomerGroup": "Master data — it is itself a scope dimension",
    "sales.SalesPriceMaster": "Master data",

    # Parties. Suppliers have no group scope wired; customers are scoped.
    "broiler.Farmer": "No unambiguous branch link; the farm carries it",
    "purchase.Supplier": "supplier_groups scope is stored but not applied anywhere yet",
    "purchase.SupplierShippingAddress": "Follows its supplier",
    "sales.CustomerShippingAddress": "Follows its customer",

    # Line items. They are reached through their parent, which is scoped, and
    # scoping them independently risks a different answer from the parent's.
    "hatchery.ChickSaleItem": "Reached through ChickSale, which is scoped",
    "hatchery.DeliveryChallanItem": "Reached through DeliveryChallan",
    "hatchery.EggPurchaseItem": "Reached through EggPurchase",
    "hr.LeaveSelectedDate": "Reached through EmployeeLeave",
    "purchase.ChicksPurchaseItem": "Reached through ChicksPurchase",
    "purchase.GeneralPurchaseItem": "Reached through GeneralPurchase",
    "purchase.SupplierPaymentLine": "Reached through SupplierPayment",
    "sales.SalesInvoiceItem": "Reached through SalesInvoice",

    # Not yet scoped, and each needs its web view checked first. Listed so the
    # gap is visible rather than implied by absence.
    "broiler.BirdSaleReceipt": "The web does not scope it either (checked 2026-08-02)",
    "broiler.BroilerDisease": "The web does not scope it either",
    "broiler.BroilerLine": "The web does not scope it either",
    "broiler.GrowingChargeScheme": "The web does not scope it either",
    "broiler.GrowingChargeSettlement": "The web does not scope it either",
    "broiler.MedicineVaccineEntry": "The web does not scope it either",
    "hatchery.ChangeRequest": "Workflow record, not location data",
    "hatchery.EggGrading": "The web does not scope it either",
    "hatchery.HatchEntry": "The web does not scope it either",
    "hatchery.HatchSetting": "The web does not scope it either",
    "hatchery.TraySetting": "The web does not scope it either",
    "hr.Attendance": "HR is unscoped on the web — no scope call anywhere in hr/views.py",
    "hr.Employee": "HR is unscoped on the web",
    "hr.EmployeeLeave": "HR is unscoped on the web",
    "hr.Group": "HR is unscoped on the web",
    "hr.Payroll": "HR is unscoped on the web",
    "purchase.CreditNote": "The web does not scope it either",
    "purchase.DebitNote": "The web does not scope it either",

    # RBAC configuration. Admin-only already, and not location data.
    "user.GroupAccessProfile": "Admin-only RBAC config",
    "user.GroupTabPermission": "Admin-only RBAC config",
    "user.UserProfile": "Admin-only, no location dimension",
}


def registered_api_models():
    """Every model the mobile API exposes, as ``app_label.ModelName``.

    Read from the ``register_model`` calls rather than the router, so it can be
    used from a test without building the whole API.
    """
    import re
    from pathlib import Path

    from django.apps import apps
    from django.conf import settings

    found = set()
    for app in ("broiler", "hatchery", "inventory", "sales", "purchase", "hr",
                "account", "user", "notification", "tracking"):
        path = Path(settings.BASE_DIR) / app / "api.py"
        if not path.exists():
            continue
        for match in re.finditer(
                r"register_model\(\s*router,\s*\"[^\"]+\",\s*(\w+)",
                path.read_text(encoding="utf-8")):
            try:
                model = apps.get_model(app, match.group(1))
            except LookupError:
                continue
            found.add(f"{model._meta.app_label}.{model.__name__}")
    return found


def scope_api_queryset(user, qs):
    """Apply the data scope to an API queryset.

    The API is the same data by another door, so the branch / farm / warehouse
    limits that narrow the web app have to narrow it too — otherwise a token is
    a way round the scoping as well as the matrix.
    """
    from user.services.scoping import scope_any, scope_multi

    model = qs.model
    scopes = API_SCOPES.get(f"{model._meta.app_label}.{model.__name__}")
    if not scopes or user is None:
        return qs
    scopes = dict(scopes)
    combine = scope_any if scopes.pop("mode", "all") == "any" else scope_multi
    return combine(user, qs, **scopes)


def _has_field(model, name: str) -> bool:
    return any(f.name == name for f in model._meta.get_fields())


def register_model(
    router: DefaultRouter,
    prefix: str,
    model,
    *,
    read_only: bool = False,
    serializer=None,
    fields: Optional[list[str]] = None,
    exclude: Optional[list[str]] = None,
    search_fields: Optional[list[str]] = None,
    ordering: Optional[list[str]] = None,
    cursor: bool = False,
    permission_classes=None,
    basename: Optional[str] = None,
) -> None:
    """Build and register a resource viewset in one call.

    Args:
        prefix: URL prefix, e.g. ``"broiler/daily-entries"``.
        read_only: expose list+retrieve only (masters/reference data).
        serializer: a custom serializer class; defaults to the factory output.
        cursor: use cursor pagination (infinite-scroll feeds/transactions).
        search_fields/ordering: forwarded to the DRF filter backends.
    """
    serializer_cls = serializer or serializer_factory(
        model, fields=fields, exclude=exclude
    )
    base = BaseReadOnlyViewSet if read_only else BaseModelViewSet

    attrs: dict = {
        "queryset": model._default_manager.all(),
        "serializer_class": serializer_cls,
    }
    if search_fields:
        attrs["search_fields"] = search_fields
    if ordering:
        attrs["ordering"] = ordering
    if cursor:
        pg = type(f"{model.__name__}Cursor", (CursorPagination,), {})
        # Cursor pagination needs a stable, unique-enough ordering. Prefer
        # created_at with an id tie-breaker (correct even when timestamps
        # collide); fall back to the always-unique pk when there's no
        # created_at column.
        pg.ordering = ("-created_at", "-id") if _has_field(model, "created_at") else "-id"
        attrs["pagination_class"] = pg
    if permission_classes:
        attrs["permission_classes"] = permission_classes

    viewset = type(f"{model.__name__}ViewSet", (base,), attrs)
    router.register(prefix, viewset, basename=basename or _default_basename(prefix))


def _default_basename(prefix: str) -> str:
    return prefix.replace("/", "-").rstrip("-")
