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
}


def scope_api_queryset(user, qs):
    """Apply the data scope to an API queryset.

    The API is the same data by another door, so the branch / farm / warehouse
    limits that narrow the web app have to narrow it too — otherwise a token is
    a way round the scoping as well as the matrix.
    """
    from user.services.scoping import scope_multi

    model = qs.model
    scopes = API_SCOPES.get(f"{model._meta.app_label}.{model.__name__}")
    if not scopes or user is None:
        return qs
    return scope_multi(user, qs, **scopes)


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
