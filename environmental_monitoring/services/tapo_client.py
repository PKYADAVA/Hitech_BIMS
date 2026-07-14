"""The only module in this project that imports ``kasa``.

Wraps python-kasa's asyncio-native API behind a synchronous interface so
Django views, management commands, and the rest of the service layer never
touch asyncio or ``kasa.*`` types/exceptions directly. New Tapo child device
types (T315, T100, T110, S200) need no changes here - ``fetch_hub_and_children``
already reads whatever children the hub reports.
"""

import asyncio
import logging

from kasa import Credentials, Device, Discover, KasaException, Module

from .dto import ChildReading, HubInfo

logger = logging.getLogger("environmental_monitoring.tapo")


class TapoConnectionError(Exception):
    """Raised when the H100 hub can't be reached or authenticated against."""


class TapoHubClient:
    """Talks to exactly one H100 hub, identified by its current LAN IP."""

    def __init__(self, host: str, username: str, password: str):
        self._host = host
        self._credentials = Credentials(username=username, password=password)

    def fetch_hub_and_children(self) -> tuple[HubInfo, list[ChildReading]]:
        """Connect, read the hub and its children, and disconnect. Synchronous entrypoint."""
        return asyncio.run(self._fetch())

    async def _fetch(self) -> tuple[HubInfo, list[ChildReading]]:
        device = await self._connect_with_retry()
        try:
            hub_info = HubInfo(
                device_id=device.device_id,
                alias=device.alias or "",
                model=device.model or "H100",
                mac=device.mac or "",
                host=self._host,
                firmware_version=(device.hw_info or {}).get("sw_ver", ""),
                rssi=device.rssi,
            )
            readings = [self._read_child(child) for child in device.children]
            return hub_info, readings
        finally:
            await device.disconnect()

    async def _connect_with_retry(self) -> Device:
        # Discover.discover_single (rather than Device.connect with a bare
        # DeviceConfig) sends a discovery probe first so python-kasa detects
        # this device's actual protocol/connection type - H100 uses the
        # KLAP/SMART protocol over HTTPS, not the legacy IOT port-9999
        # protocol Device.connect otherwise defaults to guessing.
        device = await self._discover_with_retry()
        await device.update()
        return device

    async def _discover_with_retry(self) -> Device:
        try:
            device = await Discover.discover_single(
                self._host, credentials=self._credentials, discovery_timeout=8,
            )
        except KasaException as first_error:
            logger.warning("Tapo discover failed for %s, retrying once: %s", self._host, first_error)
            device = None

        if device is None:
            try:
                device = await Discover.discover_single(
                    self._host, credentials=self._credentials, discovery_timeout=8,
                )
            except KasaException as second_error:
                raise TapoConnectionError(
                    f"Could not connect to hub at {self._host}: {second_error}"
                ) from second_error

        if device is None:
            raise TapoConnectionError(f"No device found at {self._host}")
        return device

    @staticmethod
    def _read_child(child: Device) -> ChildReading:
        temperature_module = child.modules.get(Module.TemperatureSensor)
        humidity_module = child.modules.get(Module.HumiditySensor)
        battery_module = child.modules.get(Module.BatterySensor)
        trigger_logs_module = child.modules.get(Module.TriggerLogs)

        # Read the raw child info dict directly rather than through the
        # kasa module properties: on this firmware, BatterySensor.battery
        # does an unguarded dict lookup for a "battery_percentage" key this
        # device never reports (it only exposes the "at_low_battery" flag),
        # which raises KeyError. Going through .data.get(...) degrades
        # gracefully to None instead of crashing the whole poll.
        raw = (temperature_module or humidity_module or battery_module)
        raw_data = raw.data if raw is not None else {}

        raw_temp = raw_data.get("current_temp")
        temperature_c = None
        if raw_temp is not None:
            # H100/T310 can be configured to report in Fahrenheit - the
            # "temperature" field on the model is always Celsius, so convert.
            if str(raw_data.get("temp_unit", "celsius")).lower().startswith("f"):
                temperature_c = (raw_temp - 32) * 5 / 9
            else:
                temperature_c = raw_temp

        # The hub's own alarm/threshold event log for this child (e.g.
        # "tooHumid") - a genuinely device-sourced timestamp, distinct from
        # when *we* last polled. logs[0] is the most recent entry (descending
        # order); absent entirely if this sensor has never crossed a
        # threshold the hub tracks.
        last_alarm_event = None
        last_alarm_at_epoch = None
        if trigger_logs_module is not None:
            logs = trigger_logs_module.data.get("logs") or []
            if logs:
                last_alarm_event = logs[0].get("event")
                last_alarm_at_epoch = logs[0].get("timestamp")

        return ChildReading(
            device_id=child.device_id,
            model=child.model or "",
            alias=child.alias or "",
            temperature_c=temperature_c,
            humidity_pct=raw_data.get("current_humidity"),
            battery_pct=raw_data.get("battery_percentage"),
            battery_low=bool(raw_data.get("at_low_battery", False)),
            rssi=child.rssi,
            is_online=raw_data.get("status", "online") == "online",
            last_alarm_event=last_alarm_event,
            last_alarm_at_epoch=last_alarm_at_epoch,
        )
