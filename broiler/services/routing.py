"""Road distances and travel times, from whichever provider is configured.

Everything in the Farm Map & Route Planner that needs to know how far apart
two farms are asks this module, and nothing outside it knows which provider
answered. That is the whole point: routing is bought, providers change, and a
`requests.get("https://router.project-osrm.org/...")` scattered through six
views is how a project ends up unable to change one.

**Never a straight line, unless it says so.** The great-circle distance
between two pins understates a hill road by half and a river crossing by
whatever the bridge is worth; settling a travel claim on it would be wrong in
the company's favour or the supervisor's, and nobody could tell which. So the
providers here speak to a real road network, and the one fallback that does
not — :class:`StraightLineProvider` — stamps every answer ``basis="straight"``
so the screen above can label it an estimate. A silent fallback would be worse
than an error.

Configuration, all through the environment (see settings.ROUTING):

    ROUTING_PROVIDER      osrm | openrouteservice | google | straight
    ROUTING_API_KEY       the provider's key, where one is needed
    ROUTING_BASE_URL      override for a self-hosted OSRM/ORS
    ROUTING_TIMEOUT       seconds, default 20

``osrm`` needs no key and is the default, pointed at the public demo server.
That server is rate-limited and explicitly not for production use — for real
traffic either self-host OSRM and set ROUTING_BASE_URL, or set a key and use
openrouteservice or google.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

#: Providers charge per call and a filter bar invites re-planning the same day
#: over and over, so an identical question inside this window is answered from
#: the cache. Keyed on the exact coordinate list and mode, so it can only ever
#: return the answer to the question actually asked.
CACHE_SECONDS = 60 * 60


class RoutingError(Exception):
    """The provider could not answer. Carries a sentence fit to show a user."""


@dataclass
class Leg:
    """One hop, from one stop to the next."""

    distance_km: float = 0.0
    minutes: int = 0


@dataclass
class RouteResult:
    """What a provider came back with.

    ``order`` is the sequence the stops should be visited in, as indices into
    the waypoint list that was asked about — the optimiser's answer, or simply
    0..n when the caller asked for the order it gave.
    """

    legs: list = field(default_factory=list)
    order: list = field(default_factory=list)
    geometry: object = None
    provider: str = ""
    basis: str = "road"

    @property
    def distance_km(self) -> float:
        return round(sum(leg.distance_km for leg in self.legs), 2)

    @property
    def minutes(self) -> int:
        return int(sum(leg.minutes for leg in self.legs))


def haversine_km(a, b) -> float:
    """Great-circle kilometres between two (lat, lng) pairs.

    Used for the fallback and for sanity checks, never presented as a driving
    distance without the accompanying ``basis`` saying what it is.
    """
    lat1, lng1 = float(a[0]), float(a[1])
    lat2, lng2 = float(b[0]), float(b[1])
    radius = 6371.0088
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    h = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlng / 2) ** 2)
    return round(2 * radius * math.asin(math.sqrt(h)), 3)


class BaseProvider:
    """What every provider has to be able to do.

    Two questions, because route optimisation needs both: "how long is this
    exact round" and "how far is everything from everything", the second being
    what an ordering algorithm works over.
    """

    name = "base"
    basis = "road"

    def route(self, points, mode="distance"):
        raise NotImplementedError

    def matrix(self, points, mode="distance"):
        raise NotImplementedError


class StraightLineProvider(BaseProvider):
    """No network, no provider, no road: pins joined by ruler.

    Here so the module still works when routing is unconfigured or the
    provider is down — a planner that shows nothing at all is less useful than
    one that shows an order and admits its kilometres are estimates. Every
    answer is stamped ``basis="straight"`` and the UI is expected to say so.

    The road factor is the usual rule of thumb: real roads run about a fifth
    longer than the crow flies. It makes the estimate less wrong, not right.
    """

    name = "straight"
    basis = "straight"
    ROAD_FACTOR = 1.2
    AVERAGE_KMPH = 40.0

    def _leg(self, a, b) -> Leg:
        km = round(haversine_km(a, b) * self.ROAD_FACTOR, 2)
        return Leg(distance_km=km, minutes=int(round(km / self.AVERAGE_KMPH * 60)))

    def route(self, points, mode="distance"):
        legs = [self._leg(points[i], points[i + 1]) for i in range(len(points) - 1)]
        return RouteResult(legs=legs, order=list(range(len(points))),
                           geometry={"type": "points",
                                     "coordinates": [[p[0], p[1]] for p in points]},
                           provider=self.name, basis=self.basis)

    def matrix(self, points, mode="distance"):
        return [[self._leg(a, b).distance_km if mode == "distance"
                 else self._leg(a, b).minutes
                 for b in points] for a in points]


class OSRMProvider(BaseProvider):
    """Open Source Routing Machine — the default, and free of keys.

    The public demo server is rate limited and the project asks that it not be
    used for production traffic; point ROUTING_BASE_URL at your own instance
    when this stops being a pilot.
    """

    name = "osrm"

    def __init__(self, base_url=None, timeout=20):
        self.base_url = (base_url or "https://router.project-osrm.org").rstrip("/")
        self.timeout = timeout

    def _coords(self, points):
        # OSRM takes lng,lat — the opposite order to everything else here,
        # which is the single most common way to end up routing through the
        # Indian Ocean.
        return ";".join(f"{float(p[1])},{float(p[0])}" for p in points)

    def _get(self, url, params):
        import requests

        try:
            response = requests.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise RoutingError("The routing service could not be reached.") from exc
        if response.status_code != 200:
            raise RoutingError(
                f"The routing service refused the request ({response.status_code}).")
        data = response.json()
        if data.get("code") != "Ok":
            raise RoutingError(data.get("message")
                               or "The routing service could not build a route.")
        return data

    def route(self, points, mode="distance"):
        data = self._get(f"{self.base_url}/route/v1/driving/{self._coords(points)}",
                         {"overview": "full", "geometries": "polyline",
                          "steps": "false", "annotations": "false"})
        route = data["routes"][0]
        legs = [Leg(distance_km=round(leg["distance"] / 1000.0, 2),
                    minutes=int(round(leg["duration"] / 60.0)))
                for leg in route.get("legs", [])]
        return RouteResult(legs=legs, order=list(range(len(points))),
                           geometry={"type": "polyline",
                                     "encoded": route.get("geometry")},
                           provider=self.name, basis=self.basis)

    def matrix(self, points, mode="distance"):
        annotation = "duration" if mode == "time" else "distance"
        data = self._get(f"{self.base_url}/table/v1/driving/{self._coords(points)}",
                         {"annotations": annotation})
        raw = data.get("distances" if annotation == "distance" else "durations") or []
        if annotation == "distance":
            return [[round((v or 0) / 1000.0, 3) for v in row] for row in raw]
        return [[int(round((v or 0) / 60.0)) for v in row] for row in raw]

    def trip(self, points, mode="distance", roundtrip=True):
        """OSRM's own travelling-salesman endpoint.

        Asked first when a route needs ordering, because a provider that
        solves it server-side beats anything approximated here. ``source`` is
        pinned to the first point: the day starts at the office, not wherever
        the solver finds convenient.
        """
        data = self._get(f"{self.base_url}/trip/v1/driving/{self._coords(points)}",
                         {"source": "first", "roundtrip": "true" if roundtrip else "false",
                          "destination": "last" if not roundtrip else None,
                          "overview": "full", "geometries": "polyline"})
        trip = data["trips"][0]
        order = [w["waypoint_index"] for w in sorted(data["waypoints"],
                                                     key=lambda w: w["trips_index"])]
        # OSRM reports waypoint_index as the position in the optimised tour;
        # invert it so the caller gets "visit these original points in this
        # order", which is what every screen above wants.
        ordered = [None] * len(order)
        for original, position in enumerate(w["waypoint_index"]
                                            for w in data["waypoints"]):
            ordered[position] = original
        legs = [Leg(distance_km=round(leg["distance"] / 1000.0, 2),
                    minutes=int(round(leg["duration"] / 60.0)))
                for leg in trip.get("legs", [])]
        return RouteResult(legs=legs, order=[i for i in ordered if i is not None],
                           geometry={"type": "polyline", "encoded": trip.get("geometry")},
                           provider=self.name, basis=self.basis)


class OpenRouteServiceProvider(BaseProvider):
    """openrouteservice.org — needs ROUTING_API_KEY; generous free tier."""

    name = "openrouteservice"

    def __init__(self, api_key, base_url=None, timeout=20):
        self.api_key = api_key
        self.base_url = (base_url or "https://api.openrouteservice.org").rstrip("/")
        self.timeout = timeout

    def _post(self, path, payload):
        import requests

        try:
            response = requests.post(
                f"{self.base_url}{path}", json=payload, timeout=self.timeout,
                headers={"Authorization": self.api_key,
                         "Content-Type": "application/json"})
        except requests.RequestException as exc:
            raise RoutingError("The routing service could not be reached.") from exc
        if response.status_code == 401:
            raise RoutingError("The routing service rejected the API key.")
        if response.status_code != 200:
            raise RoutingError(
                f"The routing service refused the request ({response.status_code}).")
        return response.json()

    def route(self, points, mode="distance"):
        data = self._post("/v2/directions/driving-car/geojson",
                          {"coordinates": [[float(p[1]), float(p[0])] for p in points]})
        feature = data["features"][0]
        segments = feature["properties"].get("segments", [])
        legs = [Leg(distance_km=round(s["distance"] / 1000.0, 2),
                    minutes=int(round(s["duration"] / 60.0))) for s in segments]
        return RouteResult(legs=legs, order=list(range(len(points))),
                           geometry={"type": "geojson",
                                     "coordinates": feature["geometry"]["coordinates"]},
                           provider=self.name, basis=self.basis)

    def matrix(self, points, mode="distance"):
        metric = "duration" if mode == "time" else "distance"
        data = self._post("/v2/matrix/driving-car",
                          {"locations": [[float(p[1]), float(p[0])] for p in points],
                           "metrics": [metric], "units": "km"})
        raw = data.get("distances" if metric == "distance" else "durations") or []
        if metric == "distance":
            return [[round(v or 0, 3) for v in row] for row in raw]
        return [[int(round((v or 0) / 60.0)) for v in row] for row in raw]


class GoogleProvider(BaseProvider):
    """Google Directions / Distance Matrix — needs ROUTING_API_KEY.

    The key is used server-side only. It must never reach the browser: a key
    in page source is a key on somebody else's bill.
    """

    name = "google"

    def __init__(self, api_key, base_url=None, timeout=20):
        self.api_key = api_key
        self.base_url = (base_url or "https://maps.googleapis.com/maps/api").rstrip("/")
        self.timeout = timeout

    def _get(self, path, params):
        import requests

        params = {**params, "key": self.api_key}
        try:
            response = requests.get(f"{self.base_url}{path}", params=params,
                                    timeout=self.timeout)
        except requests.RequestException as exc:
            raise RoutingError("The routing service could not be reached.") from exc
        data = response.json() if response.content else {}
        status = data.get("status")
        if status == "REQUEST_DENIED":
            raise RoutingError("The routing service rejected the API key.")
        if status not in ("OK", "ZERO_RESULTS"):
            raise RoutingError(data.get("error_message")
                               or "The routing service could not build a route.")
        return data

    @staticmethod
    def _point(p):
        return f"{float(p[0])},{float(p[1])}"

    def route(self, points, mode="distance"):
        waypoints = points[1:-1]
        params = {"origin": self._point(points[0]),
                  "destination": self._point(points[-1])}
        if waypoints:
            params["waypoints"] = "|".join(self._point(p) for p in waypoints)
        data = self._get("/directions/json", params)
        routes = data.get("routes") or []
        if not routes:
            raise RoutingError("No road route exists between these points.")
        legs = [Leg(distance_km=round(leg["distance"]["value"] / 1000.0, 2),
                    minutes=int(round(leg["duration"]["value"] / 60.0)))
                for leg in routes[0].get("legs", [])]
        return RouteResult(legs=legs, order=list(range(len(points))),
                           geometry={"type": "polyline",
                                     "encoded": routes[0]["overview_polyline"]["points"]},
                           provider=self.name, basis=self.basis)

    def matrix(self, points, mode="distance"):
        joined = "|".join(self._point(p) for p in points)
        data = self._get("/distancematrix/json",
                         {"origins": joined, "destinations": joined})
        out = []
        for row in data.get("rows", []):
            cells = []
            for element in row.get("elements", []):
                if element.get("status") != "OK":
                    cells.append(0)
                elif mode == "time":
                    cells.append(int(round(element["duration"]["value"] / 60.0)))
                else:
                    cells.append(round(element["distance"]["value"] / 1000.0, 3))
            out.append(cells)
        return out


PROVIDERS = {
    "osrm": OSRMProvider,
    "openrouteservice": OpenRouteServiceProvider,
    "google": GoogleProvider,
    "straight": StraightLineProvider,
}


def get_provider(name=None):
    """The configured provider, built from settings.

    An unknown name is a configuration mistake worth failing loudly on rather
    than quietly routing by ruler for a year.
    """
    conf = getattr(settings, "ROUTING", {}) or {}
    name = (name or conf.get("PROVIDER") or "osrm").strip().lower()
    if name not in PROVIDERS:
        raise RoutingError(f"Unknown routing provider {name!r}. "
                           f"Set ROUTING_PROVIDER to one of: "
                           f"{', '.join(sorted(PROVIDERS))}.")
    timeout = int(conf.get("TIMEOUT") or 20)
    key = conf.get("API_KEY") or ""
    base = conf.get("BASE_URL") or None
    if name == "straight":
        return StraightLineProvider()
    if name == "osrm":
        return OSRMProvider(base_url=base, timeout=timeout)
    if not key:
        raise RoutingError(f"{name} needs an API key. Set ROUTING_API_KEY.")
    return PROVIDERS[name](api_key=key, base_url=base, timeout=timeout)


class RouteService:
    """The one way anything in this ERP asks about roads.

    ``calculate`` is the whole interface: give it an ordered list of points
    and it measures that round; ask it to optimise and it also decides the
    order. Callers never see a provider, a URL or a key.
    """

    def __init__(self, provider=None, allow_fallback=None):
        self._provider = provider
        conf = getattr(settings, "ROUTING", {}) or {}
        self.allow_fallback = (conf.get("ALLOW_STRAIGHT_LINE_FALLBACK", True)
                               if allow_fallback is None else allow_fallback)

    @property
    def provider(self):
        if self._provider is None:
            self._provider = get_provider()
        return self._provider

    # ---- caching ------------------------------------------------------------

    @staticmethod
    def _cache_key(kind, points, mode, extra=""):
        pins = "|".join(f"{float(p[0]):.5f},{float(p[1]):.5f}" for p in points)
        import hashlib

        digest = hashlib.sha1(f"{kind}:{mode}:{extra}:{pins}".encode()).hexdigest()
        return f"routing:{digest}"

    # ---- the interface ------------------------------------------------------

    def calculate(self, points, mode="distance", optimise=False, roundtrip=True):
        """Measure a round, and order it if asked.

        ``points`` is [(lat, lng), ...] with the start first. Returns a
        :class:`RouteResult` whose ``basis`` says whether the kilometres came
        off a road network or a ruler.
        """
        points = [(float(p[0]), float(p[1])) for p in points]
        if len(points) < 2:
            raise RoutingError("A route needs at least a start and one stop.")
        limit = int((getattr(settings, "ROUTING", {}) or {}).get("MAX_WAYPOINTS") or 25)
        if len(points) > limit:
            raise RoutingError(
                f"A route can take {limit} stops at a time; this one has "
                f"{len(points)}. Plan it as two rounds.")

        key = self._cache_key("route", points, mode, f"{optimise}:{roundtrip}")
        hit = cache.get(key)
        if hit is not None:
            return hit

        try:
            result = (self._optimised(points, mode, roundtrip) if optimise
                      else self.provider.route(points, mode))
        except RoutingError:
            if not self.allow_fallback:
                raise
            # Estimated, and labelled as such all the way up to the screen.
            logger.warning("routing provider failed; falling back to straight line",
                           exc_info=True)
            fallback = StraightLineProvider()
            result = (self._optimised(points, mode, roundtrip, provider=fallback)
                      if optimise else fallback.route(points, mode))
        cache.set(key, result, CACHE_SECONDS)
        return result

    # ---- ordering -----------------------------------------------------------

    def _optimised(self, points, mode, roundtrip, provider=None):
        """Decide the visiting order, then measure the round it implies.

        The provider's own solver is asked first — OSRM has one and it beats
        anything approximated here. Otherwise the order is worked out over the
        provider's distance *matrix*, which is still road distance: the
        approximation is in the ordering, never in the kilometres.
        """
        provider = provider or self.provider
        if hasattr(provider, "trip"):
            try:
                result = provider.trip(points, mode=mode, roundtrip=roundtrip)
                if result.order:
                    return result
            except RoutingError:
                logger.info("provider trip endpoint unavailable; ordering locally")

        matrix = provider.matrix(points, mode)
        order = _nearest_neighbour(matrix)
        order = _two_opt(order, matrix)
        ordered_points = [points[i] for i in order]
        if roundtrip:
            ordered_points = ordered_points + [points[0]]
        result = provider.route(ordered_points, mode)
        result.order = order + ([0] if roundtrip else [])
        return result


def _nearest_neighbour(matrix):
    """A first order: always go to the closest place not yet visited.

    Starts at 0 and stays there — the first point is the office, and a tour
    that begins wherever the arithmetic prefers is not a working day.
    """
    n = len(matrix)
    unvisited = set(range(1, n))
    order = [0]
    current = 0
    while unvisited:
        nxt = min(unvisited, key=lambda j: matrix[current][j])
        order.append(nxt)
        unvisited.discard(nxt)
        current = nxt
    return order


def _two_opt(order, matrix, rounds=60):
    """Untangle the nearest-neighbour order by reversing crossing segments.

    Nearest-neighbour reliably paints itself into a corner and then drives
    back across the district to collect what it skipped. Two-opt fixes exactly
    that, cheaply, and the loop is bounded because a planner must answer while
    somebody is waiting for it.
    """
    n = len(order)
    if n < 4:
        return order
    best = order[:]
    improved = True
    guard = 0
    while improved and guard < rounds:
        improved = False
        guard += 1
        for i in range(1, n - 2):
            for j in range(i + 1, n - 1):
                a, b = best[i - 1], best[i]
                c, d = best[j], best[j + 1]
                if matrix[a][c] + matrix[b][d] < matrix[a][b] + matrix[c][d]:
                    best[i:j + 1] = reversed(best[i:j + 1])
                    improved = True
    return best
