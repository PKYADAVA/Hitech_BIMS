"""v1 exception handler → machine-readable, envelope-ready errors.

Attached per-view (not globally) so only ``/api/v1/`` errors are reshaped; the
``alerts`` API and the web app are unaffected. Turns DRF/Django exceptions into
``{code, message, fields}``:

* validation errors    → ``code="validation_error"`` + per-field messages
* auth/permission/404  → stable codes (``not_authenticated`` etc.)
* anything unhandled    → logged with the traceback, returned as a generic 500
  that never leaks internals to the client (fixes the ``str(e)`` leak the audit
  flagged in the legacy AJAX endpoints).
"""
from __future__ import annotations

import logging
from typing import Any

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger("api")

# Map common DRF exception default_codes to stable API error codes.
_CODE_BY_STATUS = {
    status.HTTP_400_BAD_REQUEST: "validation_error",
    status.HTTP_401_UNAUTHORIZED: "not_authenticated",
    status.HTTP_403_FORBIDDEN: "permission_denied",
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
    status.HTTP_406_NOT_ACCEPTABLE: "not_acceptable",
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: "unsupported_media_type",
    status.HTTP_429_TOO_MANY_REQUESTS: "throttled",
}


def api_exception_handler(exc: Exception, context: dict) -> Response:
    response = drf_exception_handler(exc, context)

    if response is None:
        # Not a DRF exception → an unhandled server error. Log it (with stack)
        # and return a safe, generic body. Never surface str(exc) to mobile.
        logger.exception("Unhandled API exception in %s", context.get("view"))
        return Response(
            {"code": "server_error", "message": "An unexpected error occurred.", "fields": {}},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    code = _CODE_BY_STATUS.get(response.status_code, "error")
    message, fields = _split(response.data)
    response.data = {"code": code, "message": message, "fields": fields}
    return response


def _split(data: Any) -> tuple[str, dict]:
    """Return ``(human_message, field_errors)`` from a DRF error body."""
    if isinstance(data, dict):
        if "detail" in data and len(data) == 1:
            return str(data["detail"]), {}
        # Field-level validation errors: {"field": ["msg", ...], ...}
        fields = {k: (v if isinstance(v, list) else [str(v)]) for k, v in data.items()}
        return "Validation failed.", fields
    if isinstance(data, list):
        return "; ".join(str(x) for x in data), {}
    return str(data), {}
