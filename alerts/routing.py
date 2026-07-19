"""ASGI/WebSocket routing for real-time alerts (optional — see consumers.py).

Import this from your project's ASGI router *only after* Channels is installed::

    from channels.routing import ProtocolTypeRouter, URLRouter
    from alerts.routing import websocket_urlpatterns

    application = ProtocolTypeRouter({
        "websocket": AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
        ...
    })
"""
from __future__ import annotations

try:
    from django.urls import re_path

    from .consumers import AlertConsumer

    websocket_urlpatterns = [
        re_path(r"ws/alerts/$", AlertConsumer.as_asgi()),
    ]
except Exception:  # pragma: no cover - channels/consumer unavailable
    websocket_urlpatterns = []
