"""Plain data-transfer objects returned by the service layer.

Callers (views, the poll_sensors command, alert evaluation) work only with
these dataclasses - they never see ``kasa.*`` types, so swapping the
underlying Tapo client library later would not touch any calling code.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class HubInfo:
    device_id: str
    alias: str
    model: str
    mac: str
    host: str
    firmware_version: str
    rssi: int | None


@dataclass(frozen=True)
class ChildReading:
    device_id: str
    model: str
    alias: str
    temperature_c: float | None
    humidity_pct: float | None
    battery_pct: int | None
    battery_low: bool
    rssi: int | None
    is_online: bool
    last_alarm_event: str | None
    last_alarm_at_epoch: int | None
