"""The supervisor's own round, for the phone.

The planner is planned in the office and driven in the field, and the field
half is what this is: the day's route as a list of calls, and the two actions a
supervisor takes at each one — arriving and leaving. There is deliberately no
map here. A supervisor checking in is standing at the farm gate; what they need
is the next farm's name, its distance, and a button, not a tile layer over a
patchy signal.

Everything reuses ``broiler.services.route_trip``, which the web side uses too,
so a check-in from a phone and a check-in from a desk are the same write. What
is different is only the authentication — JWT here, a session there — and who
the caller is allowed to be.

**A supervisor sees their own round.** The web endpoints scope by branch
because a manager is looking at other people's days; here the caller *is* the
supervisor, so the default is their own routes and nobody else's. A back-office
login with no employee record behind it falls back to the branch scope, which
is what makes this usable from a tablet in the office as well.
"""
from __future__ import annotations

from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.viewsets import V1ViewMixin
from broiler.models import Branch, FarmRoute
from broiler.services.route_trip import TripError, check_in, check_out, create_trip, deviation


def _my_supervisor(user):
    """The Supervisor record behind this login, if there is one.

    Farm → Supervisor → Employee → User is the chain the ERP already keeps;
    this walks it backwards from the login.
    """
    from broiler.models import Supervisor

    return (Supervisor.objects.filter(employee__user=user)
            .select_related("employee", "branch").first())


def _visible_routes(user):
    """Routes this caller may act on.

    Their own if they are a supervisor; otherwise whatever their branch scope
    allows, so the office can drive the same endpoints.
    """
    from user.services.scoping import branches_for

    routes = (FarmRoute.objects
              .select_related("branch", "supervisor", "trip")
              .prefetch_related("stops__farm"))
    supervisor = _my_supervisor(user)
    if supervisor is not None:
        return routes.filter(supervisor=supervisor)
    allowed = set(branches_for(user, Branch.objects.all()).values_list("id", flat=True))
    return routes.filter(branch_id__in=allowed)


def _checked_out_farm_ids(route):
    """Farms this round has already been checked out of.

    One query for the whole round rather than one per stop: the phone polls
    this payload, so a dozen farms was a dozen extra queries every time a
    supervisor's screen refreshed.
    """
    if not route.trip_id:
        return set()
    return set(route.trip.visits
               .filter(checked_out_at__isnull=False)
               .values_list("farm_id", flat=True))


def _stop_payload(stop, left_ids):
    farm = stop.farm
    return {
        "sequence": stop.sequence,
        "kind": stop.kind,
        "farm_id": stop.farm_id,
        "farm_code": farm.farm_code if stop.farm_id else "",
        "label": stop.label or (farm.farm_name if stop.farm_id else ""),
        "latitude": stop.latitude,
        "longitude": stop.longitude,
        "leg_distance_km": float(stop.leg_distance_km or 0),
        "leg_minutes": stop.leg_minutes,
        "cumulative_distance_km": float(stop.cumulative_distance_km or 0),
        "priority": stop.priority or "",
        "visited_at": stop.visited_at.isoformat() if stop.visited_at else None,
        # What the phone puts on the button. Worked out here rather than in the
        # app so the two cannot disagree about whether a call is still open.
        "state": ("done" if stop.visited_at and stop.farm_id in left_ids
                  else "here" if stop.visited_at else "pending"),
    }


def _route_payload(route):
    stops = list(route.stops.all())
    left_ids = _checked_out_farm_ids(route)
    return {
        "id": route.id,
        "route_no": route.route_no,
        "date": route.date.isoformat(),
        "status": route.status,
        "supervisor": route.supervisor.name if route.supervisor_id else "",
        "branch": route.branch.branch_name if route.branch_id else "",
        "start_label": route.start_label,
        "start_latitude": route.start_latitude,
        "start_longitude": route.start_longitude,
        "farm_count": route.farm_count,
        "distance_km": float(route.planned_distance_km or 0),
        "minutes": route.planned_minutes,
        "duration_label": route.duration_label,
        # An estimate says so all the way down to the phone, so a supervisor is
        # never quoted a straight-line figure as though it were a road one.
        "estimated": route.distance_basis == FarmRoute.BASIS_STRAIGHT,
        "trip_id": route.trip_id,
        "trip_no": route.trip.trip_no if route.trip_id else "",
        "stops": [_stop_payload(s, left_ids) for s in stops],
    }


class MyRouteView(V1ViewMixin, APIView):
    """GET /api/v1/broiler/my-route[?date=YYYY-MM-DD] — the day's round.

    Answers with the route rather than a list of them: a supervisor drives one
    round a day, and a screen that made them pick from a list before showing
    the first farm would be a screen in the way. When there is more than one
    the earliest unfinished wins, which is the one they are on.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        day = (request.query_params.get("date") or "").strip()
        routes = _visible_routes(request.user)
        routes = routes.filter(date=day) if day else routes.filter(
            date=timezone.localdate())
        route = (routes.exclude(status=FarmRoute.STATUS_CANCELLED)
                 .order_by("status", "id").first())
        if route is None:
            return Response({"route": None,
                             "message": "No round is planned for this day."})
        return Response({"route": _route_payload(route),
                         "deviation": deviation(route)})


class RouteActionView(V1ViewMixin, APIView):
    """Base for the three things a supervisor does to a round from the road."""

    permission_classes = [IsAuthenticated]

    def get_route(self, request, pk):
        return _visible_routes(request.user).filter(pk=pk).first()

    def fail(self, message, status=400):
        return Response({"error": message}, status=status)


class StartTripView(RouteActionView):
    """POST /api/v1/broiler/routes/<pk>/start-trip — raise the day's trip."""

    def post(self, request, pk):
        route = self.get_route(request, pk)
        if route is None:
            return self.fail("That round is not yours to start.", 404)
        try:
            trip = create_trip(route, created_by=request.user)
        except TripError as exc:
            return self.fail(str(exc))
        return Response({"trip_id": trip.id, "trip_no": trip.trip_no,
                         "route": _route_payload(route)})


class CheckInView(RouteActionView):
    """POST /api/v1/broiler/routes/<pk>/check-in — arrived at a farm.

    The phone sends its own fix. It is recorded as given: where the supervisor
    actually was is the evidence, and correcting it towards the farm's pin
    would destroy the only thing that makes a check-in worth anything.
    """

    def post(self, request, pk):
        return self._act(request, pk, check_in)

    def _act(self, request, pk, action):
        route = self.get_route(request, pk)
        if route is None:
            return self.fail("That round is not yours.", 404)
        farm_id = request.data.get("farm_id")
        if not farm_id:
            return self.fail("Which farm?")
        try:
            visit = action(route, int(farm_id),
                           latitude=request.data.get("latitude"),
                           longitude=request.data.get("longitude"))
        except TripError as exc:
            return self.fail(str(exc))
        except (TypeError, ValueError):
            return self.fail("That farm id is not a number.")
        route.refresh_from_db()
        return Response({
            "farm_id": visit.farm_id,
            "checked_in_at": (visit.checked_in_at.isoformat()
                              if visit.checked_in_at else None),
            "checked_out_at": (visit.checked_out_at.isoformat()
                               if visit.checked_out_at else None),
            "duration_minutes": visit.duration_minutes,
            "route": _route_payload(route),
        })


class CheckOutView(CheckInView):
    """POST /api/v1/broiler/routes/<pk>/check-out — leaving the farm."""

    def post(self, request, pk):
        return self._act(request, pk, check_out)


def route_urls() -> list:
    """URL patterns for the supervisor's own round."""
    from django.urls import path

    return [
        path("broiler/my-route", MyRouteView.as_view(), name="broiler-my-route"),
        path("broiler/routes/<int:pk>/start-trip", StartTripView.as_view(),
             name="broiler-route-start-trip"),
        path("broiler/routes/<int:pk>/check-in", CheckInView.as_view(),
             name="broiler-route-check-in"),
        path("broiler/routes/<int:pk>/check-out", CheckOutView.as_view(),
             name="broiler-route-check-out"),
    ]
