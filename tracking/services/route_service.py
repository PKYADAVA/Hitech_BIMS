# pylint: disable=no-member
"""Builds per-day route summaries from raw GPS pings.

Runs inside the sync pipeline right after new history lands, so
``employee_route`` / ``employee_route_points`` are always current and no
report or dashboard ever aggregates over ``employee_location_history``
at request time.
"""

import logging
from datetime import datetime, time as dt_time, timedelta

from django.db import transaction
from django.utils import timezone

from ..models import (
    EmployeeLocationHistory,
    EmployeeRoute,
    EmployeeRoutePoint,
    TrackingSettings,
)
from .geo import encode_polyline, haversine_km

logger = logging.getLogger("tracking.routes")

#: Consecutive pings within this radius count as "not moving".
STOP_RADIUS_KM = 0.05  # 50 m
#: GPS jitter guard: a leg implying > this speed is discarded from distance.
MAX_PLAUSIBLE_SPEED_KMH = 160.0


class RouteBuilder:
    """Recomputes one employee's route summary for one calendar day."""

    def __init__(self, settings: TrackingSettings = None):
        self._settings = settings or TrackingSettings.get_solo()

    def rebuild(self, employee, day, provider=None) -> EmployeeRoute:
        """Aggregate the day's pings into an EmployeeRoute (+ points).

        Idempotent: deletes and recreates the day's route points, so it can
        run after every incremental history sync.
        """
        day_start = timezone.make_aware(datetime.combine(day, dt_time.min))
        day_end = day_start + timedelta(days=1)
        pings = list(
            EmployeeLocationHistory.objects
            .filter(employee=employee, recorded_at__gte=day_start, recorded_at__lt=day_end)
            .order_by("recorded_at")
        )

        with transaction.atomic():
            route, _created = EmployeeRoute.objects.select_for_update().get_or_create(
                employee=employee, date=day, defaults={"provider": provider}
            )
            route.points.all().delete()
            if not pings:
                self._reset_empty(route)
                return route
            self._aggregate(route, pings)
            route.is_finalized = day < timezone.localdate()
            if provider is not None:
                route.provider = provider
            route.save()
        return route

    @staticmethod
    def _reset_empty(route):
        route.total_distance_km = 0
        route.points_count = 0
        route.stops_count = 0
        route.polyline = ""
        route.first_point_at = None
        route.last_point_at = None
        route.travel_time = None
        route.idle_time = None
        route.average_speed_kmh = None
        route.max_speed_kmh = None
        route.save()

    def _aggregate(self, route, pings):
        total_km = 0.0
        idle = timedelta()
        max_speed = 0.0
        idle_threshold = timedelta(minutes=self._settings.idle_after_minutes)

        stops = []  # (first_ping, last_ping) of each stationary cluster
        cluster_start = pings[0]
        cluster_last = pings[0]

        for prev, current in zip(pings, pings[1:]):
            leg_km = haversine_km(prev.latitude, prev.longitude,
                                  current.latitude, current.longitude)
            leg_time = (current.recorded_at - prev.recorded_at).total_seconds()
            if leg_time > 0:
                implied_speed = leg_km / (leg_time / 3600)
                if implied_speed <= MAX_PLAUSIBLE_SPEED_KMH:
                    total_km += leg_km
            if current.speed_kmh:
                max_speed = max(max_speed, current.speed_kmh)

            # Stationary-cluster detection for stops/idle time.
            from_cluster_km = haversine_km(cluster_start.latitude, cluster_start.longitude,
                                           current.latitude, current.longitude)
            if from_cluster_km <= STOP_RADIUS_KM:
                cluster_last = current
            else:
                self._close_cluster(stops, cluster_start, cluster_last, idle_threshold)
                cluster_start = cluster_last = current
        self._close_cluster(stops, cluster_start, cluster_last, idle_threshold)

        first, last = pings[0], pings[-1]
        elapsed = last.recorded_at - first.recorded_at
        idle = sum((s[1].recorded_at - s[0].recorded_at for s in stops), timedelta())
        travel = max(elapsed - idle, timedelta())
        travel_hours = travel.total_seconds() / 3600

        route.total_distance_km = round(total_km, 2)
        route.points_count = len(pings)
        route.first_point_at = first.recorded_at
        route.last_point_at = last.recorded_at
        route.travel_time = travel
        route.idle_time = idle
        route.average_speed_kmh = round(total_km / travel_hours, 1) if travel_hours > 0.01 else None
        route.max_speed_kmh = max_speed or None
        route.start_address = first.address
        route.end_address = last.address
        route.polyline = encode_polyline((p.latitude, p.longitude) for p in pings)
        route.stops_count = len(stops)

        self._write_points(route, pings, stops)

    @staticmethod
    def _close_cluster(stops, cluster_start, cluster_last, idle_threshold):
        duration = cluster_last.recorded_at - cluster_start.recorded_at
        if duration >= idle_threshold:
            stops.append((cluster_start, cluster_last))

    @staticmethod
    def _write_points(route, pings, stops):
        """Simplified leg sequence: start, each stop, end."""
        points = []
        sequence = 1
        first, last = pings[0], pings[-1]

        points.append(EmployeeRoutePoint(
            route=route, sequence=sequence, point_type="travel",
            latitude=first.latitude, longitude=first.longitude,
            address=first.address, started_at=first.recorded_at,
        ))
        previous_ping = first
        for stop_start, stop_end in stops:
            sequence += 1
            points.append(EmployeeRoutePoint(
                route=route, sequence=sequence, point_type="stop",
                latitude=stop_start.latitude, longitude=stop_start.longitude,
                address=stop_start.address,
                started_at=stop_start.recorded_at, ended_at=stop_end.recorded_at,
                duration=stop_end.recorded_at - stop_start.recorded_at,
                distance_from_previous_km=round(haversine_km(
                    previous_ping.latitude, previous_ping.longitude,
                    stop_start.latitude, stop_start.longitude), 2),
            ))
            previous_ping = stop_end
        if last is not first:
            sequence += 1
            points.append(EmployeeRoutePoint(
                route=route, sequence=sequence, point_type="travel",
                latitude=last.latitude, longitude=last.longitude,
                address=last.address, started_at=last.recorded_at,
                distance_from_previous_km=round(haversine_km(
                    previous_ping.latitude, previous_ping.longitude,
                    last.latitude, last.longitude), 2),
            ))
        EmployeeRoutePoint.objects.bulk_create(points)
