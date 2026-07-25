"""Expo push helper — sends notifications to registered device tokens.

Uses Expo's HTTP push API (https://exp.host/--/api/v2/push/send), so no
Firebase/APNs credentials are needed for Expo-managed builds. Best-effort:
network/gateway errors are swallowed into the return value, never raised.
"""
from __future__ import annotations

from typing import Iterable, Optional

import requests

_EXPO_URL = "https://exp.host/--/api/v2/push/send"


def send_push(tokens: Iterable[str], title: str, body: str,
              data: Optional[dict] = None) -> dict:
    valid = [t for t in tokens if t]
    if not valid:
        return {"sent": 0, "error": "No device tokens."}
    messages = [
        {"to": t, "title": title, "body": body, "data": data or {}, "sound": "default"}
        for t in valid
    ]
    try:
        resp = requests.post(
            _EXPO_URL, json=messages, timeout=15,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        return {
            "sent": len(valid),
            "status": resp.status_code,
            "response": resp.json() if resp.content else None,
        }
    except requests.RequestException as exc:
        return {"sent": 0, "error": str(exc)}
