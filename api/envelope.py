"""Uniform response envelope for the mobile API.

Every ``/api/v1/`` response — success or error, list or detail — comes back in
the *same* shape so the mobile client writes one response parser, not one per
endpoint::

    { "success": true,  "data": <payload>, "error": null,        "meta": {...} }
    { "success": false, "data": null,      "error": {code,...},  "meta": {} }

The envelope is applied by a renderer attached **only to v1 views** (see
``api.viewsets.BaseAPIView`` / the auth views), so the separate ``alerts`` API
keeps its native DRF shape and nothing about the web app changes.
"""
from __future__ import annotations

from typing import Any

from rest_framework.renderers import JSONRenderer


class EnvelopeJSONRenderer(JSONRenderer):
    """Wrap the serialized body in the standard envelope."""

    def render(self, data: Any, accepted_media_type=None, renderer_context=None):
        renderer_context = renderer_context or {}
        response = renderer_context.get("response")
        status_code = getattr(response, "status_code", 200) or 200

        if status_code >= 400:
            payload = {
                "success": False,
                "data": None,
                "error": _normalize_error(data),
                "meta": {},
            }
        else:
            meta: dict = {}
            body = data
            # Paginators hand us {"results": [...], "_pagination": {...}} — lift
            # the pagination block into meta and expose the rows as data.
            if isinstance(data, dict) and "_pagination" in data:
                meta["pagination"] = data.get("_pagination")
                body = data.get("results")
            payload = {"success": True, "data": body, "error": None, "meta": meta}

        return super().render(payload, accepted_media_type, renderer_context)


def _normalize_error(data: Any) -> dict:
    """Coerce whatever the exception handler produced into the error shape.

    The v1 exception handler already emits ``{code, message, fields}``; this is
    a defensive fallback for anything that slips through (e.g. a raw dict).
    """
    if isinstance(data, dict) and "code" in data and "message" in data:
        return data
    if isinstance(data, dict) and "detail" in data:
        return {"code": "error", "message": str(data["detail"]), "fields": {}}
    if isinstance(data, dict):
        return {"code": "validation_error", "message": "Validation failed.", "fields": data}
    return {"code": "error", "message": str(data), "fields": {}}
