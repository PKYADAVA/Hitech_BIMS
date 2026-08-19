"""Joining a planned round to the journey that was actually driven.

The plan lives in :class:`~broiler.models.FarmRoute`. The journey already had
a home before this module existed — ``hr.SupervisorTrip`` carries the
odometer, the start and end photographs and the GPS stamps, and
``hr.SupervisorTripVisit`` carries each farm call with its check-in and
check-out. None of that is rebuilt here. This is the seam: it creates a trip
from a route, records arrivals and departures against both at once, and
afterwards says how far the day drifted from the plan.

The trip is the record and the route is the intention. Where they disagree the
trip wins — a supervisor who visited the farms in a different order visited
them in a different order, and the report's job is to show it, not to correct
it.
"""
from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from broiler.models import FarmRoute, FarmRouteStop


class TripError(Exception):
    """Something about the trip prevents this. Message fit to show a user."""


def employee_for(supervisor):
    """The payroll record behind a supervisor, which is what a trip belongs to.

    ``broiler.Supervisor`` and ``hr.Employee`` are two records of one person —
    the farm master points at the first, the trip register at the second, and
    ``Supervisor.employee`` is the link between them. A supervisor nobody has
    linked cannot have a trip raised for them, and saying so is more useful
    than creating a trip against nobody.
    """
    if supervisor is None:
        return None
    return getattr(supervisor, "employee", None)


@transaction.atomic
def create_trip(route, *, created_by=None, purpose="Farm visit"):
    """Raise the Supervisor Daily Trip this route is to be driven as.

    One route, one trip. Re-planning a day makes a new route rather than
    rewriting the one whose journey is already recorded, so a plan can always
    be compared with what happened to it.
    """
    from hr.models import SupervisorTrip, SupervisorTripVisit

    if route.trip_id:
        raise TripError(f"Route {route.route_no} already has trip "
                        f"{route.trip.trip_no}.")
    employee = employee_for(route.supervisor)
    if employee is None:
        raise TripError(
            "This route has no supervisor with an employee record, so there is "
            "nobody to raise a trip against. Set the supervisor on the route, "
            "and link that supervisor to an employee in the Supervisor master.")

    trip = SupervisorTrip.objects.create(
        date=route.date, employee=employee,
        status=SupervisorTrip.STATUS_IN_PROGRESS,
        start_address=route.start_label or "",
        start_latitude=route.start_latitude,
        start_longitude=route.start_longitude,
        remarks=f"Planned round {route.route_no}",
        created_by=created_by,
    )
    # A visit row per planned farm call, in the planned order. They are the
    # rows the phone checks into, so they exist before the day starts rather
    # than being created on arrival — a supervisor with no signal at the farm
    # gate still has something to record against.
    SupervisorTripVisit.objects.bulk_create([
        SupervisorTripVisit(trip=trip, farm_id=stop.farm_id, purpose=purpose)
        for stop in route.stops.filter(farm__isnull=False).order_by("sequence")
    ])
    route.trip = trip
    route.status = FarmRoute.STATUS_STARTED
    route.save(update_fields=["trip", "status", "updated_at"])
    return trip


def _visit_for(route, farm_id):
    """The trip's own visit row for this farm, or None."""
    if not route.trip_id:
        return None
    return route.trip.visits.filter(farm_id=farm_id).order_by("id").first()


@transaction.atomic
def check_in(route, farm_id, *, latitude=None, longitude=None, when=None):
    """The supervisor has reached a farm.

    Recorded on the trip's visit, which is where the register reads it from,
    and mirrored onto the route's stop so planned and actual sit side by side
    without a join for every comparison. ``actual_sequence`` is the order they
    really arrived in — the whole basis of the deviation report.
    """
    if not route.trip_id:
        raise TripError("Start the trip before checking in at a farm.")
    visit = _visit_for(route, farm_id)
    if visit is None:
        raise TripError("That farm is not on this trip.")
    if visit.checked_in_at:
        raise TripError(f"Already checked in at {visit.farm.farm_name} at "
                        f"{timezone.localtime(visit.checked_in_at):%H:%M}.")

    when = when or timezone.now()
    visit.checked_in_at = when
    if latitude is not None and longitude is not None:
        visit.latitude, visit.longitude = float(latitude), float(longitude)
    visit.save()

    stop = route.stops.filter(farm_id=farm_id).order_by("sequence").first()
    if stop:
        # How many farms had already been reached: this call is the next one.
        reached = (route.stops.filter(visited_at__isnull=False)
                   .exclude(pk=stop.pk).count())
        stop.visited_at = when
        stop.actual_sequence = reached + 2      # the start is stop 1
        stop.save(update_fields=["visited_at", "actual_sequence"])
    return visit


@transaction.atomic
def check_out(route, farm_id, *, latitude=None, longitude=None, when=None):
    """The supervisor has left. Duration is the model's own business."""
    visit = _visit_for(route, farm_id)
    if visit is None:
        raise TripError("That farm is not on this trip.")
    if not visit.checked_in_at:
        raise TripError("Check in at the farm before checking out of it.")
    if visit.checked_out_at:
        raise TripError("Already checked out of this farm.")

    visit.checked_out_at = when or timezone.now()
    if latitude is not None and longitude is not None:
        visit.latitude, visit.longitude = float(latitude), float(longitude)
    visit.save()      # SupervisorTripVisit.save works the duration out itself
    return visit


def deviation(route):
    """Planned against actual: order, distance and what the difference cost.

    Two different questions, and the report needs both. *Sequence* deviation is
    whether the farms were reached in the planned order — a supervisor who
    took the third farm first has deviated even if the kilometres came out the
    same. *Distance* deviation is the odometer against the plan, which is the
    figure a travel claim turns on.

    Efficiency is planned over actual, so 100% is driving the round as planned
    and less than 100% is driving further than it. Above 100% means the day was
    shorter than the plan — a farm skipped, or a better road than the router
    knew about — and it is left as it falls rather than capped, because a
    number that cannot exceed its target hides exactly that.
    """
    stops = list(route.stops.filter(farm__isnull=False).order_by("sequence"))
    visited = [s for s in stops if s.visited_at]
    planned_order = [s.farm_id for s in stops]
    actual_order = [s.farm_id for s in sorted(visited, key=lambda s: s.visited_at)]

    out_of_turn = [
        {"farm": s.label or (s.farm.farm_name if s.farm_id else ""),
         "planned": s.sequence, "actual": s.actual_sequence}
        for s in visited if s.is_deviation
    ]

    planned_km = float(route.planned_distance_km or 0)
    actual_km = float(getattr(route.trip, "distance_km", 0) or 0) if route.trip_id else 0.0
    extra_km = round(actual_km - planned_km, 2) if actual_km else 0.0
    efficiency = round(planned_km / actual_km * 100, 1) if actual_km else None

    return {
        "route_no": route.route_no,
        "trip_no": route.trip.trip_no if route.trip_id else "",
        "planned_farms": len(stops),
        "visited_farms": len(visited),
        "missed_farms": [s.label or (s.farm.farm_name if s.farm_id else "")
                         for s in stops if not s.visited_at],
        "planned_order": planned_order,
        "actual_order": actual_order,
        # The headline the register shows: did the day follow the plan at all.
        "sequence_changed": bool(out_of_turn) or (
            actual_order != planned_order[:len(actual_order)]),
        "out_of_turn": out_of_turn,
        "planned_distance_km": round(planned_km, 2),
        "actual_distance_km": round(actual_km, 2),
        "extra_distance_km": extra_km,
        "efficiency_pct": efficiency,
        # An odometer nobody filled in is not a zero-kilometre day, and a
        # deviation report that treats it as one accuses somebody of not
        # having gone out.
        "actual_distance_known": bool(actual_km),
    }
