"""Environmental Monitoring views.

Follows this project's existing convention (see hatchery_master/views.py):
function-based views, ``@login_required``, Django messages for feedback,
``full_clean()`` + ``save()`` for validation, no ``forms.py``. JSON endpoints
return hand-built ``JsonResponse`` payloads (see notification/views.py's
``SmsTemplateAPI``) rather than DRF serializers, since DRF isn't wired into
INSTALLED_APPS.
"""

import json
import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from hatchery_master.models import Setter

from .models import Alert, AlertThresholdDefaults, Hub, Sensor, SensorReading, TapoAccount
from .services.dto import ChildReading
from .services.sensor_service import SensorService


# --------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------- #

@login_required(login_url="login")
def dashboard(request):
    """Render the Environmental Monitoring dashboard shell (cards + charts)."""
    hubs = Hub.objects.all()
    open_alerts = Alert.objects.filter(resolved_at__isnull=True)

    context = {
        "total_hubs": hubs.count(),
        "online_hubs": hubs.filter(status="online").count(),
        "offline_hubs": hubs.filter(status="offline").count(),
        "total_sensors": Sensor.objects.count(),
        "temperature_alerts": open_alerts.filter(alert_type__in=["temp_high", "temp_low"]).count(),
        "humidity_alerts": open_alerts.filter(alert_type__in=["humidity_high", "humidity_low"]).count(),
        "low_battery_sensors": open_alerts.filter(alert_type="battery_low").count(),
        "communication_errors": (
            hubs.filter(status="error").count()
            + open_alerts.filter(alert_type__in=["sensor_offline", "hub_offline"]).count()
        ),
        "sensors": Sensor.objects.select_related("setter", "hub").filter(is_active=True),
    }
    return render(request, "environmental_dashboard.html", context)


@login_required(login_url="login")
def sensor_status_api(request):
    """Polled every 5s by the dashboard; returns cached sensor rows."""
    sensors = Sensor.objects.select_related("setter", "hub").filter(is_active=True)
    payload = [_sensor_to_dict(sensor) for sensor in sensors]
    return JsonResponse({"sensors": payload})


@login_required(login_url="login")
def sensor_history_api(request, id):
    """Feeds a sensor's history chart with its most recent readings."""
    sensor = get_object_or_404(Sensor, id=id)
    readings = sensor.readings.order_by("-timestamp")[:200]
    payload = [
        {
            "timestamp": reading.timestamp.isoformat(),
            "temperature_c": float(reading.temperature_c) if reading.temperature_c is not None else None,
            "humidity_pct": float(reading.humidity_pct) if reading.humidity_pct is not None else None,
            "battery_pct": reading.battery_pct,
        }
        for reading in reversed(readings)
    ]
    return JsonResponse({"sensor": sensor.alias or str(sensor), "readings": payload})


def _sensor_to_dict(sensor: Sensor) -> dict:
    return {
        "id": sensor.id,
        "alias": sensor.alias or str(sensor),
        "hub": sensor.hub.name,
        "setter": sensor.setter.setter_no if sensor.setter else None,
        "temperature_c": float(sensor.temperature_c) if sensor.temperature_c is not None else None,
        "humidity_pct": float(sensor.humidity_pct) if sensor.humidity_pct is not None else None,
        "battery_pct": sensor.battery_pct,
        "status": sensor.status,
        "last_update": sensor.last_update.strftime("%Y-%m-%d %H:%M:%S") if sensor.last_update else None,
        "temp_out_of_range": sensor.is_temperature_out_of_range,
        "humidity_out_of_range": sensor.is_humidity_out_of_range,
        "battery_low": sensor.is_battery_low,
    }


# --------------------------------------------------------------------- #
# Ingest (push from an on-site collector script, token-authenticated)
# --------------------------------------------------------------------- #

@csrf_exempt
@require_POST
def ingest_hub_reading(request):
    """Accept a hub+children reading payload pushed by a standalone on-site
    collector script (see environmental_monitoring/collector/hub_collector.py).

    Machine-to-machine endpoint: authenticated by a per-hub bearer token
    (Hub.api_token), not a Django session, since the collector never logs in -
    hence @csrf_exempt. Reuses the same SensorService the local poll_sensors
    path uses, so alert evaluation/history/calibration all behave identically
    regardless of whether a hub is polled locally or pushes over HTTPS.
    """
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[len("Bearer "):].strip() if auth_header.startswith("Bearer ") else ""
    if not token:
        return JsonResponse({"error": "Missing bearer token."}, status=401)

    hub = Hub.objects.filter(api_token=token).first()
    if hub is None:
        return JsonResponse({"error": "Invalid token."}, status=401)
    if not hub.is_active:
        return JsonResponse({"error": "Hub is inactive."}, status=403)

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON payload."}, status=400)

    hub_payload = payload.get("hub") or {}
    children_payload = payload.get("children") or []

    if hub_payload.get("device_id"):
        hub.device_id = hub_payload["device_id"]
    hub.alias = hub_payload.get("alias", hub.alias)
    hub.model = hub_payload.get("model", hub.model)
    hub.mac_address = hub_payload.get("mac", hub.mac_address)
    hub.firmware_version = hub_payload.get("firmware_version", hub.firmware_version)
    hub.signal_strength = hub_payload.get("rssi", hub.signal_strength)
    hub.ip_address = hub_payload.get("host") or hub.ip_address
    hub.status = "online"
    hub.last_seen = timezone.now()
    hub.save(update_fields=[
        "device_id", "alias", "model", "mac_address", "firmware_version",
        "signal_strength", "ip_address", "status", "last_seen", "updated_at",
    ])

    readings = [
        ChildReading(
            device_id=child.get("device_id", ""),
            model=child.get("model", ""),
            alias=child.get("alias", ""),
            temperature_c=child.get("temperature_c"),
            humidity_pct=child.get("humidity_pct"),
            battery_pct=child.get("battery_pct"),
            battery_low=bool(child.get("battery_low", False)),
            rssi=child.get("rssi"),
            is_online=bool(child.get("is_online", True)),
            last_alarm_event=child.get("last_alarm_event"),
            last_alarm_at_epoch=child.get("last_alarm_at_epoch"),
        )
        for child in children_payload
        if child.get("device_id")
    ]
    SensorService().sync_readings(hub, readings)

    return JsonResponse({"message": "ok", "synced": len(readings)})


# --------------------------------------------------------------------- #
# Tapo Account (master settings, singleton record)
# --------------------------------------------------------------------- #

@login_required(login_url="login")
def tapo_account_settings(request):
    account = TapoAccount.get_solo()

    if request.method == "POST":
        account.email = request.POST.get("email", "").strip()
        account.password = request.POST.get("password", "").strip() or account.password
        try:
            account.full_clean()
            account.save()
            messages.success(request, "Tapo account updated successfully.")
            return redirect("env_tapo_account")
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))

    return render(request, "tapo_account_form.html", {"account": account})


@login_required(login_url="login")
def default_thresholds_settings(request):
    thresholds = AlertThresholdDefaults.get_solo()

    if request.method == "POST":
        thresholds.temp_min = request.POST.get("temp_min") or thresholds.temp_min
        thresholds.temp_max = request.POST.get("temp_max") or thresholds.temp_max
        thresholds.humidity_min = request.POST.get("humidity_min") or thresholds.humidity_min
        thresholds.humidity_max = request.POST.get("humidity_max") or thresholds.humidity_max
        thresholds.battery_low_pct = request.POST.get("battery_low_pct") or thresholds.battery_low_pct
        try:
            thresholds.full_clean()
            thresholds.save()
            messages.success(request, "Default thresholds updated successfully.")
            return redirect("env_default_thresholds")
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))

    return render(request, "default_thresholds_form.html", {"thresholds": thresholds})


# --------------------------------------------------------------------- #
# Hub management
# --------------------------------------------------------------------- #

def _apply_hub_fields(hub: Hub, request):
    hub.name = request.POST.get("name", "").strip()
    hub.ip_address = request.POST.get("ip_address", "").strip()
    hub.mac_address = request.POST.get("mac_address", "").strip()
    device_id = request.POST.get("device_id", "").strip()
    hub.device_id = device_id or hub.device_id or f"pending-{uuid.uuid4()}"
    hub.is_active = bool(request.POST.get("is_active"))


@login_required(login_url="login")
def hub_list(request):
    hubs = Hub.objects.all()
    return render(request, "hub_list.html", {"hubs": hubs})


@login_required(login_url="login")
def create_hub(request):
    if request.method == "POST":
        hub = Hub(is_active=True)
        _apply_hub_fields(hub, request)
        try:
            hub.full_clean()
            hub.save()
            messages.success(request, "Hub added successfully.")
            return redirect("env_hub_list")
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))

    return render(request, "hub_form.html", {})


@login_required(login_url="login")
def edit_hub(request, id):
    hub = get_object_or_404(Hub, id=id)
    if request.method == "POST":
        _apply_hub_fields(hub, request)
        try:
            hub.full_clean()
            hub.save()
            messages.success(request, "Hub updated successfully.")
            return redirect("env_hub_list")
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))

    return render(request, "hub_form.html", {"hub": hub})


@login_required(login_url="login")
@require_POST
def delete_hub(request, id):
    hub = get_object_or_404(Hub, id=id)
    hub.delete()
    messages.success(request, "Hub deleted successfully.")
    return redirect("env_hub_list")


@login_required(login_url="login")
@require_POST
def regenerate_hub_token(request, id):
    hub = get_object_or_404(Hub, id=id)
    hub.regenerate_api_token()
    messages.success(request, "API token regenerated. Update the collector script's configuration with the new token.")
    return redirect("env_hub_edit", id=hub.id)


# --------------------------------------------------------------------- #
# Sensor management (mapping to a Setter, calibration, thresholds)
# --------------------------------------------------------------------- #

@login_required(login_url="login")
def sensor_list(request):
    sensors = Sensor.objects.select_related("hub", "setter").all()
    return render(request, "sensor_list.html", {"sensors": sensors})


@login_required(login_url="login")
def edit_sensor(request, id):
    sensor = get_object_or_404(Sensor, id=id)
    if request.method == "POST":
        setter_id = request.POST.get("setter")
        sensor.setter = Setter.objects.filter(id=setter_id).first() if setter_id else None
        sensor.alias = request.POST.get("alias", "").strip()
        sensor.calibration_offset_temp = request.POST.get("calibration_offset_temp") or 0
        sensor.calibration_offset_humidity = request.POST.get("calibration_offset_humidity") or 0
        sensor.temp_min = request.POST.get("temp_min") or None
        sensor.temp_max = request.POST.get("temp_max") or None
        sensor.humidity_min = request.POST.get("humidity_min") or None
        sensor.humidity_max = request.POST.get("humidity_max") or None
        sensor.battery_low_pct = request.POST.get("battery_low_pct") or None
        sensor.is_active = bool(request.POST.get("is_active"))
        try:
            sensor.full_clean()
            sensor.save()
            messages.success(request, "Sensor updated successfully.")
            return redirect("env_sensor_list")
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))

    return render(request, "sensor_form.html", {
        "sensor": sensor,
        "setters": Setter.objects.filter(is_active=True).select_related("hatchery"),
    })


# --------------------------------------------------------------------- #
# Alerts
# --------------------------------------------------------------------- #

@login_required(login_url="login")
def alert_list(request):
    alerts = Alert.objects.select_related("sensor", "hub").all()[:500]
    return render(request, "alert_list.html", {"alerts": alerts})


@login_required(login_url="login")
@require_POST
def acknowledge_alert(request, id):
    alert = get_object_or_404(Alert, id=id)
    alert.is_acknowledged = True
    alert.acknowledged_by = request.user
    alert.save(update_fields=["is_acknowledged", "acknowledged_by"])
    messages.success(request, "Alert acknowledged.")
    return redirect("env_alert_list")


@login_required(login_url="login")
@require_POST
def clear_all_alerts(request):
    deleted_count, _ = Alert.objects.all().delete()
    messages.success(request, f"Cleared {deleted_count} alert(s).")
    return redirect("env_alert_list")
