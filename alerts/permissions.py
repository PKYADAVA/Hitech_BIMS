"""Visibility rules for alerts.

Two layers:

* :func:`scope_alerts` — *row-level* filtering applied to every queryset so a
  user only ever sees alerts they are entitled to. This is the security
  boundary; the API and admin both go through it.
* DRF permission classes — *endpoint-level* gating (authenticated; object owner
  or staff for mutations).

Scope tiers (most→least privileged):
    global admin  -> every alert
    department    -> alerts by users in the same UserProfile.department
    own           -> only alerts the user performed / that target the user
"""
from __future__ import annotations

from django.db.models import Q
from rest_framework.permissions import IsAuthenticated


def _is_global_admin(user) -> bool:
    return bool(user and (user.is_superuser or user.is_staff))


def _department_of(user) -> str:
    profile = getattr(user, "userprofile", None)
    return getattr(profile, "department", "") or "" if profile else ""


def scope_alerts(queryset, user):
    """Restrict ``queryset`` to alerts ``user`` may see."""
    if user is None or not getattr(user, "is_authenticated", False):
        return queryset.none()
    if _is_global_admin(user):
        return queryset

    visibility = Q(performed_by=user) | Q(
        model_name="auth.User", object_id=str(user.pk)
    )

    department = _department_of(user)
    if department:
        # Alerts performed by teammates sharing the department.
        visibility |= Q(performed_by__userprofile__department=department)

    return queryset.filter(visibility)


class IsAuthenticatedOwnerOrStaff(IsAuthenticated):
    """Read within scope for any authenticated user; mutate only own/staff."""

    def has_object_permission(self, request, view, obj) -> bool:
        user = request.user
        if _is_global_admin(user):
            return True
        return obj.performed_by_id == user.pk or (
            obj.model_name == "auth.User" and obj.object_id == str(user.pk)
        )
