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
        roles = [
            {"id": g.id, "name": g.name, "modules": _role_modules(g)}
            for g in AuthGroup.objects.order_by("name")
        ]
        return Response({"navs": _MANAGED_NAVS, "roles": roles})

    def post(self, request):
        """Create a new role (auth group)."""
        name = str(request.data.get("name") or "").strip()
        if not name:
            raise ValidationError({"name": ["Role name is required."]})
        group, created = AuthGroup.objects.get_or_create(name=name)
        return Response(
            {"id": group.id, "name": group.name, "modules": _role_modules(group), "created": created}
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
        return Response({"id": user.id, "group_ids": list(user.groups.values_list("id", flat=True))})


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
