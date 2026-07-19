"""Ambient request context for signal receivers.

Django model signals do not receive the HTTP request, so a receiver cannot,
on its own, know *who* performed a change or *from where*. Rather than thread
the request through every ``save()`` call site, the middleware stashes it here
and signals read it back.

A :class:`contextvars.ContextVar` is used instead of a bare ``threading.local``
because it is coroutine-safe (correct under ASGI / async views) while behaving
exactly like thread-local storage under the classic WSGI worker model.
"""
from __future__ import annotations

import contextvars
import uuid
from dataclasses import dataclass
from typing import Any, Optional

_request_var: contextvars.ContextVar[Optional[Any]] = contextvars.ContextVar(
    "alerts_current_request", default=None
)
_actor_var: contextvars.ContextVar[Optional[Any]] = contextvars.ContextVar(
    "alerts_current_actor", default=None
)
_extra_var: contextvars.ContextVar[dict] = contextvars.ContextVar(
    "alerts_extra_meta", default={}
)


def set_current_request(request: Any) -> None:
    _request_var.set(request)
    if not getattr(request, "alerts_request_id", None):
        request.alerts_request_id = uuid.uuid4().hex


def get_current_request() -> Optional[Any]:
    return _request_var.get()


def clear_current_request() -> None:
    _request_var.set(None)
    _extra_var.set({})


def get_current_user() -> Optional[Any]:
    """Return the authenticated user for this context, if any.

    Falls back to an explicitly-set actor (used by management commands or
    background jobs that have no request but still want attribution).
    """
    request = _request_var.get()
    if request is not None:
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            return user
    return _actor_var.get()


def set_current_actor(user: Any) -> None:
    """Attribute changes to ``user`` outside of a request (e.g. Celery, cron)."""
    _actor_var.set(user)


def add_extra_meta(**kwargs: Any) -> None:
    """Attach ad-hoc metadata (e.g. ``reason=...``) to alerts in this context."""
    current = dict(_extra_var.get())
    current.update(kwargs)
    _extra_var.set(current)


def get_extra_meta() -> dict:
    return dict(_extra_var.get())


@dataclass(frozen=True)
class RequestSnapshot:
    """Immutable, serialisable view of the actor + request environment.

    Captured once per event so services never hold a reference to the live
    request object.
    """

    user_id: Optional[int] = None
    username: str = ""
    email: str = ""
    role: str = ""
    department: str = ""
    ip_address: Optional[str] = None
    user_agent: str = ""
    browser: str = ""
    os: str = ""
    device: str = ""
    session_id: str = ""
    request_id: str = ""
    timezone: str = ""


def capture_snapshot() -> RequestSnapshot:
    """Build a :class:`RequestSnapshot` from the current context."""
    # Imported lazily to avoid a circular import (utils imports nothing heavy,
    # but keeps the dependency graph one-directional).
    from .utils import (
        get_client_ip,
        get_user_department,
        get_user_role,
        parse_user_agent,
    )

    request = _request_var.get()
    user = get_current_user()

    snap: dict[str, Any] = {}
    if user is not None:
        snap.update(
            user_id=user.pk,
            username=getattr(user, "username", "") or "",
            email=getattr(user, "email", "") or "",
            role=get_user_role(user),
            department=get_user_department(user),
        )

    if request is not None:
        ua = request.META.get("HTTP_USER_AGENT", "") if hasattr(request, "META") else ""
        browser, os_name, device = parse_user_agent(ua)
        session = getattr(request, "session", None)
        snap.update(
            ip_address=get_client_ip(request),
            user_agent=ua[:512],
            browser=browser,
            os=os_name,
            device=device,
            session_id=getattr(session, "session_key", "") or "",
            request_id=getattr(request, "alerts_request_id", "") or "",
            timezone=request.META.get("HTTP_X_TIMEZONE", "") if hasattr(request, "META") else "",
        )

    return RequestSnapshot(**snap)
