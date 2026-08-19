"""Farm Map & Route Planner — the page and the endpoints behind it.

Kept in its own module rather than added to ``broiler.views``, which is
already several thousand lines: everything here is about pins, roads and
rounds, and none of it is needed by any other broiler screen.

Three things this module is careful about.

**It shows a user only their own farms.** Every query goes through
``user.services.scoping``, the same helpers the reports use, so a supervisor
scoped to one branch cannot see another branch's pins by calling the endpoint
directly. The filter bar narrowing what it offers is a convenience; the
scoping is the rule.

**It never invents a coordinate.** A farm with no pin comes back in its own
list with a link to Farm Location Capture, and is refused entry to a route.

**It does not save while you think.** Calculating a route writes nothing;
saving is a separate, deliberate call. A planner that recorded every drag of a
filter would fill the table with rounds nobody drove.
"""
from __future__ import annotations

import json
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Max, OuterRef, Q, Subquery
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from broiler.models import (BirdSale, Branch, BroilerBatch, BroilerFarm,
                            DailyEntry, FarmRoute, FarmRouteStop, Supervisor)
from broiler.services.route_planner import (PlannerError, farm_point, plan_route,
                                            save_route, split_by_gps)
from broiler.services.routing import RoutingError
from user.services.scoping import branches_for, farms_for, supervisors_for


def _visible_farms(user):
    """Farms this login may see, with everything the map needs joined in."""
    return (farms_for(user, BroilerFarm.objects.all())
            .select_related("branch", "supervisor", "farmer"))


def _int(value):
    value = (value or "").strip() if isinstance(value, str) else value
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _start_point(user, branch_id, payload=None):
    """Where the day begins.

    A start point given explicitly wins — a supervisor may set off from home.
    Otherwise it is the chosen branch, if somebody has pinned it; the branch
    is the head office for this purpose. With neither, the caller is told to
    pick one rather than being routed from the middle of the Bay of Bengal,
    which is where (0, 0) is.
    """
    payload = payload or {}
    lat, lng = payload.get("start_latitude"), payload.get("start_longitude")
    if lat is not None and lng is not None:
        return (payload.get("start_label") or "Start", float(lat), float(lng))

    branch = None
    if branch_id:
        branch = branches_for(user, Branch.objects.filter(id=branch_id)).first()
    if branch and getattr(branch, "latitude", None) and getattr(branch, "longitude", None):
        return (branch.branch_name, float(branch.latitude), float(branch.longitude))
    return None


@login_required
def farm_map_planner(request):
    """Broiler > Utilities > Map & Route Planner."""
    user = request.user
    farms = _visible_farms(user)
    routable, missing = split_by_gps(farms)
    branch_rows = list(branches_for(user, Branch.objects.order_by("branch_name")))
    # Head-office pins, so the page can start a round at the chosen branch
    # without another request. A branch nobody has pinned simply is not in the
    # map, and the planner asks for a start point instead of guessing one.
    branch_points = {b.id: {"name": b.branch_name,
                            "latitude": b.latitude, "longitude": b.longitude}
                     for b in branch_rows
                     if b.latitude is not None and b.longitude is not None}
    return render(request, "farm_map_planner.html", {
        "active_tab": "farm_map_planner",
        "branches": branch_rows,
        "branch_points_json": json.dumps(branch_points),
        "supervisors": supervisors_for(user, Supervisor.objects.order_by("name")),
        "priorities": BroilerFarm.VISIT_PRIORITY_CHOICES,
        "route_modes": FarmRoute.MODE_CHOICES,
        "total_farms": len(routable) + len(missing),
        "mapped_farms": len(routable),
        "missing_farms": len(missing),
        "today": timezone.localdate(),
    })


@login_required
def farm_map_data(request):
    """The pins, and everything the popup shows.

    One request for the whole map rather than one per farm: a district has a
    few hundred farms and a popup that fetched on click would be a request per
    marker on a phone signal.
    """
    user = request.user
    farms = _visible_farms(user)

    branch_id = _int(request.GET.get("branch"))
    supervisor_id = _int(request.GET.get("supervisor"))
    farm_id = _int(request.GET.get("farm"))
    status = (request.GET.get("farm_status") or "").strip()
    priority = (request.GET.get("priority") or "").strip()
    batch_status = (request.GET.get("batch_status") or "").strip()

    if branch_id:
        farms = farms.filter(branch_id=branch_id)
    if supervisor_id:
        farms = farms.filter(supervisor_id=supervisor_id)
    if farm_id:
        farms = farms.filter(id=farm_id)
    if status:
        farms = farms.filter(farm_status__iexact=status)
    if priority:
        farms = farms.filter(visit_priority=priority)

    # Live flocks per farm, plus the flock's own name and the last time anybody
    # called there. All annotated rather than fetched per row: this is the
    # query that would otherwise make a 300-farm map 900 queries, and the farm
    # list wants every one of these columns.
    from django.db.models import IntegerField, Sum, Value
    from django.db.models.functions import Coalesce
    from hr.models import SupervisorTripVisit
    from inventory.models import StockTransfer

    from broiler.views import chick_items

    # Birds standing on the farm: placed, less lost, less lifted. Three
    # aggregates, all as subqueries against the farm's live flock, so the map
    # stays one query however many farms it draws. It is the same arithmetic
    # the Live Flock Summary does, at the resolution a map marker needs.
    chick_ids = list(chick_items().values_list("id", flat=True))
    placed = (StockTransfer.objects
              .filter(to_farm=OuterRef("pk"), item_id__in=chick_ids,
                      to_batch__end_date__isnull=True, to_batch__is_closed=False)
              .values("to_farm").annotate(n=Sum("quantity")).values("n")[:1])
    lost = (DailyEntry.objects
            .filter(farm=OuterRef("pk"), batch__end_date__isnull=True,
                    batch__is_closed=False)
            .values("farm").annotate(n=Sum("mortality") + Sum("culls")).values("n")[:1])
    lifted = (BirdSale.objects
              .filter(farm=OuterRef("pk"), batch__end_date__isnull=True,
                      batch__is_closed=False)
              .values("farm").annotate(n=Sum("birds")).values("n")[:1])

    live = BroilerBatch.objects.filter(
        broiler_farm=OuterRef("pk"), end_date__isnull=True, is_closed=False)
    farms = farms.annotate(
        active_batches=Count("broiler_batches",
                             filter=Q(broiler_batches__end_date__isnull=True,
                                      broiler_batches__is_closed=False),
                             distinct=True),
        batch_code=Subquery(live.order_by("start_date").values("batch_name")[:1]),
        batch_started=Subquery(live.order_by("start_date").values("start_date")[:1]),
        last_visit=Subquery(
            SupervisorTripVisit.objects
            .filter(farm=OuterRef("pk"), checked_in_at__isnull=False)
            .order_by("-checked_in_at").values("checked_in_at")[:1]),
        placed_birds=Coalesce(Subquery(placed, output_field=IntegerField()), Value(0)),
        lost_birds=Coalesce(Subquery(lost, output_field=IntegerField()), Value(0)),
        lifted_birds=Coalesce(Subquery(lifted, output_field=IntegerField()), Value(0)),
    )
    if batch_status == "active":
        farms = farms.filter(active_batches__gt=0)
    elif batch_status == "empty":
        farms = farms.filter(active_batches=0)

    rows, missing = [], []
    for farm in farms.order_by("farm_name"):
        point = farm_point(farm)
        common = {
            "id": farm.id,
            "code": farm.farm_code or "",
            "name": farm.farm_name,
            "branch": farm.branch.branch_name if farm.branch_id else "",
            "branch_id": farm.branch_id,
            "supervisor": farm.supervisor.name if farm.supervisor_id else "",
            "supervisor_id": farm.supervisor_id,
            "farmer": farm.farmer.farmer_name if farm.farmer_id else "",
            "status": farm.farm_status or "",
            "priority": farm.visit_priority,
            "active_batches": farm.active_batches,
            "batch_code": farm.batch_code or "",
            "batch_age": ((timezone.localdate() - farm.batch_started).days
                          if farm.batch_started else None),
            # Never negative: a farm whose recorded sales exceed what its
            # entries say survived is a data problem to fix, not a negative
            # head count to print on a map.
            "live_birds": (max(int(farm.placed_birds - farm.lost_birds
                                   - farm.lifted_birds), 0)
                           if farm.active_batches else 0),
            "last_visit": (timezone.localtime(farm.last_visit).date().isoformat()
                           if farm.last_visit else None),
            "location": ", ".join(p for p in (farm.area, farm.district, farm.state) if p),
        }
        if point:
            rows.append({**common, "latitude": point[0], "longitude": point[1],
                         "gps_accuracy": farm.gps_accuracy,
                         "location_captured_at": (farm.location_captured_at.isoformat()
                                                  if farm.location_captured_at else None),
                         "location_verified": farm.location_verified})
        else:
            missing.append(common)

    return JsonResponse({"farms": rows, "gps_missing": missing,
                         "counts": {"total": len(rows) + len(missing),
                                    "mapped": len(rows), "missing": len(missing)}})


@login_required
def farm_map_batch(request, farm_id):
    """The live flock behind a marker popup — the production half of section 7.

    Fetched on demand rather than with the pins, because it is several joins
    per farm and most markers are never opened.
    """
    farm = _visible_farms(request.user).filter(id=farm_id).first()
    if farm is None:
        return JsonResponse({"error": "Farm not found, or not one you may see."},
                            status=404)

    from broiler.views import _build_batch_report

    batches = []
    live = (BroilerBatch.objects
            .filter(broiler_farm=farm, end_date__isnull=True, is_closed=False)
            .select_related("breed", "shed").order_by("start_date"))
    for batch in live:
        costing = (_build_batch_report(batch) or {}).get("batch_costing") or {}
        placed = costing.get("chicks_placed") or 0
        batches.append({
            "id": batch.id,
            "batch_no": batch.batch_name or batch.lot_no or "",
            "age": ((timezone.localdate() - batch.start_date).days
                    if batch.start_date else None),
            "bird_type": (batch.breed.bird_category.name
                          if batch.breed_id and batch.breed.bird_category_id else ""),
            "breed": batch.breed.breed_name if batch.breed_id else "",
            "shed": batch.shed.shed_name if batch.shed_id else "",
            "opening_birds": placed,
            # What is still standing: placed, less lost, less lifted. The
            # costing engine calls it excess_birds.
            "live_birds": costing.get("excess_birds"),
            "mortality_pct": costing.get("total_mort_pct"),
            "avg_weight": costing.get("avg_body_weight"),
            "fcr": costing.get("fcr"),
            "cfcr": costing.get("cfcr"),
        })

    from hr.models import SupervisorTripVisit

    last = (SupervisorTripVisit.objects.filter(farm=farm, checked_in_at__isnull=False)
            .order_by("-checked_in_at").values_list("checked_in_at", flat=True).first())
    return JsonResponse({
        "farm": {"id": farm.id, "name": farm.farm_name, "code": farm.farm_code or ""},
        "batches": batches,
        "last_visit": last.isoformat() if last else None,
    })


@login_required
@require_POST
def farm_route_calculate(request):
    """Work out a round. Writes nothing.

    Every failure here is something the person on the screen can act on, so
    each comes back as a sentence rather than a status code: which farms have
    no GPS, that the provider is down, that the round is too long.
    """
    try:
        payload = json.loads(request.body or "{}")
    except ValueError:
        return JsonResponse({"error": "Could not read the request."}, status=400)

    farm_ids = [i for i in (_int(v) for v in (payload.get("farm_ids") or [])) if i]
    if not farm_ids:
        return JsonResponse(
            {"error": "Select the farms to visit before calculating a route."},
            status=400)

    farms = list(_visible_farms(request.user).filter(id__in=farm_ids))
    found = {f.id for f in farms}
    if len(found) < len(set(farm_ids)):
        return JsonResponse(
            {"error": "Some selected farms are not available to you any more. "
                      "Refresh the map and try again."}, status=403)
    # Keep the order the user picked; the optimiser decides the real order.
    farms.sort(key=lambda f: farm_ids.index(f.id))

    routable, missing = split_by_gps(farms)
    if missing:
        names = ", ".join(f.farm_name for f in missing[:5])
        more = f" and {len(missing) - 5} more" if len(missing) > 5 else ""
        return JsonResponse({
            "error": (f"{len(missing)} selected farm"
                      f"{'s do' if len(missing) != 1 else ' does'} not have GPS "
                      f"coordinates ({names}{more}). Capture their farm locations "
                      f"before generating the route."),
            "gps_missing": [{"id": f.id, "name": f.farm_name,
                             "code": f.farm_code or "",
                             "supervisor": (f.supervisor.name
                                            if f.supervisor_id else "")}
                            for f in missing],
        }, status=422)

    branch_id = _int(payload.get("branch"))
    start = _start_point(request.user, branch_id, payload)
    if start is None:
        return JsonResponse(
            {"error": "This route has no starting point. Choose a branch that has "
                      "a location, or set a start point on the map."}, status=400)

    mode = (payload.get("mode") or "distance").strip()
    roundtrip = bool(payload.get("roundtrip", True))
    try:
        plan = plan_route(start=start, farms=routable, mode=mode, roundtrip=roundtrip)
    except PlannerError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except RoutingError as exc:
        return JsonResponse({"error": str(exc)}, status=503)

    plan["start"] = {"label": start[0], "latitude": start[1], "longitude": start[2]}
    return JsonResponse(plan)


@login_required
@require_POST
def farm_route_save(request):
    """Keep a calculated round, so it can be driven, repeated or compared."""
    try:
        payload = json.loads(request.body or "{}")
    except ValueError:
        return JsonResponse({"error": "Could not read the request."}, status=400)

    plan = payload.get("plan") or {}
    if not plan.get("stops"):
        return JsonResponse({"error": "Calculate a route before saving it."},
                            status=400)

    branch_id, supervisor_id = _int(payload.get("branch")), _int(payload.get("supervisor"))
    branch = branches_for(request.user, Branch.objects.filter(id=branch_id)).first()
    supervisor = supervisors_for(
        request.user, Supervisor.objects.filter(id=supervisor_id)).first()

    start = plan.get("start") or {}
    route = save_route(
        plan,
        name=(payload.get("name") or "").strip(),
        date=payload.get("date") or timezone.localdate(),
        branch=branch, supervisor=supervisor,
        mode=(payload.get("mode") or "distance").strip(),
        start=(start.get("label") or "Start", start.get("latitude"),
               start.get("longitude")),
        roundtrip=bool(payload.get("roundtrip", True)),
        created_by=request.user,
    )
    return JsonResponse({"id": route.id, "route_no": route.route_no,
                         "status": route.status})


# --- the round as it is actually driven -----------------------------------


def _route_for(user, route_id):
    """A saved route this login may act on.

    Scoped through the branch and the supervisor rather than by who created
    it: a round is the branch's work, and a manager standing in for somebody
    on leave has to be able to open it.
    """
    routes = FarmRoute.objects.select_related("supervisor", "branch", "trip")
    route = routes.filter(id=route_id).first()
    if route is None:
        return None
    allowed_branches = branches_for(user, Branch.objects.all()).values_list("id", flat=True)
    if route.branch_id and route.branch_id not in set(allowed_branches):
        return None
    return route


@login_required
def route_history(request):
    """Broiler > Utilities > Route History — the rounds that have been saved."""
    routes = (FarmRoute.objects.select_related("branch", "supervisor", "trip",
                                               "created_by")
              .prefetch_related("stops"))
    allowed = set(branches_for(request.user, Branch.objects.all())
                  .values_list("id", flat=True))
    routes = routes.filter(Q(branch__isnull=True) | Q(branch_id__in=allowed))

    branch_id = _int(request.GET.get("branch"))
    supervisor_id = _int(request.GET.get("supervisor"))
    status = (request.GET.get("status") or "").strip()
    from_date = (request.GET.get("from_date") or "").strip()
    to_date = (request.GET.get("to_date") or "").strip()
    if branch_id:
        routes = routes.filter(branch_id=branch_id)
    if supervisor_id:
        routes = routes.filter(supervisor_id=supervisor_id)
    if status:
        routes = routes.filter(status=status)
    if from_date:
        routes = routes.filter(date__gte=from_date)
    if to_date:
        routes = routes.filter(date__lte=to_date)

    return render(request, "farm_route_history.html", {
        "active_tab": "route_history",
        "routes": routes[:300],
        "branches": branches_for(request.user, Branch.objects.order_by("branch_name")),
        "supervisors": supervisors_for(request.user, Supervisor.objects.order_by("name")),
        "statuses": FarmRoute.STATUS_CHOICES,
        "branch_id": branch_id or "",
        "supervisor_id": supervisor_id or "",
        "status": status,
        "from_date": from_date,
        "to_date": to_date,
    })


@login_required
def route_detail(request, route_id):
    """One round: what was planned, what was driven, and the gap."""
    from broiler.services.route_trip import deviation

    route = _route_for(request.user, route_id)
    if route is None:
        return JsonResponse({"error": "Route not found, or not one you may see."},
                            status=404)
    stops = route.stops.select_related("farm").order_by("sequence")
    return JsonResponse({
        "route": {
            "id": route.id, "route_no": route.route_no, "name": route.name,
            "date": route.date.isoformat(), "status": route.status,
            "mode": route.get_mode_display(),
            "branch": route.branch.branch_name if route.branch_id else "",
            "supervisor": route.supervisor.name if route.supervisor_id else "",
            "distance_km": float(route.planned_distance_km),
            "minutes": route.planned_minutes,
            "duration_label": route.duration_label,
            "basis": route.distance_basis, "provider": route.provider,
            "trip_no": route.trip.trip_no if route.trip_id else "",
            "geometry": route.geometry,
        },
        "stops": [{
            "sequence": s.sequence, "kind": s.kind,
            "farm_id": s.farm_id,
            "label": s.label or (s.farm.farm_name if s.farm_id else ""),
            "latitude": s.latitude, "longitude": s.longitude,
            "leg_distance_km": float(s.leg_distance_km),
            "leg_minutes": s.leg_minutes,
            "cumulative_distance_km": float(s.cumulative_distance_km),
            "cumulative_minutes": s.cumulative_minutes,
            "priority": s.priority,
            "visited_at": s.visited_at.isoformat() if s.visited_at else None,
            "actual_sequence": s.actual_sequence,
        } for s in stops],
        "deviation": deviation(route),
    })


@login_required
@require_POST
def route_start_trip(request, route_id):
    """Create the Supervisor Daily Trip this round is driven as."""
    from broiler.services.route_trip import TripError, create_trip

    route = _route_for(request.user, route_id)
    if route is None:
        return JsonResponse({"error": "Route not found, or not one you may see."},
                            status=404)
    try:
        trip = create_trip(route, created_by=request.user)
    except TripError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"trip_id": trip.id, "trip_no": trip.trip_no,
                         "route_status": route.status})


@login_required
@require_POST
def route_check_in(request, route_id):
    """GPS check-in at a farm on the round."""
    from broiler.services.route_trip import TripError, check_in

    return _check(request, route_id, check_in, TripError)


@login_required
@require_POST
def route_check_out(request, route_id):
    """GPS check-out, which is what makes the visit a duration."""
    from broiler.services.route_trip import TripError, check_out

    return _check(request, route_id, check_out, TripError)


def _check(request, route_id, action, error_class):
    route = _route_for(request.user, route_id)
    if route is None:
        return JsonResponse({"error": "Route not found, or not one you may see."},
                            status=404)
    try:
        payload = json.loads(request.body or "{}")
    except ValueError:
        return JsonResponse({"error": "Could not read the request."}, status=400)
    farm_id = _int(payload.get("farm_id"))
    if not farm_id:
        return JsonResponse({"error": "Which farm?"}, status=400)
    try:
        visit = action(route, farm_id,
                       latitude=payload.get("latitude"),
                       longitude=payload.get("longitude"))
    except error_class as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({
        "farm_id": visit.farm_id,
        "checked_in_at": visit.checked_in_at.isoformat() if visit.checked_in_at else None,
        "checked_out_at": visit.checked_out_at.isoformat() if visit.checked_out_at else None,
        "duration_minutes": visit.duration_minutes,
    })


# --- reports ---------------------------------------------------------------


@login_required
def route_reports(request):
    """Broiler > Utilities > Route & Visit Reports.

    One page and one permission for the nine reports, because they are nine
    questions about the same three tables. Nine pages would be nine filter
    bars and nine places for the scoping to be got wrong.
    """
    from broiler.services import route_reports as reports

    key = (request.GET.get("report") or reports.REPORTS[0][0]).strip()
    if key not in reports.BUILDERS:
        key = reports.REPORTS[0][0]
    filters = {
        "branch": _int(request.GET.get("branch")),
        "supervisor": _int(request.GET.get("supervisor")),
        "from_date": (request.GET.get("from_date") or "").strip() or None,
        "to_date": (request.GET.get("to_date") or "").strip() or None,
    }
    submitted = any(request.GET.get(k) for k in
                    ("report", "branch", "supervisor", "from_date", "to_date"))

    columns, rows, summary = ([], [], {})
    if submitted:
        columns, rows, summary = reports.build(key, request.user, filters)
        if (request.GET.get("export") or "").strip().lower() == "excel":
            return _route_report_excel(key, columns, rows)

    return render(request, "farm_route_reports.html", {
        "active_tab": "route_reports",
        "reports": reports.REPORTS,
        "report_key": key,
        "report_label": dict(reports.REPORTS)[key],
        "columns": columns, "rows": rows, "summary": summary,
        "submitted": submitted,
        "branches": branches_for(request.user, Branch.objects.order_by("branch_name")),
        "supervisors": supervisors_for(request.user, Supervisor.objects.order_by("name")),
        "branch_id": filters["branch"] or "",
        "supervisor_id": filters["supervisor"] or "",
        "from_date": filters["from_date"] or "",
        "to_date": filters["to_date"] or "",
    })


def _route_report_excel(key, columns, rows):
    """The same columns the screen shows, so the two cannot disagree."""
    import io as _io

    from django.http import HttpResponse
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = key[:31]
    sheet.append(columns)
    for row in rows:
        sheet.append(["" if cell is None else cell for cell in row])
    buffer = _io.BytesIO()
    book.save(buffer)
    response = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="{key}.xlsx"'
    return response


@login_required
@require_POST
def route_duplicate(request, route_id):
    """Copy a round onto another day, unstarted.

    The most common way a route is made is that last week's worked. Copying
    leaves the original's journey alone — the trip, the check-ins and the
    deviation all stay attached to the round that was actually driven — and the
    copy comes back as a draft nobody has started.

    The stored geometry and distances come with it: the roads have not moved,
    and re-measuring would spend a provider call to be told the same thing.
    Recalculate is there for when they have.
    """
    from broiler.models import FarmRouteStop

    route = _route_for(request.user, route_id)
    if route is None:
        return JsonResponse({"error": "Route not found, or not one you may see."},
                            status=404)
    try:
        payload = json.loads(request.body or "{}")
    except ValueError:
        payload = {}
    stops = list(route.stops.all().order_by("sequence"))

    copy = FarmRoute.objects.create(
        name=route.name, date=payload.get("date") or timezone.localdate(),
        branch=route.branch, supervisor=route.supervisor,
        start_label=route.start_label, start_latitude=route.start_latitude,
        start_longitude=route.start_longitude,
        end_label=route.end_label, end_latitude=route.end_latitude,
        end_longitude=route.end_longitude,
        returns_to_start=route.returns_to_start, mode=route.mode,
        status=FarmRoute.STATUS_PLANNED,
        distance_basis=route.distance_basis, provider=route.provider,
        planned_distance_km=route.planned_distance_km,
        planned_minutes=route.planned_minutes, geometry=route.geometry,
        created_by=request.user,
    )
    FarmRouteStop.objects.bulk_create([
        FarmRouteStop(
            route=copy, sequence=s.sequence, kind=s.kind, farm_id=s.farm_id,
            label=s.label, latitude=s.latitude, longitude=s.longitude,
            leg_distance_km=s.leg_distance_km, leg_minutes=s.leg_minutes,
            cumulative_distance_km=s.cumulative_distance_km,
            cumulative_minutes=s.cumulative_minutes, priority=s.priority,
        ) for s in stops
    ])
    return JsonResponse({"id": copy.id, "route_no": copy.route_no,
                         "date": copy.date.isoformat()})


@login_required
@require_POST
def route_recalculate(request, route_id):
    """Measure the same farms again, in case the roads or the pins have moved.

    The same stops in the same order are re-measured rather than re-optimised,
    unless the round has not been driven yet — a plan somebody has started
    following must not have its order changed underneath them, and one that has
    not can be improved.

    A round that has already been driven is refused outright: its distances are
    what its trip was compared against, and quietly re-measuring them would
    change a deviation report after the fact.
    """
    from broiler.services.route_planner import PlannerError, plan_route, split_by_gps
    from broiler.services.routing import RoutingError

    route = _route_for(request.user, route_id)
    if route is None:
        return JsonResponse({"error": "Route not found, or not one you may see."},
                            status=404)
    if route.trip_id:
        return JsonResponse(
            {"error": f"Route {route.route_no} has already been driven as trip "
                      f"{route.trip.trip_no}. Its distances are what that trip is "
                      f"measured against. Duplicate it instead."}, status=400)

    stops = list(route.stops.filter(farm__isnull=False).order_by("sequence")
                 .select_related("farm"))
    farms = [s.farm for s in stops]
    routable, missing = split_by_gps(farms)
    if missing:
        return JsonResponse(
            {"error": f"{len(missing)} farm(s) on this round no longer have GPS "
                      f"coordinates: {', '.join(f.farm_name for f in missing)}."},
            status=422)
    if route.start_latitude is None or route.start_longitude is None:
        return JsonResponse({"error": "This round has no starting point to "
                                      "measure from."}, status=400)

    try:
        plan = plan_route(
            start=(route.start_label or "Start", route.start_latitude,
                   route.start_longitude),
            farms=routable, mode=route.mode, roundtrip=route.returns_to_start)
    except PlannerError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except RoutingError as exc:
        return JsonResponse({"error": str(exc)}, status=503)

    before = float(route.planned_distance_km or 0)
    with transaction.atomic():
        route.stops.all().delete()
        route.planned_distance_km = Decimal(str(plan["distance_km"]))
        route.planned_minutes = int(plan["minutes"])
        route.geometry = plan["geometry"]
        route.provider = plan["provider"] or ""
        route.distance_basis = (FarmRoute.BASIS_ROAD if plan["basis"] == "road"
                                else FarmRoute.BASIS_STRAIGHT)
        route.save()
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
    return JsonResponse({
        "id": route.id, "route_no": route.route_no,
        "distance_km": plan["distance_km"], "minutes": plan["minutes"],
        "was_km": round(before, 2),
        "changed_km": round(plan["distance_km"] - before, 2),
        "estimated": plan["estimated"],
    })
