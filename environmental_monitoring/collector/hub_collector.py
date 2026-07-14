#!/usr/bin/env python3
"""Standalone on-site collector for one Tapo H100 hub.

Runs on a small always-on device (e.g. a Raspberry Pi) on the SAME LOCAL
NETWORK as the H100 hub - the hub's local Tapo protocol can't be reached from
the cloud. This script polls the hub via python-kasa, then pushes the reading
to the cloud ERP's ingest endpoint over HTTPS.

Deliberately has ZERO dependency on Django or the rest of this repo - it only
needs `python-kasa` and `requests` - so it can be copied to the Pi on its own:

    pip install -r requirements.txt   # see collector/requirements.txt
    python3 hub_collector.py

Configure via environment variables:
    HUB_HOST               LAN IP of the H100 hub, e.g. 192.168.1.9
    TAPO_ACCOUNT_EMAIL     Tapo cloud account email
    TAPO_ACCOUNT_PASSWORD  Tapo cloud account password
    ERP_INGEST_URL         e.g. https://bims.yourcompany.com/environmental-monitoring/api/ingest/
    HUB_API_TOKEN          shown on this hub's edit page in the ERP (Hubs > Edit)

Schedule with cron to run every minute:
    * * * * * /usr/bin/python3 /home/pi/hub_collector.py >> /home/pi/hub_collector.log 2>&1
"""

import asyncio
import os
import sys

import requests
from kasa import Credentials, Discover, KasaException, Module


def read_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"Missing required environment variable: {name}", file=sys.stderr)
        sys.exit(1)
    return value


async def fetch_hub_and_children(host: str, username: str, password: str):
    """Mirrors environmental_monitoring/services/tapo_client.py's reading logic,
    duplicated here (rather than imported) so this file has no dependency on
    Django or the rest of the repo being present on the collector device."""
    creds = Credentials(username=username, password=password)
    # Discover.discover_single (rather than Device.connect with a bare
    # DeviceConfig) probes the device first so python-kasa detects the H100's
    # actual KLAP/SMART protocol - Device.connect otherwise defaults to
    # guessing the legacy IOT protocol (port 9999), which this hub refuses.
    device = await Discover.discover_single(host, credentials=creds, discovery_timeout=8)
    if device is None:
        raise KasaException(f"No device found at {host}")
    try:
        await device.update()
        hub_payload = {
            "device_id": device.device_id,
            "alias": device.alias or "",
            "model": device.model or "H100",
            "mac": device.mac or "",
            "host": host,
            "firmware_version": (device.hw_info or {}).get("sw_ver", ""),
            "rssi": device.rssi,
        }
        children_payload = []
        for child in device.children:
            temperature_module = child.modules.get(Module.TemperatureSensor)
            humidity_module = child.modules.get(Module.HumiditySensor)
            battery_module = child.modules.get(Module.BatterySensor)
            trigger_logs_module = child.modules.get(Module.TriggerLogs)
            # Read the raw child info dict directly: on this firmware,
            # BatterySensor.battery does an unguarded lookup for a
            # "battery_percentage" key this device never reports (it only
            # exposes "at_low_battery"), which raises KeyError. .data.get(...)
            # degrades gracefully to None instead of crashing.
            raw = temperature_module or humidity_module or battery_module
            raw_data = raw.data if raw is not None else {}

            raw_temp = raw_data.get("current_temp")
            temperature_c = None
            if raw_temp is not None:
                # H100/T310 can be configured to report in Fahrenheit - always
                # send Celsius to the ERP, converting when needed.
                if str(raw_data.get("temp_unit", "celsius")).lower().startswith("f"):
                    temperature_c = (raw_temp - 32) * 5 / 9
                else:
                    temperature_c = raw_temp

            # The hub's own alarm/threshold event log for this child (e.g.
            # "tooHumid") - genuinely device-sourced, distinct from when
            # *we* last polled. logs[0] is the most recent entry.
            last_alarm_event = None
            last_alarm_at_epoch = None
            if trigger_logs_module is not None:
                logs = trigger_logs_module.data.get("logs") or []
                if logs:
                    last_alarm_event = logs[0].get("event")
                    last_alarm_at_epoch = logs[0].get("timestamp")

            children_payload.append({
                "device_id": child.device_id,
                "model": child.model or "",
                "alias": child.alias or "",
                "temperature_c": temperature_c,
                "humidity_pct": raw_data.get("current_humidity"),
                "battery_pct": raw_data.get("battery_percentage"),
                "battery_low": bool(raw_data.get("at_low_battery", False)),
                "rssi": child.rssi,
                "is_online": raw_data.get("status", "online") == "online",
                "last_alarm_event": last_alarm_event,
                "last_alarm_at_epoch": last_alarm_at_epoch,
            })
        return hub_payload, children_payload
    finally:
        await device.disconnect()


def main():
    host = read_env("HUB_HOST")
    username = read_env("TAPO_ACCOUNT_EMAIL")
    password = read_env("TAPO_ACCOUNT_PASSWORD")
    ingest_url = read_env("ERP_INGEST_URL")
    token = read_env("HUB_API_TOKEN")

    try:
        hub_payload, children_payload = asyncio.run(fetch_hub_and_children(host, username, password))
    except KasaException as exc:
        print(f"Failed to poll hub at {host}: {exc}", file=sys.stderr)
        sys.exit(1)

    response = requests.post(
        ingest_url,
        json={"hub": hub_payload, "children": children_payload},
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    if response.status_code >= 400:
        print(f"Ingest failed: {response.status_code} {response.text}", file=sys.stderr)
        sys.exit(1)

    print(f"Synced {len(children_payload)} sensor reading(s) for hub {host}.")


if __name__ == "__main__":
    main()
