"""Applies polled child readings onto Sensor/SensorReading rows."""

import datetime
from decimal import Decimal

from django.utils import timezone as dj_timezone

from ..models import Hub, Sensor, SensorReading
from .alert_service import AlertService
from .dto import ChildReading


class SensorService:
    def __init__(self):
        self._alert_service = AlertService()

    def sync_readings(self, hub: Hub, readings: list[ChildReading]) -> None:
        for reading in readings:
            sensor, _created = Sensor.objects.get_or_create(
                device_id=reading.device_id,
                defaults={
                    "hub": hub,
                    "model": reading.model,
                    "alias": reading.alias,
                },
            )
            if sensor.hub_id != hub.id:
                sensor.hub = hub

            now = dj_timezone.now()

            sensor.alias = reading.alias or sensor.alias
            sensor.model = reading.model or sensor.model
            sensor.status = "online" if reading.is_online else "offline"
            update_fields = ["hub", "alias", "model", "status", "updated_at"]

            # The hub's own alarm/threshold event log is genuinely
            # device-sourced (not "did we successfully poll" like the fields
            # below) - update it whenever we have a newer entry, regardless
            # of the sensor's current live online/offline status.
            if reading.last_alarm_at_epoch and (
                sensor.last_alarm_at is None
                or reading.last_alarm_at_epoch > sensor.last_alarm_at.timestamp()
            ):
                sensor.last_alarm_event = reading.last_alarm_event or ""
                sensor.last_alarm_at = datetime.datetime.fromtimestamp(
                    reading.last_alarm_at_epoch, tz=datetime.timezone.utc,
                )
                update_fields += ["last_alarm_event", "last_alarm_at"]

            # A child reporting offline still comes back with whatever the hub
            # has cached (which may be from well before it went offline, or -
            # for a sensor we've never successfully read at all - nothing
            # meaningful whatsoever). Only overwrite the displayed reading and
            # advance last_update when the data is genuinely live, so an
            # offline sensor keeps showing its last real confirmed reading
            # (or blank, if it was never online) instead of a misleading
            # hub-cached value stamped with a fresh-looking timestamp.
            temperature_c = None
            humidity_pct = None
            if reading.is_online:
                temperature_c = self._apply_offset(reading.temperature_c, sensor.calibration_offset_temp)
                humidity_pct = self._apply_offset(reading.humidity_pct, sensor.calibration_offset_humidity)
                sensor.temperature_c = temperature_c
                sensor.humidity_pct = humidity_pct
                sensor.battery_pct = reading.battery_pct
                sensor.signal_strength = reading.rssi
                sensor.last_update = now
                update_fields += [
                    "temperature_c", "humidity_pct", "battery_pct",
                    "signal_strength", "last_update",
                ]
            sensor.save(update_fields=update_fields)

            if reading.is_online:
                SensorReading.objects.create(
                    sensor=sensor, hub=hub, timestamp=now,
                    temperature_c=temperature_c, humidity_pct=humidity_pct,
                    battery_pct=reading.battery_pct, signal_strength=reading.rssi,
                )

            self._alert_service.evaluate(sensor)

    @staticmethod
    def _apply_offset(value, offset: Decimal):
        if value is None:
            return None
        return Decimal(str(value)) + offset
