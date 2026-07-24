"""drf-spectacular preprocessing hook.

Keeps the generated OpenAPI schema (and therefore the mobile TypeScript client)
focused on the ``/api/v1/`` surface: the legacy web AJAX endpoints and the
alerts UI API are excluded so the mobile contract stays clean and small.
"""
from __future__ import annotations


def only_v1_endpoints(endpoints):
    """Drop any path that isn't under ``/api/v1/``."""
    return [
        (path, path_regex, method, callback)
        for (path, path_regex, method, callback) in endpoints
        if path.startswith("/api/v1/")
    ]
