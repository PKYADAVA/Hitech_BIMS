"""User & access-control domain — mobile API v1 resources.

Exposes the RBAC surface (system users, profiles, groups/roles and their tab
permissions + access profiles) **read-only** and **admin-only** — this is
sensitive configuration, so editing stays in the web app. The auth ``User``
serializer explicitly excludes the password hash and permission M2Ms.

Registered under ``/api/v1/user/…`` by :func:`register` (called from
``api/urls.py``).
"""
from __future__ import annotations

from django.contrib.auth.models import Group as AuthGroup
from django.contrib.auth.models import User as AuthUser
from rest_framework.permissions import IsAdminUser

from api.viewsets import register_model

from .models import GroupAccessProfile, GroupTabPermission, UserProfile

_ADMIN = [IsAdminUser]


def register(router) -> None:
    # System users — never serialize the password hash or permission M2Ms.
    register_model(router, "user/users", AuthUser, read_only=True,
                   exclude=["password", "user_permissions"],
                   search_fields=["username", "email", "first_name", "last_name"],
                   ordering=["username"], permission_classes=_ADMIN)
    register_model(router, "user/profiles", UserProfile, read_only=True,
                   search_fields=["department", "role"], permission_classes=_ADMIN)

    # Roles (groups) + their tab permissions / access profile.
    register_model(router, "user/groups", AuthGroup, read_only=True,
                   search_fields=["name"], ordering=["name"], permission_classes=_ADMIN)
    register_model(router, "user/group-permissions", GroupTabPermission, read_only=True,
                   search_fields=["tab_code"], permission_classes=_ADMIN)
    register_model(router, "user/group-access", GroupAccessProfile, read_only=True,
                   permission_classes=_ADMIN)


# --- Access management (admin editor) --------------------------------------
from django.contrib.auth.models import Group as AuthGroup  # noqa: E402
from django.contrib.auth.models import User as AuthUser  # noqa: E402
from django.contrib.auth.password_validation import validate_password  # noqa: E402
from django.core.exceptions import ValidationError as DjangoValidationError  # noqa: E402
from rest_framework.exceptions import NotFound, ValidationError  # noqa: E402
from rest_framework.permissions import AllowAny, IsAuthenticated  # noqa: E402
from rest_framework.response import Response  # noqa: E402
from rest_framework.views import APIView  # noqa: E402

from api.viewsets import V1ViewMixin  # noqa: E402
from user.access import NAV_GROUPS  # noqa: E402

from .models import GroupTabPermission  # noqa: E402

# Navs surfaced as modules in the mobile app (SMS lives under "notifications").
_MANAGED_NAVS = [
    "broiler", "hatchery", "account", "inventory",
    "sales", "purchase", "hr", "user", "notifications",
]
_ALL_ON = {
    "can_view": True, "can_add": True, "can_edit": True, "can_delete": True,
    "can_print": True, "can_save": True, "can_update": True, "can_favorite": True,
}


def _role_modules(group) -> dict:
    """Which managed navs the group has *any* view permission on."""
    viewable = set(
        GroupTabPermission.objects.filter(group=group, can_view=True)
        .values_list("tab_code", flat=True)
    )
    return {nav: bool(NAV_GROUPS.get(nav, set()) & viewable) for nav in _MANAGED_NAVS}


def _role_mobile(group) -> dict:
    """Which phone modules the group shows — the Mobile Access switch.

    A group with no rows is unconfigured, which means every module its tabs
    allow, so it reads back as all-on. That matches what the web editor shows
    for a group being configured for the first time.
    """
    from user.models import GroupMobileAccess
    from user.services.mobile_access import ALL_KEYS

    rows = {r.module_key: r.enabled
            for r in GroupMobileAccess.objects.filter(group=group)}
    if not rows:
        return {key: True for key in ALL_KEYS}
    return {key: rows.get(key, False) for key in ALL_KEYS}


def _materialise_mobile(group) -> None:
    """Give an unconfigured group a full set of rows before the first edit.

    Without this, switching one module off would leave the group with a single
    disabled row — and "some rows" is what tells the system a group has been
    configured, so every *other* module would silently switch off with it. The
    web editor writes all nine rows on save for the same reason.
    """
    from user.models import GroupMobileAccess
    from user.services.mobile_access import ALL_KEYS

    if GroupMobileAccess.objects.filter(group=group).exists():
        return
    GroupMobileAccess.objects.bulk_create([
        GroupMobileAccess(group=group, module_key=key, enabled=True, position=index)
        for index, key in enumerate(ALL_KEYS)
    ])


class UserCreateView(V1ViewMixin, APIView):
    """POST /user/users/create — admin creates a new login user.

    Hashes the password (never stores/returns it), assigns roles, and can grant
    staff access. Creating superusers is intentionally not allowed here — that
    stays in the web app / Django admin.
    """

    permission_classes = _ADMIN

    def post(self, request):
        data = request.data
        username = str(data.get("username") or "").strip()
        if not username:
            raise ValidationError({"username": ["Username is required."]})
        if AuthUser.objects.filter(username__iexact=username).exists():
            raise ValidationError({"username": ["A user with that username already exists."]})

        password = str(data.get("password") or "")
        if not password:
            raise ValidationError({"password": ["Password is required."]})
        try:
            validate_password(password)
        except DjangoValidationError as exc:
            raise ValidationError({"password": list(exc.messages)})

        ids = data.get("group_ids") or []
        if not isinstance(ids, list):
            raise ValidationError({"group_ids": ["Must be a list of role ids."]})

        user = AuthUser.objects.create_user(
            username=username,
            password=password,
            email=str(data.get("email") or "").strip(),
            first_name=str(data.get("first_name") or "").strip(),
            last_name=str(data.get("last_name") or "").strip(),
        )
        user.is_active = bool(data.get("is_active", True))
        user.is_staff = bool(data.get("is_staff", False))
        user.save(update_fields=["is_active", "is_staff"])
        if ids:
            user.groups.set(AuthGroup.objects.filter(id__in=ids))

        return Response({
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "is_active": user.is_active,
            "is_staff": user.is_staff,
            "group_ids": list(user.groups.values_list("id", flat=True)),
        })


class RolesAccessView(V1ViewMixin, APIView):
    """GET /user/access/roles — every role with its per-module access map."""

    permission_classes = _ADMIN

    def get(self, request):
        from user.services.mobile_access import MOBILE_MODULES

        roles = [
            {"id": g.id, "name": g.name,
             "modules": _role_modules(g), "mobile": _role_mobile(g)}
            for g in AuthGroup.objects.order_by("name")
        ]
        # Titles travel with the keys so the client needs no second label map
        # to drift out of step with the registry.
        return Response({
            "navs": _MANAGED_NAVS,
            "mobile_modules": [{"key": key, "title": title}
                               for key, title, *_rest in MOBILE_MODULES],
            "roles": roles,
        })

    def post(self, request):
        """Create a new role (auth group)."""
        name = str(request.data.get("name") or "").strip()
        if not name:
            raise ValidationError({"name": ["Role name is required."]})
        group, created = AuthGroup.objects.get_or_create(name=name)
        return Response(
            {"id": group.id, "name": group.name, "modules": _role_modules(group),
             "mobile": _role_mobile(group), "created": created}
        )


class RoleModuleView(V1ViewMixin, APIView):
    """POST /user/roles/<id>/module {module, enabled} — bulk grant/revoke a
    whole module's tabs for a role."""

    permission_classes = _ADMIN

    def post(self, request, pk):
        group = AuthGroup.objects.filter(pk=pk).first()
        if not group:
            raise NotFound("Role not found.")
        nav = str(request.data.get("module") or "")
        if nav not in _MANAGED_NAVS:
            raise ValidationError({"module": ["Unknown module."]})
        enabled = bool(request.data.get("enabled"))
        tabs = sorted(NAV_GROUPS.get(nav, set()))

        if enabled:
            for tab_code in tabs:
                GroupTabPermission.objects.update_or_create(
                    group=group, tab_code=tab_code, defaults=_ALL_ON
                )
        else:
            GroupTabPermission.objects.filter(group=group, tab_code__in=tabs).delete()

        return Response({"module": nav, "enabled": enabled, "modules": _role_modules(group)})


class RoleMobileModuleView(V1ViewMixin, APIView):
    """POST /user/roles/<id>/mobile-module {module, enabled} — show or hide one
    module of the phone app for a role.

    The web counterpart is User > Mobile Access. Same rule applies here: this
    is subtractive, so switching a module on cannot grant access the tab matrix
    withholds — it only stops Mobile Access from taking it away.
    """

    permission_classes = _ADMIN

    def post(self, request, pk):
        from user.models import GroupMobileAccess
        from user.services.mobile_access import ALL_KEYS

        group = AuthGroup.objects.filter(pk=pk).first()
        if not group:
            raise NotFound("Role not found.")
        key = str(request.data.get("module") or "")
        if key not in ALL_KEYS:
            raise ValidationError({"module": ["Unknown mobile module."]})
        enabled = bool(request.data.get("enabled"))

        _materialise_mobile(group)

        # Only ever write ``enabled`` on an existing row — the order is set in
        # the web editor and a toggle here has no opinion about it.
        row, created = GroupMobileAccess.objects.get_or_create(
            group=group, module_key=key,
            defaults={"enabled": enabled, "position": ALL_KEYS.index(key)},
        )
        if not created and row.enabled != enabled:
            row.enabled = enabled
            row.save(update_fields=["enabled"])

        return Response({"module": key, "enabled": enabled,
                         "mobile": _role_mobile(group)})


class UserRolesView(V1ViewMixin, APIView):
    """POST /user/users/<id>/roles {group_ids: [...]} — set a user's roles."""

    permission_classes = _ADMIN

    def post(self, request, pk):
        user = AuthUser.objects.filter(pk=pk).first()
        if not user:
            raise NotFound("User not found.")
        ids = request.data.get("group_ids")
        if not isinstance(ids, list):
            raise ValidationError({"group_ids": ["Must be a list of role ids."]})

        user.groups.set(AuthGroup.objects.filter(id__in=ids))
        return Response({"id": user.id,
                         "group_ids": sorted(user.groups.values_list("id", flat=True))})


class RoleView(V1ViewMixin, APIView):
    """PATCH /user/roles/<id> {name} — rename;  DELETE — remove a role."""

    permission_classes = _ADMIN

    def patch(self, request, pk):
        group = AuthGroup.objects.filter(pk=pk).first()
        if not group:
            raise NotFound("Role not found.")
        name = str(request.data.get("name") or "").strip()
        if not name:
            raise ValidationError({"name": ["Role name is required."]})
        group.name = name
        group.save(update_fields=["name"])
        return Response({"id": group.id, "name": group.name})

    def delete(self, request, pk):
        group = AuthGroup.objects.filter(pk=pk).first()
        if not group:
            raise NotFound("Role not found.")
        GroupTabPermission.objects.filter(group=group).delete()
        group.delete()
        return Response({"deleted": True})


class DashboardWidgetsView(V1ViewMixin, APIView):
    """GET /dashboard-widgets — the same five data widgets home.html's own
    dashboard-widgets fetch renders, for the phone's dashboard.

    Calls the identical ``dashboard_widgets()`` the web page uses, so a widget
    is gated by the same tab matrix and the same admin-configured on/off +
    ordering (``GroupDashboardWidget`` — Dashboard Access) either side reads.
    Query params mirror the web filter bar: date, branch, line, supervisor,
    farm — all optional.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .services.dashboard_widgets import dashboard_widgets, parse_filters

        filters = parse_filters(request.query_params)
        return Response(dashboard_widgets(request.user, filters))


class AppVersionView(V1ViewMixin, APIView):
    """GET /app-version — the latest published build, for the phone's own
    sideload-update check.

    Deliberately open: the client that needs this most is the one furthest
    behind, and a breaking API change is exactly the case a login-gated
    check would fail on — the app has to be able to learn it needs updating
    before it can necessarily still log in.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        from django.urls import reverse

        from .models import AppRelease

        latest = AppRelease.objects.first()
        if latest is None:
            return Response({"latest_version": None, "latest_version_code": None,
                             "download_url": None, "force_update": False, "notes": ""})
        return Response({
            "latest_version": latest.version,
            "latest_version_code": latest.version_code,
            # This domain, not the object storage's — see app_release_download.
            "download_url": (request.build_absolute_uri(reverse("app_release_download"))
                             if latest.apk_file else None),
            "force_update": latest.force_update,
            "notes": latest.release_notes,
        })
