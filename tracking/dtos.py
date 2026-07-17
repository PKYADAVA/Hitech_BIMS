"""Provider-agnostic data structures crossing the adapter boundary.

Every fetch method on a tracking adapter returns these frozen dataclasses —
never raw vendor JSON — so the sync service and everything above it stay
free of provider specifics. ``raw`` retains the original payload for
diagnostics only and is never persisted to business columns.

All datetimes are timezone-aware (UTC); adapters own the conversion from
whatever the vendor sends (epoch ms for TrackWick).
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class ProviderEmployee:
    """An employee identity as known to the vendor (directory sync)."""

    external_id: str
    name: str = ""
    phone: str = ""
    email: str = ""
    is_active: bool = True
    raw: Optional[dict] = field(default=None, repr=False)


@dataclass(frozen=True)
class LivePosition:
    """Current position of one employee."""

    external_employee_id: str
    latitude: Decimal
    longitude: Decimal
    recorded_at: datetime
    heartbeat_at: Optional[datetime] = None  # device alive-ness, ≥ recorded_at
    accuracy_m: Optional[float] = None
    speed_kmh: Optional[float] = None
    heading: Optional[float] = None
    altitude_m: Optional[float] = None
    battery_pct: Optional[int] = None
    network: str = ""
    gps_enabled: bool = True
    status: str = "unknown"  # online / idle / moving / offline / unknown
    address: str = ""
    raw: Optional[dict] = field(default=None, repr=False)


@dataclass(frozen=True)
class HistoryPoint:
    """One historical GPS ping."""

    external_employee_id: str
    latitude: Decimal
    longitude: Decimal
    recorded_at: datetime
    accuracy_m: Optional[float] = None
    speed_kmh: Optional[float] = None
    heading: Optional[float] = None
    altitude_m: Optional[float] = None
    battery_pct: Optional[int] = None
    event_type: str = "ping"  # ping / stop / idle / check_in / check_out
    external_id: str = ""
    address: str = ""
    raw: Optional[dict] = field(default=None, repr=False)


@dataclass(frozen=True)
class VisitRecord:
    """A customer/field visit reported by the vendor."""

    external_id: str
    external_employee_id: str
    customer_name: str = ""
    external_customer_id: str = ""
    check_in_at: Optional[datetime] = None
    check_out_at: Optional[datetime] = None
    check_in_latitude: Optional[Decimal] = None
    check_in_longitude: Optional[Decimal] = None
    check_out_latitude: Optional[Decimal] = None
    check_out_longitude: Optional[Decimal] = None
    address: str = ""
    remarks: str = ""
    photo_url: str = ""
    next_follow_up: Optional[datetime] = None
    raw: Optional[dict] = field(default=None, repr=False)


@dataclass(frozen=True)
class AttendanceEvent:
    """A GPS check-in/check-out event."""

    external_employee_id: str
    event: str  # check_in / check_out
    occurred_at: datetime
    latitude: Optional[Decimal] = None
    longitude: Optional[Decimal] = None
    address: str = ""
    photo_url: str = ""
    raw: Optional[dict] = field(default=None, repr=False)


@dataclass(frozen=True)
class GeofenceRecord:
    """A geofence defined on the vendor side."""

    external_id: str
    name: str
    latitude: Decimal
    longitude: Decimal
    radius_m: int = 200
    geofence_type: str = "other"
    address: str = ""
    raw: Optional[dict] = field(default=None, repr=False)


@dataclass(frozen=True)
class ConnectionTestResult:
    """Outcome of a provider connectivity/credential test."""

    success: bool
    message: str
    details: Optional[dict] = field(default=None, repr=False)
