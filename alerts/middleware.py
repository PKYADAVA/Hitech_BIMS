"""Middleware that publishes the active request into :mod:`alerts.context`.

Placed *after* ``AuthenticationMiddleware`` in ``MIDDLEWARE`` so ``request.user``
is populated by the time a model signal reads it. The ``finally`` guarantees
the context is cleared even if a view raises, so no request leaks into the next
one handled by the same worker thread.
"""
from __future__ import annotations

from typing import Callable

from django.http import HttpRequest, HttpResponse

from .context import clear_current_request, set_current_request


class AlertContextMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        set_current_request(request)
        try:
            return self.get_response(request)
        finally:
            clear_current_request()
