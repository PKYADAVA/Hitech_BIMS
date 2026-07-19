"""Pure helper functions — no Django models imported at module load.

Kept dependency-light and side-effect free so they are trivially unit-testable
and safe to import from anywhere in the module (context, services, signals).
"""
from __future__ import annotations

import datetime
import decimal
import uuid
from typing import Any, Optional

from django.db import models

from .conf import config


# --------------------------------------------------------------------------- #
# Request / actor introspection
# --------------------------------------------------------------------------- #
def get_client_ip(request: Any) -> Optional[str]:
    """Best-effort client IP, honouring a single proxy hop.

    ``X-Forwarded-For`` is a client-controlled header; only trust it when a
    reverse proxy is known to set it. This project runs behind Nginx (see
    ``SECURE_PROXY_SSL_HEADER``), so the left-most entry is used.
    """
    if not hasattr(request, "META"):
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def get_user_role(user: Any) -> str:
    """Resolve a display role from the project's ``UserProfile``/groups."""
    profile = getattr(user, "userprofile", None)
    if profile is not None and getattr(profile, "role", None):
        return profile.role
    groups = getattr(user, "groups", None)
    if groups is not None:
        names = list(groups.values_list("name", flat=True)[:3])
        if names:
            return ", ".join(names)
    if getattr(user, "is_superuser", False):
        return "Superuser"
    return ""


def get_user_department(user: Any) -> str:
    profile = getattr(user, "userprofile", None)
    if profile is not None and getattr(profile, "department", None):
        return profile.department
    return ""


# --------------------------------------------------------------------------- #
# User-agent parsing (dependency-free, deliberately simple)
# --------------------------------------------------------------------------- #
_BROWSERS = [
    ("Edg", "Edge"),
    ("OPR", "Opera"),
    ("Opera", "Opera"),
    ("Chrome", "Chrome"),
    ("Firefox", "Firefox"),
    ("Safari", "Safari"),
    ("MSIE", "Internet Explorer"),
    ("Trident", "Internet Explorer"),
]
_OSES = [
    ("Windows NT 10", "Windows 10/11"),
    ("Windows", "Windows"),
    ("Mac OS X", "macOS"),
    ("Android", "Android"),
    ("iPhone", "iOS"),
    ("iPad", "iPadOS"),
    ("Linux", "Linux"),
]


def parse_user_agent(ua: str) -> tuple[str, str, str]:
    """Return ``(browser, os, device)`` from a UA string.

    A tiny hand-rolled parser is used on purpose: it covers >99% of real
    traffic with zero extra dependencies. Swap in ``user-agents`` here if
    richer detection is ever required — the call site never changes.
    """
    if not ua:
        return "", "", ""
    browser = next((label for token, label in _BROWSERS if token in ua), "Unknown")
    # Chrome UAs also contain "Safari"; ordering above resolves that.
    os_name = next((label for token, label in _OSES if token in ua), "Unknown")
    device = "Mobile" if any(t in ua for t in ("Mobile", "Android", "iPhone")) else "Desktop"
    return browser, os_name, device


# --------------------------------------------------------------------------- #
# Value serialisation & display
# --------------------------------------------------------------------------- #
def to_jsonable(value: Any) -> Any:
    """Coerce an arbitrary field value into something JSON-serialisable.

    Used for ``changed_fields`` / audit before-after snapshots so the JSON
    columns never choke on Decimals, dates, models, files, or UUIDs.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, models.Model):
        return str(value)
    # FieldFile and similar expose ``.name``.
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name
    return str(value)


def truncate(text: Any, length: Optional[int] = None) -> str:
    text = "" if text is None else str(text)
    limit = length or config.MAX_DISPLAY_LENGTH
    return text if len(text) <= limit else text[: limit - 1] + "…"


def object_display(instance: models.Model) -> str:
    """Human label for an instance, guarding against ``__str__`` that raises."""
    try:
        return truncate(str(instance))
    except Exception:  # pragma: no cover - defensive
        return f"{instance._meta.object_name} #{instance.pk}"


def model_label(model: type[models.Model]) -> str:
    """``app_label.ModelName`` — the canonical model identifier used everywhere."""
    return f"{model._meta.app_label}.{model._meta.object_name}"


def verbose_model_name(model: type[models.Model]) -> str:
    return str(model._meta.verbose_name).title()
