"""TrackWick (formerly TrackoLap) API adapter.

This is the only module that knows TrackWick's wire format. It converts
sync-engine calls into authenticated HTTP requests, validates responses and
returns :mod:`tracking.dtos` objects. Credentials never leave this module
and are never logged.

Authentication — common headers on **every** request (confirmed contract,
see the vendor API document):

    platform: API
    tlp-cid:  <Customer ID>            (Manager → Account Setting → API Config)
    tlp-t:    <timestamp, epoch ms>
    api-key:  <API key>

Provider-row mapping:
    * ``api_url``                     — vendor API base URL
    * ``api_key`` (encrypted)         — the ``api-key`` header value
    * ``extra_config["customer_id"]`` — the ``tlp-cid`` header value
    * ``extra_config["endpoints"]``   — optional per-kind overrides of
      :data:`DEFAULT_ENDPOINTS`, so path corrections are configuration, not
      code. Each entry is ``{"path": "...", "method": "GET"|"POST"}`` (or a
      bare path string, keeping the default method).
    * ``extra_config["timeout"]``     — HTTP timeout seconds (default 15).

The response parsers are deliberately alias-tolerant (``lat``/``latitude``,
epoch-ms/ISO datetimes, several envelope shapes) so minor payload-naming
differences are absorbed here rather than crashing the sync.
"""

import logging
import time
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal, InvalidOperation
from typing import List, Optional

import requests

from ..dtos import (
    AttendanceEvent,
    ConnectionTestResult,
    GeofenceRecord,
    HistoryPoint,
    LivePosition,
    ProviderEmployee,
    VisitRecord,
)
from ..exceptions import (
    TrackingAuthError,
    TrackingConfigurationError,
    TrackingPermanentError,
    TrackingTransientError,
)
from .base import TrackingProviderAdapter

logger = logging.getLogger("tracking.provider")

_TRANSIENT_HTTP_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
_AUTH_HTTP_STATUSES = frozenset({401, 403})

#: Endpoint paths relative to ``api_url``. The provider's API base URL must
#: be the bare host ``https://app.trackolap.com`` — paths carry their full
#: prefix because the vendor exposes two roots: ``cust/1/api/...`` for
#: resource APIs and ``integration/api/...`` for the integration feed.
#:
#: Confirmed from the account's official API document (2026-07-17):
#:   employees   cust/1/api/asset/list      GET, paginated (pt/pn/q); each
#:                                          record embeds latitude/longitude/
#:                                          lastGPS/lastHeartbeat, so it
#:                                          doubles as the live-location feed
#:                                          — no separate "live" endpoint
#:                                          exists or is needed.
#:   history     cust/1/api/asset/history   GET; params start_time/end_time
#:                                          (epoch ms) + asset_id (**the raw
#:                                          Mongo id from asset/list's "id"
#:                                          field, NOT the empId code**).
#:                                          Vendor caps end-start at < 24h,
#:                                          so the adapter chunks longer
#:                                          windows and loops one call per
#:                                          asset (asset_id is mandatory —
#:                                          there is no bulk/all-employees
#:                                          history call).
#: Deliberately NOT wired up as auto-sync kinds — the document defines no
#: bulk, dated, GPS-tagged fetch for either:
#:   * visits/tasks   no endpoint at all in the document (cust/1/api/task/list
#:                    exists but 403s — a separately licensed module the
#:                    account doesn't have).
#:   * attendance     cust/1/api/punch/in/out is a POST that RECORDS a punch
#:                    (pushes an event INTO TrackoLap — e.g. from a
#:                    biometric device — and returns a bare success/failure,
#:                    not history); integration/api/get?type=punchin/punchout
#:                    only answers "is this one employee punched in/out
#:                    right now", with no timestamp, coordinates, or
#:                    date-range support. Neither fits a pull-sync of dated
#:                    GPS attendance events.
#: An empty path disables a kind (the adapter drops the capability), which is
#: how both the above and any future unlicensed module are switched off per
#: provider — flip it back on via the endpoint-overrides box once a real
#: bulk endpoint is confirmed.
DEFAULT_ENDPOINTS = {
    "employees": {"path": "cust/1/api/asset/list", "method": "GET"},
    "live": {"path": "cust/1/api/asset/list", "method": "GET"},
    "history": {"path": "cust/1/api/asset/history", "method": "GET"},
    "visits": {"path": "", "method": "GET"},       # no bulk endpoint — see above
    "attendance": {"path": "", "method": "GET"},   # no bulk endpoint — see above
    "geofences": {"path": "", "method": "GET"},    # none known
}

#: Confirmed history query params (start_time/end_time epoch ms, asset_id).
#: Overridable via ``extra_config["param_names"]`` for the rare case the
#: vendor changes these.
HISTORY_PARAM_NAMES = {"from": "start_time", "to": "end_time", "employee": "asset_id"}

#: Placeholder param names for the still-unconfirmed windowed kinds
#: (visits/attendance) — only relevant if a future endpoint override enables
#: one of them; deliberately kept separate from HISTORY_PARAM_NAMES so
#: enabling, say, visits doesn't silently inherit history's field names.
GENERIC_PARAM_NAMES = {"from": "from", "to": "to", "employee": "eid"}

#: TrackoLap's own hard cap: end_time − start_time must be < 24h.
#: Kept at 23h55m so a same-day request never lands exactly on the boundary.
MAX_HISTORY_WINDOW = timedelta(hours=23, minutes=55)

#: asset/list page size (params: pt = page size, pn = zero-based page number).
ASSET_LIST_PAGE_SIZE = 200
#: Safety cap on pages fetched, so a pagination bug can't loop forever.
ASSET_LIST_MAX_PAGES = 100


def _ms(dt: datetime) -> int:
    """Datetime → epoch milliseconds (the vendor's timestamp convention)."""
    return int(dt.timestamp() * 1000)


def _first(payload: dict, *keys, default=None):
    """First present, non-None key from an alias list."""
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return default


def _to_datetime(value) -> Optional[datetime]:
    """Epoch ms/seconds or ISO-8601 string → aware UTC datetime."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 1e11 else value  # ms vs s heuristic
        return datetime.fromtimestamp(seconds, tz=dt_timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                return _to_datetime(float(value))
            except (TypeError, ValueError):
                return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt_timezone.utc)
        return parsed.astimezone(dt_timezone.utc)
    return None


def _to_decimal(value) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _to_float(value) -> Optional[float]:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _to_int(value) -> Optional[int]:
    try:
        return int(float(value)) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


class TrackWickProviderAdapter(TrackingProviderAdapter):
    """Talk to one TrackWick account, configured by one TrackingProvider row."""

    name = "trackwick"

    def __init__(self, provider, session: requests.Session = None):
        super().__init__(provider)
        self._session = session or requests.Session()
        config = provider.extra_config or {}
        self._customer_id = str(config.get("customer_id", "") or "").strip()
        self._timeout = int(config.get("timeout", 15))
        self._endpoints = self._merge_endpoints(config.get("endpoints") or {})
        overrides = config.get("param_names") or {}
        self._params = {**HISTORY_PARAM_NAMES, **overrides}
        self._generic_params = {**GENERIC_PARAM_NAMES, **overrides}
        # asset/list is fetched once per adapter instance (i.e. once per sync
        # cycle — see SyncService.sync_provider) and reused by employees/live/
        # history, since all three read from the same directory.
        self._asset_cache = None
        # Kinds without a usable path are dropped from capabilities so the
        # sync engine skips them instead of calling a known-missing endpoint.
        self.capabilities = frozenset(
            kind for kind in type(self).capabilities
            if self._endpoints.get(kind, {}).get("path")
        )

    # ------------------------------------------------------------- plumbing

    @staticmethod
    def _merge_endpoints(overrides: dict) -> dict:
        merged = {}
        for kind, default in DEFAULT_ENDPOINTS.items():
            override = overrides.get(kind)
            if isinstance(override, str):
                merged[kind] = {"path": override, "method": default["method"]}
            elif isinstance(override, dict):
                merged[kind] = {
                    "path": override.get("path", default["path"]),
                    "method": str(override.get("method", default["method"])).upper(),
                }
            else:
                merged[kind] = dict(default)
        return merged

    def _ensure_configured(self):
        missing = []
        if not self.provider.api_url:
            missing.append("API URL")
        if not self.provider.api_key:
            missing.append("API key")
        if not self._customer_id:
            missing.append("Customer ID (extra_config.customer_id)")
        if missing:
            raise TrackingConfigurationError(
                f"Provider '{self.provider.name}' is missing: {', '.join(missing)}. "
                "Both values come from Manager → Account Setting → API Config."
            )

    def _headers(self) -> dict:
        return {
            "platform": "API",
            "tlp-cid": self._customer_id,
            "tlp-t": str(int(time.time() * 1000)),
            "api-key": self.provider.api_key,
            "Accept": "application/json",
        }

    def _request(self, kind: str, params: dict = None) -> object:
        """Perform one authenticated call for a data kind; returns the payload."""
        self._ensure_configured()
        endpoint = self._endpoints[kind]
        url = f"{self.provider.api_url.rstrip('/')}/{endpoint['path'].lstrip('/')}"

        try:
            if endpoint["method"] == "POST":
                response = self._session.post(
                    url, json=params or {}, headers=self._headers(), timeout=self._timeout
                )
            else:
                response = self._session.get(
                    url, params=params or {}, headers=self._headers(), timeout=self._timeout
                )
        except requests.Timeout as exc:
            raise TrackingTransientError(
                f"TrackWick request timed out after {self._timeout}s ({endpoint['path']})."
            ) from exc
        except requests.RequestException as exc:
            raise TrackingTransientError(
                f"Network error contacting TrackWick ({endpoint['path']})."
            ) from exc

        return self._handle_response(response, endpoint["path"])

    def _handle_response(self, response, path: str):
        status = response.status_code
        if status in _AUTH_HTTP_STATUSES:
            raise TrackingAuthError(
                "TrackWick rejected the credentials (check Customer ID and API key).",
                error_code=str(status),
            )
        if status in _TRANSIENT_HTTP_STATUSES:
            raise TrackingTransientError(
                f"TrackWick returned HTTP {status} for '{path}'.", error_code=str(status)
            )
        if status == 404:
            raise TrackingPermanentError(
                f"TrackWick endpoint '{path}' was not found (HTTP 404). Align the "
                "endpoint path with the account's API document via the provider's "
                "endpoint overrides in Tracking Settings.",
                error_code="404",
            )
        if status >= 400:
            raise TrackingPermanentError(
                f"TrackWick returned HTTP {status} for '{path}'.", error_code=str(status)
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise TrackingPermanentError(
                f"TrackWick returned a non-JSON response for '{path}'."
            ) from exc
        return self._extract_data(body, path)

    @staticmethod
    def _extract_data(body, path: str):
        """Unwrap the response envelope.

        TrackWick's live envelope (observed against go.trackwick.com) is
        ``{"s": <bool>, "d": <data>}`` on success and
        ``{"s": false, "ed": "<error text>", "rc": <code>}`` on failure —
        failures arrive with HTTP 200, so the flag must be honoured here.
        Generic ``success/status`` + ``data/result/...`` shapes are also
        accepted for tolerance.
        """
        if isinstance(body, list):
            return body
        if isinstance(body, dict):
            flag = _first(body, "s", "success", "status")
            if flag in (False, "error", "ERROR", "failure", 0):
                message = str(_first(
                    body, "ed", "message", "error", "msg", default="request failed"))
                code = str(_first(body, "rc", "code", "errorCode", default=""))
                lowered = message.lower()
                if "not authorized" in lowered or "access error" in lowered \
                        or "unauthoriz" in lowered or "invalid api" in lowered:
                    raise TrackingAuthError(
                        f"TrackWick rejected the request for '{path}': {message} "
                        "(check Customer ID and API key).",
                        error_code=code, provider_response=body,
                    )
                raise TrackingPermanentError(
                    f"TrackWick reported an error for '{path}': {message}",
                    error_code=code, provider_response=body,
                )
            data = _first(body, "d", "data", "result", "rows", "list", "response")
            if data is not None:
                return data
            return body
        raise TrackingPermanentError(
            f"Unexpected TrackWick response type for '{path}': {type(body).__name__}."
        )

    @staticmethod
    def _as_records(data) -> List[dict]:
        """Normalise unwrapped data to a list of dicts."""
        if isinstance(data, dict):
            inner = _first(data, "items", "records", "rows", "list", "data")
            if isinstance(inner, list):
                data = inner
            else:
                data = [data]
        if not isinstance(data, list):
            return []
        return [record for record in data if isinstance(record, dict)]

    @staticmethod
    def _external_employee_id(record: dict) -> str:
        return str(
            _first(record, "eid", "employeeId", "employee_id", "userId",
                   "user_id", "empId", "id", default="")
        )

    # ------------------------------------------------------------ fetchers

    def test_connection(self) -> ConnectionTestResult:
        try:
            employees = self.fetch_employees()
        except TrackingConfigurationError as exc:
            return ConnectionTestResult(success=False, message=str(exc))
        except TrackingAuthError as exc:
            return ConnectionTestResult(success=False, message=str(exc))
        except (TrackingTransientError, TrackingPermanentError) as exc:
            return ConnectionTestResult(success=False, message=str(exc))
        return ConnectionTestResult(
            success=True,
            message=f"Connected. TrackWick reports {len(employees)} employee(s).",
            details={"employee_count": len(employees)},
        )

    def _load_assets(self) -> List[dict]:
        """The asset/list directory, fetched once (paginated) and cached.

        Both the employee directory and live positions are read off this one
        cached list — TrackoLap has no separate live-location endpoint;
        asset/list's own records carry latitude/longitude/lastGPS/
        lastHeartbeat. ``asset/history`` also needs this list to translate a
        mapping's stable ``empId`` into the raw asset id it requires.
        """
        if self._asset_cache is not None:
            return self._asset_cache
        records: List[dict] = []
        for page in range(ASSET_LIST_MAX_PAGES):
            params = {"pt": ASSET_LIST_PAGE_SIZE, "pn": page, "q": ""}
            page_records = self._as_records(self._request("employees", params))
            records.extend(page_records)
            if len(page_records) < ASSET_LIST_PAGE_SIZE:
                break
        self._asset_cache = records
        return records

    def _asset_object_id(self, external_employee_id: str) -> Optional[str]:
        """Raw Mongo id for an employee, keyed by their stable empId code.

        ``asset/history`` requires this raw id as ``asset_id`` — a different
        identifier from the ``empId`` used everywhere else (mappings, punch
        endpoints), so the translation happens here, internal to the adapter.
        """
        for record in self._load_assets():
            if self._external_employee_id(record) == external_employee_id:
                return str(record.get("id") or record.get("_id") or "") or None
        return None

    def fetch_employees(self) -> List[ProviderEmployee]:
        employees = []
        for record in self._load_assets():
            external_id = self._external_employee_id(record)
            if not external_id:
                continue
            employees.append(ProviderEmployee(
                external_id=external_id,
                name=str(_first(record, "name", "fullName", "employeeName", default="")),
                phone=str(_first(record, "phone", "mobile", "contactNumber", default="")),
                email=str(_first(record, "email", default="")),
                is_active=bool(_first(record, "active", "isActive", "enabled", default=True)),
                raw=record,
            ))
        return employees

    def fetch_live_locations(self) -> List[LivePosition]:
        positions = []
        for record in self._load_assets():
            position = self._parse_live(record)
            if position is not None:
                positions.append(position)
        return positions

    def _parse_live(self, record: dict) -> Optional[LivePosition]:
        external_id = self._external_employee_id(record)
        latitude = _to_decimal(_first(record, "lat", "latitude"))
        longitude = _to_decimal(_first(record, "lng", "lon", "longitude"))
        recorded_at = _to_datetime(
            _first(record, "time", "timestamp", "lastGPS", "lastUpdated",
                   "recordedAt", "gpsTime")
        )
        if not external_id or latitude is None or longitude is None or recorded_at is None:
            # Routine for assets that never sent a fix (e.g. admin accounts).
            logger.debug("Skipping live record without a GPS fix (eid=%s).",
                         external_id or "?")
            return None
        return LivePosition(
            external_employee_id=external_id,
            latitude=latitude,
            longitude=longitude,
            recorded_at=recorded_at,
            heartbeat_at=_to_datetime(_first(record, "lastHeartbeat", "heartbeat")),
            accuracy_m=_to_float(_first(record, "accuracy", "gpsAccuracy")),
            speed_kmh=_to_float(_first(record, "speed", "speedKmh")),
            heading=_to_float(_first(record, "heading", "bearing")),
            altitude_m=_to_float(_first(record, "altitude", "alt")),
            battery_pct=_to_int(_first(record, "battery", "batteryLevel")),
            network=str(_first(record, "network", "networkType", default="")),
            gps_enabled=bool(_first(record, "gpsEnabled", "gps", default=True)),
            status=self._map_status(_first(record, "status", "state", default="")),
            address=str(_first(record, "address", "location", default="")),
            raw=record,
        )

    @staticmethod
    def _map_status(value) -> str:
        text = str(value or "").strip().lower()
        if not text:
            return "unknown"
        if "off" in text:
            return "offline"
        if "idle" in text or "stop" in text or "halt" in text:
            return "idle"
        if "mov" in text or "travel" in text or "running" in text:
            return "moving"
        if "on" in text or "active" in text or "live" in text:
            return "online"
        return "unknown"

    def fetch_location_history(
        self,
        window_start: datetime,
        window_end: datetime,
        external_employee_id: Optional[str] = None,
    ) -> List[HistoryPoint]:
        """GPS history — one call per employee, chunked under the vendor's
        24h-per-request cap. ``asset_id`` is mandatory on this endpoint, so
        with no employee given every mapped-and-known asset is walked."""
        if external_employee_id:
            target_ids = [external_employee_id]
        else:
            target_ids = [
                eid for eid in (self._external_employee_id(r) for r in self._load_assets())
                if eid
            ]

        points: List[HistoryPoint] = []
        for eid in target_ids:
            object_id = self._asset_object_id(eid)
            if not object_id:
                logger.warning("No asset id found for employee '%s'; skipping history.", eid)
                continue
            points.extend(self._fetch_history_for_asset(eid, object_id, window_start, window_end))
        return points

    def _fetch_history_for_asset(
        self, external_employee_id: str, object_id: str,
        window_start: datetime, window_end: datetime,
    ) -> List[HistoryPoint]:
        points = []
        chunk_start = window_start
        while chunk_start < window_end:
            chunk_end = min(chunk_start + MAX_HISTORY_WINDOW, window_end)
            params = {
                self._params["from"]: _ms(chunk_start),
                self._params["to"]: _ms(chunk_end),
                self._params["employee"]: object_id,
            }
            records = self._as_records(self._request("history", params))
            for record in records:
                latitude = _to_decimal(_first(record, "lat", "latitude"))
                longitude = _to_decimal(_first(record, "lng", "lon", "longitude"))
                recorded_at = _to_datetime(
                    _first(record, "time", "timestamp", "gpsTime", "recordedAt")
                )
                if latitude is None or longitude is None or recorded_at is None:
                    continue
                points.append(HistoryPoint(
                    external_employee_id=external_employee_id,
                    latitude=latitude,
                    longitude=longitude,
                    recorded_at=recorded_at,
                    accuracy_m=_to_float(_first(record, "accuracy", "gpsAccuracy")),
                    speed_kmh=_to_float(_first(record, "speed", "speedKmh")),
                    heading=_to_float(_first(record, "heading", "bearing")),
                    altitude_m=_to_float(_first(record, "altitude", "alt")),
                    battery_pct=_to_int(_first(record, "battery", "batteryLevel")),
                    event_type=self._map_event(_first(record, "type", "eventType", default="")),
                    external_id=str(_first(record, "id", "pointId", default="")),
                    address=str(_first(record, "address", default="")),
                    raw=record,
                ))
            chunk_start = chunk_end
        return points

    @staticmethod
    def _map_event(value) -> str:
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        if text in {"check_in", "checkin", "punch_in"}:
            return "check_in"
        if text in {"check_out", "checkout", "punch_out"}:
            return "check_out"
        if "stop" in text or "halt" in text:
            return "stop"
        if "idle" in text:
            return "idle"
        return "ping"

    def fetch_visits(self, window_start: datetime, window_end: datetime) -> List[VisitRecord]:
        """Not part of any confirmed endpoint (see DEFAULT_ENDPOINTS); kept
        implemented so an operator who enables it via an endpoint override
        gets tolerant parsing rather than a NotImplementedError."""
        params = {
            self._generic_params["from"]: _ms(window_start),
            self._generic_params["to"]: _ms(window_end),
        }
        records = self._as_records(self._request("visits", params))
        visits = []
        for record in records:
            external_id = str(_first(record, "id", "visitId", "taskId", default=""))
            eid = self._external_employee_id(record)
            if not external_id or not eid:
                continue
            visits.append(VisitRecord(
                external_id=external_id,
                external_employee_id=eid,
                customer_name=str(_first(record, "customerName", "customer",
                                         "clientName", "client", default="")),
                external_customer_id=str(_first(record, "customerId", "clientId", default="")),
                check_in_at=_to_datetime(_first(record, "checkInTime", "checkin", "startTime")),
                check_out_at=_to_datetime(_first(record, "checkOutTime", "checkout", "endTime")),
                check_in_latitude=_to_decimal(_first(record, "checkInLat", "lat", "latitude")),
                check_in_longitude=_to_decimal(_first(record, "checkInLng", "lng", "longitude")),
                check_out_latitude=_to_decimal(_first(record, "checkOutLat")),
                check_out_longitude=_to_decimal(_first(record, "checkOutLng")),
                address=str(_first(record, "address", "location", default="")),
                remarks=str(_first(record, "remarks", "notes", "comment", default="")),
                photo_url=str(_first(record, "photo", "photoUrl", "image", default="")),
                next_follow_up=_to_datetime(
                    _first(record, "nextFollowUp", "followUpDate", "nextVisitDate")
                ),
                raw=record,
            ))
        return visits

    def fetch_attendance_events(
        self, window_start: datetime, window_end: datetime
    ) -> List[AttendanceEvent]:
        """Not part of any confirmed bulk endpoint — TrackoLap's punch APIs
        are push-only (record a punch) or single-employee status checks, not
        a dated/paginated fetch (see DEFAULT_ENDPOINTS). Kept implemented
        for tolerant parsing if an operator wires up an override once a real
        endpoint is confirmed."""
        params = {
            self._generic_params["from"]: _ms(window_start),
            self._generic_params["to"]: _ms(window_end),
        }
        records = self._as_records(self._request("attendance", params))
        events = []
        for record in records:
            eid = self._external_employee_id(record)
            occurred_at = _to_datetime(_first(record, "time", "timestamp", "eventTime"))
            event = self._map_event(_first(record, "type", "eventType", "event", default=""))
            if not eid or occurred_at is None or event not in {"check_in", "check_out"}:
                continue
            events.append(AttendanceEvent(
                external_employee_id=eid,
                event=event,
                occurred_at=occurred_at,
                latitude=_to_decimal(_first(record, "lat", "latitude")),
                longitude=_to_decimal(_first(record, "lng", "lon", "longitude")),
                address=str(_first(record, "address", default="")),
                photo_url=str(_first(record, "photo", "photoUrl", "selfie", default="")),
                raw=record,
            ))
        return events

    def fetch_geofences(self) -> List[GeofenceRecord]:
        records = self._as_records(self._request("geofences"))
        fences = []
        for record in records:
            external_id = str(_first(record, "id", "geofenceId", default=""))
            latitude = _to_decimal(_first(record, "lat", "latitude", "centerLat"))
            longitude = _to_decimal(_first(record, "lng", "lon", "longitude", "centerLng"))
            if not external_id or latitude is None or longitude is None:
                continue
            fences.append(GeofenceRecord(
                external_id=external_id,
                name=str(_first(record, "name", "title", default=f"Geofence {external_id}")),
                latitude=latitude,
                longitude=longitude,
                radius_m=_to_int(_first(record, "radius", "radiusM", default=200)) or 200,
                geofence_type=str(_first(record, "type", "category", default="other")).lower(),
                address=str(_first(record, "address", default="")),
                raw=record,
            ))
        return fences
