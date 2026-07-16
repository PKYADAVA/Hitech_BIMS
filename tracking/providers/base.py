"""Adapter interface that decouples the tracking module from any GPS vendor.

The contract every vendor implementation must satisfy. Rules of the layer:

* Adapters are the **only** code that knows a vendor's wire format. They
  accept/return :mod:`tracking.dtos` objects exclusively.
* Adapters never retry internally — the sync service owns retry policy.
  Retryable failures raise :class:`~tracking.exceptions.TrackingTransientError`,
  everything else :class:`~tracking.exceptions.TrackingPermanentError`
  (credential rejections: :class:`~tracking.exceptions.TrackingAuthError`).
* Adapters never log or expose credentials, and never write to the database.
* A vendor that lacks a data kind declares it via ``capabilities`` so the
  sync engine skips it instead of calling and failing.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional

from ..dtos import (
    AttendanceEvent,
    ConnectionTestResult,
    GeofenceRecord,
    HistoryPoint,
    LivePosition,
    ProviderEmployee,
    VisitRecord,
)

#: Every data kind the sync engine knows how to ask for.
ALL_CAPABILITIES = frozenset(
    {"employees", "live", "history", "visits", "attendance", "geofences"}
)


class TrackingProviderAdapter(ABC):
    """Contract every GPS-vendor implementation must satisfy."""

    #: Short, stable identifier recorded on sync runs and in logs.
    name = "base"

    #: Data kinds this vendor can supply; the sync engine only requests these.
    capabilities = ALL_CAPABILITIES

    def __init__(self, provider):
        """``provider`` is the :class:`tracking.models.TrackingProvider` row."""
        self.provider = provider

    def supports(self, kind: str) -> bool:
        return kind in self.capabilities

    @abstractmethod
    def test_connection(self) -> ConnectionTestResult:
        """Cheapest possible authenticated call; never raises — returns a result."""

    @abstractmethod
    def fetch_employees(self) -> List[ProviderEmployee]:
        """Vendor's employee directory, for identity mapping."""

    @abstractmethod
    def fetch_live_locations(self) -> List[LivePosition]:
        """Current position of every tracked employee."""

    @abstractmethod
    def fetch_location_history(
        self,
        window_start: datetime,
        window_end: datetime,
        external_employee_id: Optional[str] = None,
    ) -> List[HistoryPoint]:
        """GPS pings inside a time window, optionally for one employee."""

    @abstractmethod
    def fetch_visits(
        self, window_start: datetime, window_end: datetime
    ) -> List[VisitRecord]:
        """Customer visits recorded inside a time window."""

    @abstractmethod
    def fetch_attendance_events(
        self, window_start: datetime, window_end: datetime
    ) -> List[AttendanceEvent]:
        """GPS check-in/check-out events inside a time window."""

    @abstractmethod
    def fetch_geofences(self) -> List[GeofenceRecord]:
        """Geofences defined on the vendor side."""
