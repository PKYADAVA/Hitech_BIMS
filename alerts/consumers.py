"""Django Channels consumer for real-time alert delivery (optional).

**Not imported anywhere at startup** — Channels is not currently a project
dependency, so importing this module is only safe once ``channels`` is
installed. To enable real-time alerts:

1. ``pip install channels channels-redis`` and add ``"channels"`` to
   ``INSTALLED_APPS``; set ``ASGI_APPLICATION`` and a ``CHANNEL_LAYERS`` config.
2. Include :data:`alerts.routing.websocket_urlpatterns` in your ASGI router.
3. Set ``ALERT_SETTINGS["ENABLE_WEBSOCKET"] = True``.

The :class:`~alerts.channels.WebSocketChannel` then broadcasts each alert to
``alerts_all`` (staff dashboards) and ``alerts_user_<id>`` (the actor). This
consumer subscribes the connecting user to the groups they are allowed to hear.
"""
from __future__ import annotations

try:
    from channels.generic.websocket import AsyncJsonWebsocketConsumer
except Exception:  # pragma: no cover - channels not installed
    AsyncJsonWebsocketConsumer = object  # type: ignore


class AlertConsumer(AsyncJsonWebsocketConsumer):  # pragma: no cover - needs channels
    """Streams alerts to a connected, authenticated user."""

    async def connect(self):
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            await self.close()
            return
        self.groups_joined = [f"alerts_user_{user.pk}"]
        if user.is_staff or user.is_superuser:
            self.groups_joined.append("alerts_all")
        for group in self.groups_joined:
            await self.channel_layer.group_add(group, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        for group in getattr(self, "groups_joined", []):
            await self.channel_layer.group_discard(group, self.channel_name)

    async def alert_message(self, event):
        """Handler for ``{"type": "alert.message"}`` fan-out from the channel layer."""
        await self.send_json(event["content"])
