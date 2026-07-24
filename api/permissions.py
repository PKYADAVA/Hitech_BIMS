"""Permission classes for the mobile API.

The web app authorizes by *page* (``WebAccessMiddleware`` maps a URL name to a
tab right). That model does not apply to resource APIs, so v1 uses DRF
permissions instead. This module centralizes them so every domain viewset
shares one policy and we never re-implement authz per resource.

``IsAuthenticated`` is the baseline. ``ReadOnlyOrStaff`` is provided for
master/reference data that mobile should read but not mutate. Object-level
scoping (branch/farm ownership) is intentionally a documented extension point:
add a ``scope_queryset`` hook on the viewset rather than a new permission class.
"""
from __future__ import annotations

from rest_framework.permissions import BasePermission, IsAuthenticated, SAFE_METHODS

__all__ = ["IsAuthenticated", "ReadOnlyOrStaff"]


class ReadOnlyOrStaff(BasePermission):
    """Anyone authenticated may read; only staff may write."""

    def has_permission(self, request, view) -> bool:
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return bool(request.user.is_staff or request.user.is_superuser)
