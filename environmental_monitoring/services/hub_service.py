"""Hub-level polling: connects to one H100 via TapoHubClient and syncs its state."""

import logging

from django.utils import timezone

from .. import conf
from ..models import Hub
from .dto import ChildReading
from .tapo_client import TapoConnectionError, TapoHubClient

logger = logging.getLogger("environmental_monitoring.hub")


class HubService:
    def poll_hub(self, hub: Hub) -> list[ChildReading]:
        """Connect to ``hub``, refresh its cached fields, and return its children's readings.

        Never raises - failures are logged and the hub is marked ``error`` so
        one unreachable hub never aborts the rest of a poll_sensors run.
        """
        config = conf.load_config()
        client = TapoHubClient(hub.ip_address, config.tapo_username, config.tapo_password)
        try:
            hub_info, readings = client.fetch_hub_and_children()
        except TapoConnectionError as exc:
            logger.error("Poll failed for hub %s (%s): %s", hub.name, hub.ip_address, exc)
            hub.status = "error"
            hub.save(update_fields=["status", "updated_at"])
            return []

        if hub_info.device_id:
            hub.device_id = hub_info.device_id
        hub.alias = hub_info.alias
        hub.model = hub_info.model
        hub.mac_address = hub_info.mac
        hub.firmware_version = hub_info.firmware_version
        hub.signal_strength = hub_info.rssi
        hub.status = "online"
        hub.last_seen = timezone.now()
        hub.save(update_fields=[
            "device_id", "alias", "model", "mac_address", "firmware_version",
            "signal_strength", "status", "last_seen", "updated_at",
        ])
        return readings
