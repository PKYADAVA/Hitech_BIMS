"""Threshold and connectivity alert evaluation.

Alerts are self-contained here (not in the ``notification`` app, which is
SMS-template-only today) - in-app alert list/badge only for this phase. A
later phase can call ``notification.services.sms_service.get_sms_service()``
from here without any model changes.
"""

from datetime import timedelta

from django.utils import timezone

from .. import conf
from ..models import Alert, Hub, Sensor


class AlertService:
    def evaluate(self, sensor: Sensor) -> None:
        """Open/resolve temperature, humidity, and battery alerts for one sensor's latest reading."""
        thresholds = sensor.effective_thresholds()
        temp_min = thresholds["temp_min"]
        temp_max = thresholds["temp_max"]
        humidity_min = thresholds["humidity_min"]
        humidity_max = thresholds["humidity_max"]
        battery_low_pct = thresholds["battery_low_pct"]

        # chr(176) == the degree sign, built at runtime rather than written
        # as a literal character in this file: Windows Python without
        # PYTHONUTF8=1 has been observed mangling a literal degree sign in
        # source files into a replacement character at import time.
        deg = chr(176)
        self._check_bound(sensor, "temp_high", sensor.temperature_c is not None and sensor.temperature_c > temp_max,
                           sensor.temperature_c, f"Temperature {sensor.temperature_c}{deg}C above max {temp_max}{deg}C")
        self._check_bound(sensor, "temp_low", sensor.temperature_c is not None and sensor.temperature_c < temp_min,
                           sensor.temperature_c, f"Temperature {sensor.temperature_c}{deg}C below min {temp_min}{deg}C")
        self._check_bound(sensor, "humidity_high", sensor.humidity_pct is not None and sensor.humidity_pct > humidity_max,
                           sensor.humidity_pct, f"Humidity {sensor.humidity_pct}% above max {humidity_max}%")
        self._check_bound(sensor, "humidity_low", sensor.humidity_pct is not None and sensor.humidity_pct < humidity_min,
                           sensor.humidity_pct, f"Humidity {sensor.humidity_pct}% below min {humidity_min}%")
        self._check_bound(sensor, "battery_low", sensor.battery_pct is not None and sensor.battery_pct <= battery_low_pct,
                           sensor.battery_pct, f"Battery {sensor.battery_pct}% at/below threshold {battery_low_pct}%")

    def evaluate_offline_all(self) -> None:
        """Flip status to offline and raise connectivity alerts for stale hubs/sensors.

        Runs once per poll_sensors invocation across every active hub/sensor,
        independent of which ones produced a fresh reading this cycle - an
        offline device produces no reading at all, so evaluate() alone would
        never see it.
        """
        config = conf.load_config()
        cutoff = timezone.now() - timedelta(minutes=config.offline_after_minutes)

        for hub in Hub.objects.filter(is_active=True):
            is_stale = hub.last_seen is None or hub.last_seen < cutoff
            if is_stale and hub.status != "offline":
                hub.status = "offline"
                hub.save(update_fields=["status", "updated_at"])
                self._open_alert(None, hub, "hub_offline", f"Hub '{hub.name}' has not reported in over {config.offline_after_minutes} min")
            elif not is_stale:
                self._resolve_alert(None, hub, "hub_offline")

        for sensor in Sensor.objects.filter(is_active=True).select_related("hub"):
            is_stale = sensor.last_update is None or sensor.last_update < cutoff
            if is_stale and sensor.status != "offline":
                sensor.status = "offline"
                sensor.save(update_fields=["status", "updated_at"])
                self._open_alert(sensor, sensor.hub, "sensor_offline", f"Sensor '{sensor}' has not reported in over {config.offline_after_minutes} min")
            elif not is_stale:
                self._resolve_alert(sensor, sensor.hub, "sensor_offline")

    def _check_bound(self, sensor: Sensor, alert_type: str, is_breached: bool, value, message: str) -> None:
        if is_breached:
            self._open_alert(sensor, sensor.hub, alert_type, message, value)
        else:
            self._resolve_alert(sensor, sensor.hub, alert_type)

    @staticmethod
    def _open_alert(sensor, hub, alert_type: str, message: str, value=None) -> None:
        already_open = Alert.objects.filter(
            sensor=sensor, hub=hub, alert_type=alert_type, resolved_at__isnull=True,
        ).exists()
        if not already_open:
            Alert.objects.create(sensor=sensor, hub=hub, alert_type=alert_type, message=message, value=value)

    @staticmethod
    def _resolve_alert(sensor, hub, alert_type: str) -> None:
        Alert.objects.filter(
            sensor=sensor, hub=hub, alert_type=alert_type, resolved_at__isnull=True,
        ).update(resolved_at=timezone.now())
