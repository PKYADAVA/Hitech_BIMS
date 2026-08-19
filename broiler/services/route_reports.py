"""The Farm Map & Route Planner's reports.

Nine reports, one module, because they are nine questions about the same three
tables — where the farms are, what was planned, and what was driven. Each is a
function returning ``(columns, rows, summary)``; the page renders whichever was
asked for and the exporter writes the same thing to a spreadsheet, so a column
cannot say one thing on screen and another in Excel.

They are deliberately not nine pages. Nine tabs would be nine permissions,
nine filter bars and nine places for the scoping to be got wrong; one page with
a report picker is one of each.

Every one of them reads through the caller's data scope. A supervisor sees
their own branch's farms here exactly as they do on the map.
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone

from broiler.models import Branch, BroilerFarm, FarmRoute, FarmRouteStop
from broiler.services.route_planner import farm_point
from user.services.scoping import branches_for, farms_for

#: (key, label) for the report picker, in the order the spec names them.
REPORTS = [
    ("farm_distance", "Farm Distance Report"),
    ("supervisor_route", "Supervisor Route Report"),
    ("farm_visit", "Farm Visit Report"),
    ("planned_vs_actual", "Planned vs Actual Route"),
    ("route_deviation", "Route Deviation Report"),
    ("gps_accuracy", "GPS Accuracy Report"),
    ("gps_missing", "Farm GPS Missing Report"),
    ("supervisor_travel", "Supervisor Travel Distance"),
    ("visit_compliance", "Farm Visit Compliance"),
]

#: How stale a pin has to be before the GPS Accuracy report calls it old. A
#: farm's buildings do not move, but the reading somebody took on a phone two
#: years ago was taken with two years' worse hardware, and a shed can be added.
STALE_DAYS = 365

#: A reading worse than this is too coarse to route to. 100 m is roughly the
#: length of a shed: within it, a supervisor arriving at the pin can see the
#: farm; beyond it, they may be in the wrong field.
COARSE_METRES = 100.0


def _routes(user, filters):
    """Saved rounds this user may see, narrowed by the filter bar."""
    routes = (FarmRoute.objects
              .select_related("branch", "supervisor", "trip", "created_by")
              .prefetch_related("stops__farm"))
    allowed = set(branches_for(user, Branch.objects.all()).values_list("id", flat=True))
    routes = routes.filter(Q(branch__isnull=True) | Q(branch_id__in=allowed))
    if filters.get("branch"):
        routes = routes.filter(branch_id=filters["branch"])
    if filters.get("supervisor"):
        routes = routes.filter(supervisor_id=filters["supervisor"])
    if filters.get("from_date"):
        routes = routes.filter(date__gte=filters["from_date"])
    if filters.get("to_date"):
        routes = routes.filter(date__lte=filters["to_date"])
    return routes


def _farms(user, filters):
    farms = farms_for(user, BroilerFarm.objects.select_related(
        "branch", "supervisor", "farmer"))
    if filters.get("branch"):
        farms = farms.filter(branch_id=filters["branch"])
    if filters.get("supervisor"):
        farms = farms.filter(supervisor_id=filters["supervisor"])
    return farms


def _visits(user, filters):
    """Farm calls actually recorded, from the trip register."""
    from hr.models import SupervisorTripVisit

    visits = (SupervisorTripVisit.objects
              .select_related("trip", "trip__employee", "farm", "farm__branch",
                              "farm__supervisor")
              .filter(farm__isnull=False))
    allowed = set(farms_for(user, BroilerFarm.objects.all()).values_list("id", flat=True))
    visits = visits.filter(farm_id__in=allowed)
    if filters.get("branch"):
        visits = visits.filter(farm__branch_id=filters["branch"])
    if filters.get("supervisor"):
        visits = visits.filter(farm__supervisor_id=filters["supervisor"])
    if filters.get("from_date"):
        visits = visits.filter(trip__date__gte=filters["from_date"])
    if filters.get("to_date"):
        visits = visits.filter(trip__date__lte=filters["to_date"])
    return visits


# --- the reports -----------------------------------------------------------


def farm_distance(user, filters):
    """How far each farm sits from its branch office, by road where a route
    has measured it and unmeasured otherwise.

    Deliberately not a straight-line figure for the farms nobody has routed
    to: an unmeasured distance is unknown, and printing a ruler's answer in a
    column headed "km by road" is how an estimate becomes a fact.
    """
    columns = ["Farm Code", "Farm Name", "Branch", "Supervisor", "Location",
               "Has GPS", "Road Distance (km)", "Measured On"]
    # The shortest leg ever recorded into each farm, which is the best measure
    # of how far out it is that the planner has actually paid for.
    legs = {}
    for stop in FarmRouteStop.objects.filter(
            farm__isnull=False, leg_distance_km__gt=0).select_related("route"):
        current = legs.get(stop.farm_id)
        if current is None or stop.leg_distance_km < current[0]:
            legs[stop.farm_id] = (stop.leg_distance_km, stop.route.date)

    rows = []
    for farm in _farms(user, filters).order_by("branch__branch_name", "farm_name"):
        measured = legs.get(farm.id)
        rows.append([
            farm.farm_code or "", farm.farm_name,
            farm.branch.branch_name if farm.branch_id else "",
            farm.supervisor.name if farm.supervisor_id else "",
            ", ".join(p for p in (farm.area, farm.district, farm.state) if p),
            "Yes" if farm_point(farm) else "No",
            float(measured[0]) if measured else None,
            measured[1].strftime("%d-%m-%Y") if measured else "not routed yet",
        ])
    measured_rows = [r for r in rows if r[6] is not None]
    return columns, rows, {
        "Farms": len(rows),
        "Measured by road": len(measured_rows),
        "Average distance": (round(sum(r[6] for r in measured_rows) / len(measured_rows), 1)
                             if measured_rows else None),
    }


def supervisor_route(user, filters):
    """Every planned round, by supervisor."""
    columns = ["Route ID", "Date", "Branch", "Supervisor", "Farms",
               "Planned (km)", "Planned Time", "Mode", "Basis", "Status",
               "Trip", "Created By"]
    rows, total_km, total_min = [], 0.0, 0
    for route in _routes(user, filters).order_by("-date", "route_no"):
        total_km += float(route.planned_distance_km or 0)
        total_min += int(route.planned_minutes or 0)
        rows.append([
            route.route_no, route.date.strftime("%d-%m-%Y"),
            route.branch.branch_name if route.branch_id else "",
            route.supervisor.name if route.supervisor_id else "",
            route.farm_count, float(route.planned_distance_km or 0),
            route.duration_label, route.get_mode_display(),
            "Road" if route.distance_basis == FarmRoute.BASIS_ROAD else "Estimate",
            route.get_status_display(),
            route.trip.trip_no if route.trip_id else "",
            route.created_by.username if route.created_by_id else "",
        ])
    return columns, rows, {"Routes": len(rows),
                           "Planned distance": round(total_km, 1),
                           "Planned time": _hm(total_min)}


def farm_visit(user, filters):
    """Every farm call that was actually made."""
    columns = ["Date", "Trip", "Employee", "Farm Code", "Farm Name", "Branch",
               "Supervisor", "Checked In", "Checked Out", "Duration (min)",
               "GPS At Farm"]
    rows = []
    for visit in _visits(user, filters).order_by("-trip__date", "-checked_in_at"):
        rows.append([
            visit.trip.date.strftime("%d-%m-%Y") if visit.trip_id else "",
            visit.trip.trip_no if visit.trip_id else "",
            (visit.trip.employee.full_name
             if visit.trip_id and visit.trip.employee_id else ""),
            visit.farm.farm_code or "", visit.farm.farm_name,
            visit.farm.branch.branch_name if visit.farm.branch_id else "",
            visit.farm.supervisor.name if visit.farm.supervisor_id else "",
            _time(visit.checked_in_at), _time(visit.checked_out_at),
            visit.duration_minutes or None,
            "Yes" if visit.latitude is not None and visit.longitude is not None else "No",
        ])
    done = [r for r in rows if r[9]]
    return columns, rows, {
        "Visits": len(rows),
        "With a check-in": sum(1 for r in rows if r[7]),
        "Average duration": (round(sum(r[9] for r in done) / len(done))
                             if done else None),
    }


def planned_vs_actual(user, filters):
    """Each planned stop beside the moment it was actually reached."""
    columns = ["Route ID", "Date", "Supervisor", "Planned #", "Farm",
               "Planned Leg (km)", "Reached At", "Actual #", "In Turn"]
    rows = []
    for route in _routes(user, filters).filter(trip__isnull=False).order_by("-date"):
        for stop in route.stops.all():
            if stop.kind != "farm":
                continue
            rows.append([
                route.route_no, route.date.strftime("%d-%m-%Y"),
                route.supervisor.name if route.supervisor_id else "",
                stop.sequence,
                stop.label or (stop.farm.farm_name if stop.farm_id else ""),
                float(stop.leg_distance_km or 0),
                _time(stop.visited_at),
                stop.actual_sequence or "",
                "—" if not stop.visited_at else ("No" if stop.is_deviation else "Yes"),
            ])
    reached = [r for r in rows if r[6]]
    return columns, rows, {
        "Planned stops": len(rows),
        "Reached": len(reached),
        "Out of turn": sum(1 for r in rows if r[8] == "No"),
    }


def route_deviation(user, filters):
    """One line per round: did the day follow the plan, and what did it cost."""
    from broiler.services.route_trip import deviation

    columns = ["Route ID", "Date", "Supervisor", "Trip", "Farms Planned",
               "Visited", "Missed", "Order Changed", "Planned (km)",
               "Actual (km)", "Extra (km)", "Efficiency %"]
    rows = []
    for route in _routes(user, filters).filter(trip__isnull=False).order_by("-date"):
        report = deviation(route)
        rows.append([
            route.route_no, route.date.strftime("%d-%m-%Y"),
            route.supervisor.name if route.supervisor_id else "",
            report["trip_no"], report["planned_farms"], report["visited_farms"],
            len(report["missed_farms"]),
            "Yes" if report["sequence_changed"] else "No",
            report["planned_distance_km"],
            report["actual_distance_km"] if report["actual_distance_known"] else None,
            report["extra_distance_km"] if report["actual_distance_known"] else None,
            report["efficiency_pct"],
        ])
    known = [r for r in rows if r[11] is not None]
    return columns, rows, {
        "Rounds driven": len(rows),
        "With an order change": sum(1 for r in rows if r[7] == "Yes"),
        "Average efficiency": (round(sum(r[11] for r in known) / len(known), 1)
                               if known else None),
    }


def gps_accuracy(user, filters):
    """How trustworthy each pin is: how good the reading was, and how old.

    A coordinate is not a fact that stays true. A fix good to two kilometres
    routes somebody to the wrong village, and a reading from two years ago was
    taken on worse hardware than today's — both are reasons to send someone
    back, and neither shows up anywhere else in the ERP.
    """
    columns = ["Farm Code", "Farm Name", "Branch", "Supervisor", "Latitude",
               "Longitude", "Accuracy (m)", "Captured On", "Age (days)",
               "Verified", "Assessment"]
    today = timezone.localdate()
    rows = []
    for farm in _farms(user, filters).exclude(farm_latitude=None).order_by("farm_name"):
        age = (today - farm.location_captured_at).days if farm.location_captured_at else None
        notes = []
        if farm.gps_accuracy is None:
            notes.append("accuracy not recorded")
        elif farm.gps_accuracy > COARSE_METRES:
            notes.append(f"coarse ({farm.gps_accuracy:.0f} m)")
        if age is None:
            notes.append("capture date unknown")
        elif age > STALE_DAYS:
            notes.append(f"{age // 365} year(s) old")
        if not farm.location_verified:
            notes.append("not verified")
        rows.append([
            farm.farm_code or "", farm.farm_name,
            farm.branch.branch_name if farm.branch_id else "",
            farm.supervisor.name if farm.supervisor_id else "",
            farm.farm_latitude, farm.farm_longitude, farm.gps_accuracy,
            farm.location_captured_at.strftime("%d-%m-%Y") if farm.location_captured_at else "",
            age, "Yes" if farm.location_verified else "No",
            "; ".join(notes) or "good",
        ])
    return columns, rows, {
        "Pinned farms": len(rows),
        "Needing attention": sum(1 for r in rows if r[10] != "good"),
        "Verified": sum(1 for r in rows if r[9] == "Yes"),
    }


def gps_missing(user, filters):
    """The farms that cannot be routed at all, and who should go and fix it."""
    columns = ["Farm Code", "Farm Name", "Branch", "Supervisor", "Farmer",
               "Location", "Status", "Last Capture Attempt"]
    from broiler.models import FarmLocationCapture

    last = {}
    for capture in FarmLocationCapture.objects.order_by("farm_id", "-date"):
        last.setdefault(capture.farm_id, capture.date)

    rows = []
    for farm in _farms(user, filters).order_by("branch__branch_name", "farm_name"):
        if farm_point(farm):
            continue
        rows.append([
            farm.farm_code or "", farm.farm_name,
            farm.branch.branch_name if farm.branch_id else "",
            farm.supervisor.name if farm.supervisor_id else "",
            farm.farmer.farmer_name if farm.farmer_id else "",
            ", ".join(p for p in (farm.area, farm.district, farm.state) if p),
            farm.farm_status or "",
            last[farm.id].strftime("%d-%m-%Y") if farm.id in last else "never",
        ])
    return columns, rows, {
        "Farms without a pin": len(rows),
        "Never attempted": sum(1 for r in rows if r[7] == "never"),
    }


def supervisor_travel(user, filters):
    """How far each supervisor was planned to go, and how far they went."""
    columns = ["Supervisor", "Branch", "Rounds", "Farms Planned",
               "Planned (km)", "Actual (km)", "Visits Made", "Efficiency %"]
    tally = {}
    for route in _routes(user, filters):
        key = (route.supervisor_id,
               route.supervisor.name if route.supervisor_id else "(unassigned)",
               route.branch.branch_name if route.branch_id else "")
        row = tally.setdefault(key, {"rounds": 0, "farms": 0, "planned": 0.0,
                                     "actual": 0.0, "visits": 0})
        row["rounds"] += 1
        row["farms"] += route.farm_count
        row["planned"] += float(route.planned_distance_km or 0)
        if route.trip_id:
            row["actual"] += float(route.trip.distance_km or 0)
            row["visits"] += route.trip.visits.filter(
                checked_in_at__isnull=False).count()

    rows = []
    for (_id, name, branch), row in sorted(tally.items(), key=lambda kv: kv[0][1]):
        rows.append([
            name, branch, row["rounds"], row["farms"],
            round(row["planned"], 1),
            round(row["actual"], 1) if row["actual"] else None,
            row["visits"],
            round(row["planned"] / row["actual"] * 100, 1) if row["actual"] else None,
        ])
    return columns, rows, {
        "Supervisors": len(rows),
        "Planned distance": round(sum(r[4] for r in rows), 1),
        "Actual distance": round(sum(r[5] or 0 for r in rows), 1) or None,
    }


def visit_compliance(user, filters):
    """Which farms are being called on, and which are being missed.

    The question a supervisor's manager actually asks: not how far anybody
    drove, but whether the farms that needed seeing were seen. A farm with a
    live flock and no visit in the window is the row this report exists for.
    """
    columns = ["Farm Code", "Farm Name", "Branch", "Supervisor", "Active Batch",
               "Priority", "Planned Visits", "Actual Visits", "Last Visit",
               "Days Since", "Compliance"]
    today = timezone.localdate()

    planned = dict(FarmRouteStop.objects
                   .filter(farm__isnull=False, route__in=_routes(user, filters))
                   .values_list("farm_id")
                   .annotate(n=Count("id")).values_list("farm_id", "n"))
    actual, last_seen = {}, {}
    for visit in _visits(user, filters).filter(checked_in_at__isnull=False):
        actual[visit.farm_id] = actual.get(visit.farm_id, 0) + 1
        when = visit.checked_in_at.date()
        if visit.farm_id not in last_seen or when > last_seen[visit.farm_id]:
            last_seen[visit.farm_id] = when

    farms = _farms(user, filters).annotate(
        live=Count("broiler_batches",
                   filter=Q(broiler_batches__end_date__isnull=True,
                            broiler_batches__is_closed=False), distinct=True))
    rows = []
    for farm in farms.order_by("branch__branch_name", "farm_name"):
        made = actual.get(farm.id, 0)
        want = planned.get(farm.id, 0)
        seen = last_seen.get(farm.id)
        if want and made >= want:
            verdict = "Met"
        elif made:
            verdict = "Partly met" if want else "Visited"
        elif farm.live:
            # The row this report is for: birds on the farm and nobody has been.
            verdict = "Not visited"
        else:
            verdict = "No visit needed"
        rows.append([
            farm.farm_code or "", farm.farm_name,
            farm.branch.branch_name if farm.branch_id else "",
            farm.supervisor.name if farm.supervisor_id else "",
            farm.live, farm.get_visit_priority_display(),
            want, made,
            seen.strftime("%d-%m-%Y") if seen else "",
            (today - seen).days if seen else None,
            verdict,
        ])
    return columns, rows, {
        "Farms": len(rows),
        "Not visited with a live flock": sum(1 for r in rows if r[10] == "Not visited"),
        "Met": sum(1 for r in rows if r[10] == "Met"),
    }


BUILDERS = {
    "farm_distance": farm_distance,
    "supervisor_route": supervisor_route,
    "farm_visit": farm_visit,
    "planned_vs_actual": planned_vs_actual,
    "route_deviation": route_deviation,
    "gps_accuracy": gps_accuracy,
    "gps_missing": gps_missing,
    "supervisor_travel": supervisor_travel,
    "visit_compliance": visit_compliance,
}


def build(key, user, filters):
    """(columns, rows, summary) for one report, or a clear failure."""
    builder = BUILDERS.get(key)
    if builder is None:
        raise KeyError(f"Unknown report {key!r}")
    return builder(user, filters)


# --- small shared formatting ------------------------------------------------


def _hm(minutes):
    minutes = int(minutes or 0)
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours}h {mins:02d}m"
    return f"{hours}h" if hours else f"{mins}m"


def _time(value):
    return timezone.localtime(value).strftime("%d-%m-%Y %H:%M") if value else ""
