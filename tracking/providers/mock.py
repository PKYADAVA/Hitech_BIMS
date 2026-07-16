"""In-memory adapter used by the test suite (and nothing else).

Deterministic, network-free stand-in so the sync engine, services and views
can be tested end-to-end without a vendor account. Not selectable from the
provider master's choices; tests create rows with ``provider_type="mock"``
directly. Mirrors ``notification.providers.mock``.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
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
from .base import TrackingProviderAdapter

# Fixed reference point (Lucknow) — arbitrary but stable for assertions.
BASE_LAT = Decimal("26.850000")
BASE_LNG = Decimal("80.950000")


class MockProviderAdapter(TrackingProviderAdapter):
    """Serves a small fixed dataset for two employees, EXT-1 and EXT-2."""

    name = "mock"

    #: Tests may replace these class-level datasets to simulate scenarios.
    employees = [
        ProviderEmployee(external_id="EXT-1", name="Mock Employee One", phone="9000000001"),
        ProviderEmployee(external_id="EXT-2", name="Mock Employee Two", phone="9000000002"),
    ]

    def test_connection(self) -> ConnectionTestResult:
        return ConnectionTestResult(success=True, message="Mock provider always connects.")

    def fetch_employees(self) -> List[ProviderEmployee]:
        return list(self.employees)

    def fetch_live_locations(self) -> List[LivePosition]:
        now = datetime.now(tz=timezone.utc)
        return [
            LivePosition(
                external_employee_id="EXT-1", latitude=BASE_LAT, longitude=BASE_LNG,
                recorded_at=now, speed_kmh=0.0, battery_pct=80, status="online",
            ),
            LivePosition(
                external_employee_id="EXT-2",
                latitude=BASE_LAT + Decimal("0.010000"),
                longitude=BASE_LNG + Decimal("0.010000"),
                recorded_at=now - timedelta(minutes=30),
                speed_kmh=24.5, battery_pct=45, status="moving",
            ),
        ]

    def fetch_location_history(
        self,
        window_start: datetime,
        window_end: datetime,
        external_employee_id: Optional[str] = None,
    ) -> List[HistoryPoint]:
        points, step = [], timedelta(minutes=5)
        employee_ids = [external_employee_id] if external_employee_id else ["EXT-1", "EXT-2"]
        for eid in employee_ids:
            current, index = window_start, 0
            while current < window_end and index < 12:
                offset = Decimal(index) * Decimal("0.001000")
                points.append(HistoryPoint(
                    external_employee_id=eid,
                    latitude=BASE_LAT + offset,
                    longitude=BASE_LNG + offset,
                    recorded_at=current,
                    speed_kmh=float(10 + index),
                    external_id=f"{eid}-P{index}",
                ))
                current += step
                index += 1
        return points

    def fetch_visits(self, window_start: datetime, window_end: datetime) -> List[VisitRecord]:
        return [VisitRecord(
            external_id="VISIT-1",
            external_employee_id="EXT-1",
            customer_name="Mock Customer",
            check_in_at=window_start,
            check_out_at=window_start + timedelta(minutes=40),
            check_in_latitude=BASE_LAT,
            check_in_longitude=BASE_LNG,
            remarks="Mock visit",
            photo_url="https://mock.invalid/photos/visit-1.jpg",
            next_follow_up=window_end + timedelta(days=7),
        )]

    def fetch_attendance_events(
        self, window_start: datetime, window_end: datetime
    ) -> List[AttendanceEvent]:
        return [
            AttendanceEvent(
                external_employee_id="EXT-1", event="check_in",
                occurred_at=window_start, latitude=BASE_LAT, longitude=BASE_LNG,
            ),
            AttendanceEvent(
                external_employee_id="EXT-1", event="check_out",
                occurred_at=window_end, latitude=BASE_LAT, longitude=BASE_LNG,
            ),
        ]

    def fetch_geofences(self) -> List[GeofenceRecord]:
        return [GeofenceRecord(
            external_id="GEO-1", name="Mock Office",
            latitude=BASE_LAT, longitude=BASE_LNG, radius_m=250, geofence_type="office",
        )]
