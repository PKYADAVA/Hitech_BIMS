"""Turning a set of farms into a day's round.

:mod:`broiler.services.routing` knows about roads. This module knows about
farms: which ones can be routed at all, what order they should be visited in
when priority matters as well as distance, and how a calculated round is
written down as a :class:`~broiler.models.FarmRoute` with its stops.

The division matters. Swapping routing providers must not touch anything here,
and changing what "priority" means to a supervisor must not touch anything
there.
"""
from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from broiler.services.routing import RouteService, RoutingError

#: How much longer a round may get before a priority farm's promotion stops
#: being worth it. Priority routing is a trade, not an override: a critical
#: farm should be reached early, but not by driving the district twice. At
#: 35% the ordering will reorder a day quite freely and still refuse the
#: pathological answers.
PRIORITY_DETOUR_ALLOWANCE = 0.35

#: What each priority is worth when the order is being decided, as a fraction
#: of a kilometre. Higher pulls a farm earlier.
PRIORITY_WEIGHT = {"critical": 0.55, "high": 0.30, "normal": 0.0}

#: A farm unvisited for this long is treated as urgent by the Supervisor Daily
#: Route, whatever its priority flag says. Ten days is roughly a third of a
#: crop: long enough that nobody has looked at the birds through the part of
#: the cycle where looking matters most.
OVERDUE_DAYS = 10

#: And this long is treated the way a critical farm is.
BADLY_OVERDUE_DAYS = 21


class PlannerError(Exception):
    """Something about the *farms* prevents a route. Message fit to show."""


def farm_point(farm):
    """A farm's pin, or None when it has not got one."""
    lat, lng = farm.farm_latitude, farm.farm_longitude
    if lat is None or lng is None:
        return None
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError):
        return None
    # 0,0 is in the Atlantic. It is what an empty form saves, never a farm.
    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180) or (lat == 0 and lng == 0):
        return None
    return (lat, lng)


def split_by_gps(farms):
    """(routable, missing) — the farms that can be routed and those that cannot.

    A farm with no pin is not an error and not a zero: it is a farm somebody
    has to go and capture. It comes back separately so the screen can list it
    with a Capture GPS action rather than dropping it silently or, worse,
    inventing a coordinate for it.
    """
    routable, missing = [], []
    for farm in farms:
        (routable if farm_point(farm) else missing).append(farm)
    return routable, missing



def overdue_weights(farms, as_of=None):
    """How urgent each farm is from how long nobody has been to it.

    The Supervisor Daily Route's own idea of priority. The manual flag on a
    farm says what somebody decided once; this says what the visit register
    actually shows, which is the thing a supervisor's day is really shaped by —
    the farms nobody has looked at.

    Returns the same shape PRIORITY_WEIGHT holds, so the ordering below cannot
    tell the two apart and there is one promotion algorithm rather than two.
    """
    from django.utils import timezone
    from hr.models import SupervisorTripVisit

    as_of = as_of or timezone.localdate()
    ids = [f.id for f in farms]
    last = {}
    for farm_id, when in (SupervisorTripVisit.objects
                          .filter(farm_id__in=ids, checked_in_at__isnull=False)
                          .values_list("farm_id", "checked_in_at")):
        seen = timezone.localtime(when).date()
        if farm_id not in last or seen > last[farm_id]:
            last[farm_id] = seen

    weights = {}
    for farm in farms:
        seen = last.get(farm.id)
        # Never visited is the most overdue there is, not the least: a farm
        # with no visit on record is exactly the one nobody has been to.
        days = (as_of - seen).days if seen else BADLY_OVERDUE_DAYS + 1
        if days > BADLY_OVERDUE_DAYS:
            weights[farm.id] = PRIORITY_WEIGHT["critical"]
        elif days > OVERDUE_DAYS:
            weights[farm.id] = PRIORITY_WEIGHT["high"]
        else:
            weights[farm.id] = 0.0
    return weights, last


def order_by_priority(farms, order, matrix, allowance=PRIORITY_DETOUR_ALLOWANCE,
                      weights=None, reason=None):
    """Pull urgent farms earlier in an already-optimised order.

    Works on the shortest order rather than instead of it, so a priority route
    is a recognisable variation of the efficient one and not a different day's
    driving. Each candidate promotion is measured on the same road matrix that
    produced the order; anything that pushes the round past the allowance is
    refused, and the caller is told what the trade cost.

    ``order`` is indices into a points list whose 0 is the start.
    Returns (new_order, notes) where notes explain each move that was made —
    section 14's requirement that a priority route can say why it differs.
    """

    def tour_length(seq):
        return sum(matrix[seq[i]][seq[i + 1]] for i in range(len(seq) - 1))

    base = tour_length(order)
    ceiling = base * (1 + allowance) if base else 0
    current = order[:]
    notes = []

    # Most urgent first, so a critical farm outranks a high one for the same
    # slot rather than whichever happened to be considered first.
    def weight_of(farm):
        if weights is not None:
            return weights.get(farm.id, 0.0)
        return PRIORITY_WEIGHT.get(getattr(farm, "visit_priority", "normal"), 0.0)

    def label_of(farm):
        if reason is not None:
            return reason(farm)
        return farm.get_visit_priority_display().lower() + " priority"

    ranked = sorted(((i, farms[i - 1]) for i in current if i != 0),
                    key=lambda pair: -weight_of(pair[1]))

    for index, farm in ranked:
        weight = weight_of(farm)
        if not weight:
            continue
        position = current.index(index)
        # The earliest slot this farm could hold, given how urgent it is: a
        # critical farm aims for the front of the day, a high one for the
        # first third.
        target = 1 if weight >= 0.5 else max(1, int(len(current) * 0.33))
        if position <= target:
            continue
        trial = current[:]
        trial.pop(position)
        trial.insert(target, index)
        cost = tour_length(trial)
        if ceiling and cost > ceiling:
            notes.append(
                f"{farm.farm_name} is {label_of(farm)} but moving it earlier "
                f"would add {cost - base:.1f} km, beyond the "
                f"{int(allowance * 100)}% this route allows.")
            continue
        notes.append(
            f"{farm.farm_name} moved from stop {position} to stop {target} "
            f"({label_of(farm)}), adding {max(cost - base, 0):.1f} km.")
        current = trial
        base = cost
    return current, notes


def plan_route(*, start, farms, mode="distance", roundtrip=True, end=None,
               service=None):
    """Work out the round: which order, how far, how long.

    ``start``/``end`` are ``(label, lat, lng)``. ``farms`` are BroilerFarm rows
    that have already passed :func:`split_by_gps`. Returns a plain dict — no
    database rows are written, so a planner can be re-run on the screen as
    often as somebody drags a filter without leaving anything behind.
    """
    if not farms:
        raise PlannerError("Select at least one farm with a location to plan a route.")

    service = service or RouteService()
    start_point = (float(start[1]), float(start[2]))
    points = [start_point] + [farm_point(f) for f in farms]
    end_point = None
    if end and end[1] is not None and end[2] is not None:
        end_point = (float(end[1]), float(end[2]))
        # A different end is a stop like any other as far as the roads are
        # concerned; it is pinned last below rather than optimised into
        # the middle of the day.
        points.append(end_point)

    routing_mode = "time" if mode == "time" else "distance"
    optimise = True
    result = service.calculate(points, mode=routing_mode, optimise=optimise,
                               roundtrip=roundtrip and end_point is None)

    order = [i for i in result.order] or list(range(len(points)))
    notes = []
    if mode in ("priority", "supervisor"):
        # Two ways of being urgent, one promotion algorithm. "Priority" reads
        # the flag somebody set on the farm; "Supervisor Daily Route" reads the
        # visit register instead — how long it has actually been since anybody
        # went — because that is what shapes a supervisor's real day, and a
        # flag nobody has maintained shapes nothing.
        weights, last_seen = (None, {})
        reason = None
        if mode == "supervisor":
            weights, last_seen = overdue_weights(farms)

            def reason(farm, _seen=last_seen):
                when = _seen.get(farm.id)
                if when is None:
                    return "never visited"
                from django.utils import timezone
                return f"last visited {(timezone.localdate() - when).days} days ago"

        matrix = service.provider.matrix(points, routing_mode)
        # Strip a trailing return-to-start before reordering, then put it back:
        # the office at the end is not a stop to be promoted.
        closing = order[-1] if roundtrip and order and order[-1] == 0 else None
        body = order[:-1] if closing is not None else order[:]
        body, notes = order_by_priority(farms, body, matrix,
                                        weights=weights, reason=reason)
        order = body + ([closing] if closing is not None else [])
        ordered_points = [points[i] for i in order]
        result = service.calculate(ordered_points, mode=routing_mode, optimise=False)
        result.order = order

    return _describe(result, order, start, farms, end, roundtrip, notes)


def _describe(result, order, start, farms, end, roundtrip, notes):
    """The calculated round as the screens want it: a list of stops, each with
    its leg and its running totals."""
    stops = []
    running_km, running_min = 0.0, 0
    legs = list(result.legs)

    for position, point_index in enumerate(order):
        leg = legs[position - 1] if position and position - 1 < len(legs) else None
        running_km += leg.distance_km if leg else 0.0
        running_min += leg.minutes if leg else 0
        is_start = position == 0
        is_close = roundtrip and position == len(order) - 1 and point_index == 0
        if is_start or is_close:
            stops.append({
                "sequence": position + 1,
                "kind": "start" if is_start else "end",
                "farm_id": None, "farm_code": "",
                "label": start[0] if is_start else (end[0] if end else start[0]),
                "latitude": start[1], "longitude": start[2],
                "priority": "",
                "leg_distance_km": round(leg.distance_km, 2) if leg else 0.0,
                "leg_minutes": leg.minutes if leg else 0,
                "cumulative_distance_km": round(running_km, 2),
                "cumulative_minutes": int(running_min),
            })
            continue
        farm = farms[point_index - 1]
        point = farm_point(farm)
        stops.append({
            "sequence": position + 1,
            "kind": "farm",
            "farm_id": farm.id,
            "farm_code": farm.farm_code or "",
            "label": farm.farm_name,
            "latitude": point[0], "longitude": point[1],
            "priority": getattr(farm, "visit_priority", "normal"),
            "leg_distance_km": round(leg.distance_km, 2) if leg else 0.0,
            "leg_minutes": leg.minutes if leg else 0,
            "cumulative_distance_km": round(running_km, 2),
            "cumulative_minutes": int(running_min),
        })

    # A round trip's last leg is the drive home, and a provider's optimiser
    # reports it as a leg without adding a waypoint for it — leaving the
    # sequence one stop short of the distance it was quoting, so the panel
    # said 256 km and listed 128. The closing call is written here rather than
    # hoped for in the order.
    if roundtrip and stops and stops[-1]["kind"] != "end" and len(legs) >= len(stops):
        leg = legs[len(stops) - 1]
        running_km += leg.distance_km
        running_min += leg.minutes
        stops.append({
            "sequence": len(stops) + 1,
            "kind": "end",
            "farm_id": None, "farm_code": "",
            "label": (end[0] if end else start[0]),
            "latitude": (end[1] if end else start[1]),
            "longitude": (end[2] if end else start[2]),
            "priority": "",
            "leg_distance_km": round(leg.distance_km, 2),
            "leg_minutes": leg.minutes,
            "cumulative_distance_km": round(running_km, 2),
            "cumulative_minutes": int(running_min),
        })

    return {
        "stops": stops,
        "distance_km": result.distance_km,
        "minutes": result.minutes,
        "geometry": result.geometry,
        "provider": result.provider,
        "basis": result.basis,
        "estimated": result.basis != "road",
        "priority_notes": notes,
        "farm_count": sum(1 for s in stops if s["kind"] == "farm"),
    }


@transaction.atomic
def save_route(plan, *, name="", date=None, branch=None, supervisor=None,
               mode="distance", start=None, end=None, roundtrip=True,
               created_by=None, status=None):
    """Write a calculated round down as a FarmRoute and its stops.

    Kept apart from :func:`plan_route` on purpose: a planner that saved every
    time somebody moved a filter would fill the table with rounds nobody drove.
    """
    from broiler.models import FarmRoute, FarmRouteStop

    route = FarmRoute.objects.create(
        name=name or "",
        date=date,
        branch=branch,
        supervisor=supervisor,
        start_label=(start or ("", None, None))[0] or "",
        start_latitude=(start or ("", None, None))[1],
        start_longitude=(start or ("", None, None))[2],
        end_label=(end or ("", None, None))[0] or "",
        end_latitude=(end or ("", None, None))[1],
        end_longitude=(end or ("", None, None))[2],
        returns_to_start=bool(roundtrip),
        mode=mode,
        status=status or FarmRoute.STATUS_PLANNED,
        distance_basis=(FarmRoute.BASIS_ROAD if plan.get("basis") == "road"
                        else FarmRoute.BASIS_STRAIGHT),
        provider=plan.get("provider") or "",
        planned_distance_km=Decimal(str(plan.get("distance_km") or 0)),
        planned_minutes=int(plan.get("minutes") or 0),
        geometry=plan.get("geometry"),
        created_by=created_by,
    )
    FarmRouteStop.objects.bulk_create([
        FarmRouteStop(
            route=route, sequence=s["sequence"], kind=s["kind"],
            farm_id=s["farm_id"], label=s["label"],
            latitude=s["latitude"], longitude=s["longitude"],
            leg_distance_km=Decimal(str(s["leg_distance_km"])),
            leg_minutes=s["leg_minutes"],
            cumulative_distance_km=Decimal(str(s["cumulative_distance_km"])),
            cumulative_minutes=s["cumulative_minutes"],
            priority=s.get("priority") or "",
        ) for s in plan["stops"]
    ])
    return route
