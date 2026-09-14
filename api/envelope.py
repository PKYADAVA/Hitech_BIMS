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


#: Statuses that must not carry a message body. RFC 9110: a 204 response ends
#: at the headers, and a 304 carries none either.
BODYLESS = frozenset({204, 304})


class EnvelopeJSONRenderer(JSONRenderer):
    """Wrap the serialized body in the standard envelope."""

    def render(self, data: Any, accepted_media_type=None, renderer_context=None):
        renderer_context = renderer_context or {}
        response = renderer_context.get("response")
        status_code = getattr(response, "status_code", 200) or 200

        # Nothing at all on a 204, envelope included.
        #
        # Wrapping one produced `204 No Content` with `Content-Length: 51`,
        # which is a response that contradicts itself. A client or proxy that
        # believes the status stops reading at the headers, so those 51 bytes
        # stay in the connection and are read as the beginning of the next
        # request on it — whose request line is then `{"success": true, ...`.
        # nginx answers that with **505 HTTP Version Not Supported**, which is
        # how this surfaced: the first DELETE on a page worked, the second one
        # failed, and reloading fixed it because the reload opened fresh
        # connections. Only behind a proxy; the dev server is forgiving enough
        # to hide it.
        #
        # Every v1 DELETE was affected, the phone's included — the web app had
        # simply never issued one until the bird sale evidence card did.
        if status_code in BODYLESS:
            return b""

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
