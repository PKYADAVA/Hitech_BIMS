"""Farm Map & Route Planner: pins, roads and rounds.

Nothing here touches the network. The routing providers are exercised through
:class:`StraightLineProvider`, which is deterministic, and what is being tested
is the behaviour around them — which farms may be routed, what order they come
out in, what happens when the provider cannot be reached, and who is allowed to
see whose farms. The one thing a test cannot assert is that a provider's
kilometres are right; that is the provider's job, and the reason the module
records *which* provider answered.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from broiler.models import (Branch, BroilerFarm, Farmer, FarmLocationCapture,
                            FarmRoute, Region, Supervisor)
from broiler.services.route_planner import (farm_point, order_by_priority,
                                            plan_route, save_route, split_by_gps)
from broiler.services.routing import (RouteService, RoutingError,
                                      StraightLineProvider, haversine_km,
                                      _nearest_neighbour, _two_opt)


class FarmPointTests(TestCase):
    """Which farms have a usable pin. Nothing is ever invented."""

    def setUp(self):
        self.region = Region.objects.create(description="East")
        self.branch = Branch.objects.create(branch_name="Akbarpur",
                                            region=self.region, prefix="AKB")
        self.sup = Supervisor.objects.create(branch=self.branch, name="A. Verma")
        self.farmer = Farmer.objects.create(farmer_name="S. Yadav")

    def farm(self, name, lat=None, lng=None):
        return BroilerFarm.objects.create(
            branch=self.branch, supervisor=self.sup, farmer=self.farmer,
            region=self.region, line="L1", farm_name=name, farm_capacity=5000,
            farm_latitude=lat, farm_longitude=lng)

    def test_a_farm_with_a_pin_is_routable(self):
        self.assertEqual(farm_point(self.farm("A", 26.43, 82.53)), (26.43, 82.53))

    def test_a_farm_with_no_pin_is_not(self):
        self.assertIsNone(farm_point(self.farm("B")))

    def test_null_island_is_not_a_farm(self):
        """(0, 0) is in the Atlantic. It is what an empty form saves."""
        self.assertIsNone(farm_point(self.farm("C", 0, 0)))

    def test_an_impossible_coordinate_is_refused(self):
        self.assertIsNone(farm_point(self.farm("D", 200, 300)))

    def test_the_split_keeps_the_unpinned_farms_rather_than_dropping_them(self):
        """A farm with no GPS is somebody's job to go and capture, not a row to
        discard silently."""
        good, bad = self.farm("Good", 26.4, 82.5), self.farm("Bad")
        routable, missing = split_by_gps([good, bad])
        self.assertEqual([f.farm_name for f in routable], ["Good"])
        self.assertEqual([f.farm_name for f in missing], ["Bad"])


class StraightLineIsNeverPassedOffAsRoadTests(TestCase):
    """The rule the whole module rests on."""

    def test_a_ruler_is_labelled_a_ruler(self):
        result = StraightLineProvider().route([(26.43, 82.53), (26.47, 82.61)])
        self.assertEqual(result.basis, "straight")

    def test_the_road_allowance_makes_it_longer_than_the_crow_flies(self):
        a, b = (26.43, 82.53), (26.47, 82.61)
        result = StraightLineProvider().route([a, b])
        self.assertGreater(result.distance_km, haversine_km(a, b))

    @override_settings(ROUTING={"PROVIDER": "straight"})
    def test_a_plan_built_on_it_says_it_is_an_estimate(self):
        """The screen keys its warning off this flag; without it the figures
        would read as measurements."""
        service = RouteService(provider=StraightLineProvider())
        result = service.calculate([(26.43, 82.53), (26.47, 82.61)])
        self.assertEqual(result.basis, "straight")

    @override_settings(ROUTING={"PROVIDER": "nonsense"})
    def test_a_misconfigured_provider_fails_loudly(self):
        """Quietly routing by ruler for a year because of a typo in an
        environment variable is the failure this prevents."""
        from broiler.services.routing import get_provider

        with self.assertRaises(RoutingError):
            get_provider()

    @override_settings(ROUTING={"PROVIDER": "google", "API_KEY": ""})
    def test_a_provider_with_no_key_says_so(self):
        from broiler.services.routing import get_provider

        with self.assertRaises(RoutingError) as ctx:
            get_provider()
        self.assertIn("API key", str(ctx.exception))


class OrderingTests(TestCase):
    """The optimiser, on a matrix with a known answer."""

    def test_it_starts_where_the_day_starts(self):
        """A tour that begins wherever the arithmetic prefers is not a working
        day: index 0 is the office."""
        matrix = [[0, 9, 1], [9, 0, 4], [1, 4, 0]]
        self.assertEqual(_nearest_neighbour(matrix)[0], 0)

    def test_nearest_neighbour_takes_the_closest_next(self):
        matrix = [[0, 9, 1], [9, 0, 4], [1, 4, 0]]
        self.assertEqual(_nearest_neighbour(matrix), [0, 2, 1])

    def test_two_opt_untangles_a_crossing(self):
        """Nearest-neighbour paints itself into a corner and drives back across
        the district; this is the pass that fixes it."""
        # A square: 0-1-2-3 around the edge is short, 0-2-1-3 crosses.
        matrix = [
            [0, 1, 2, 1],
            [1, 0, 1, 2],
            [2, 1, 0, 1],
            [1, 2, 1, 0],
        ]
        tangled = [0, 2, 1, 3]
        better = _two_opt(tangled, matrix)
        self.assertLessEqual(
            sum(matrix[better[i]][better[i + 1]] for i in range(len(better) - 1)),
            sum(matrix[tangled[i]][tangled[i + 1]] for i in range(len(tangled) - 1)))


class PriorityRouteTests(TestCase):
    """Priority is a trade against distance, not an override of it."""

    def setUp(self):
        self.region = Region.objects.create(description="East")
        self.branch = Branch.objects.create(branch_name="Akbarpur",
                                            region=self.region, prefix="AKB")
        self.sup = Supervisor.objects.create(branch=self.branch, name="A. Verma")
        self.farmer = Farmer.objects.create(farmer_name="S. Yadav")

    def farm(self, name, priority="normal"):
        return BroilerFarm.objects.create(
            branch=self.branch, supervisor=self.sup, farmer=self.farmer,
            region=self.region, line="L1", farm_name=name, farm_capacity=5000,
            farm_latitude=26.4, farm_longitude=82.5, visit_priority=priority)

    def test_a_critical_farm_is_pulled_towards_the_front(self):
        farms = [self.farm("A"), self.farm("B"), self.farm("C", "critical")]
        # Even ring: every promotion is affordable.
        matrix = [[0, 1, 1, 1], [1, 0, 1, 1], [1, 1, 0, 1], [1, 1, 1, 0]]
        order, notes = order_by_priority(farms, [0, 1, 2, 3], matrix)
        self.assertEqual(order[1], 3)                  # farm C, first call
        self.assertTrue(any("Critical" in n or "critical" in n for n in notes))

    def test_a_normal_farm_is_never_promoted(self):
        farms = [self.farm("A"), self.farm("B")]
        matrix = [[0, 1, 5], [1, 0, 1], [5, 1, 0]]
        order, notes = order_by_priority(farms, [0, 1, 2], matrix)
        self.assertEqual(order, [0, 1, 2])
        self.assertEqual(notes, [])

    def test_a_promotion_that_would_cost_too_much_is_refused_and_explained(self):
        """Section 14: a priority route must not randomly reorder the day. It
        may pay for urgency, up to a ceiling, and must say what it paid."""
        farms = [self.farm("A"), self.farm("B"), self.farm("C", "critical")]
        # C is very far from the office; promoting it doubles the round.
        matrix = [[0, 1, 2, 50], [1, 0, 1, 50], [2, 1, 0, 50], [50, 50, 50, 0]]
        order, notes = order_by_priority(farms, [0, 1, 2, 3], matrix)
        self.assertEqual(order, [0, 1, 2, 3])
        self.assertTrue(any("beyond" in n for n in notes))

    def test_the_office_is_never_reordered(self):
        farms = [self.farm("A", "critical")]
        matrix = [[0, 1], [1, 0]]
        order, _ = order_by_priority(farms, [0, 1], matrix)
        self.assertEqual(order[0], 0)


class PlanShapeTests(TestCase):
    """What a calculated round looks like to the screens above."""

    def setUp(self):
        self.region = Region.objects.create(description="East")
        self.branch = Branch.objects.create(branch_name="Akbarpur",
                                            region=self.region, prefix="AKB",
                                            latitude=26.43, longitude=82.53)
        self.sup = Supervisor.objects.create(branch=self.branch, name="A. Verma")
        self.farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.service = RouteService(provider=StraightLineProvider())

    def farm(self, name, lat, lng, priority="normal"):
        return BroilerFarm.objects.create(
            branch=self.branch, supervisor=self.sup, farmer=self.farmer,
            region=self.region, line="L1", farm_name=name, farm_capacity=5000,
            farm_latitude=lat, farm_longitude=lng, visit_priority=priority)

    def plan(self, **kw):
        farms = kw.pop("farms", None) or [self.farm("A", 26.47, 82.61),
                                          self.farm("B", 26.39, 82.48)]
        return plan_route(start=("Head Office", 26.43, 82.53), farms=farms,
                          service=self.service, **kw)

    def test_a_round_trip_comes_home(self):
        """The drive home is a leg the provider reports without a waypoint;
        leaving it out had the panel showing half the distance it quoted."""
        plan = self.plan(roundtrip=True)
        self.assertEqual(plan["stops"][0]["kind"], "start")
        self.assertEqual(plan["stops"][-1]["kind"], "end")

    def test_the_cumulative_column_closes_on_the_total(self):
        plan = self.plan(roundtrip=True)
        self.assertAlmostEqual(plan["stops"][-1]["cumulative_distance_km"],
                               plan["distance_km"], places=1)

    def test_every_farm_selected_appears_once(self):
        plan = self.plan(roundtrip=True)
        farm_stops = [s for s in plan["stops"] if s["kind"] == "farm"]
        self.assertEqual(len(farm_stops), 2)
        self.assertEqual(len({s["farm_id"] for s in farm_stops}), 2)

    def test_it_reports_which_provider_answered_and_on_what_basis(self):
        """A figure nobody can trace to a source is not evidence."""
        plan = self.plan()
        self.assertEqual(plan["provider"], "straight")
        self.assertTrue(plan["estimated"])

    def test_planning_writes_nothing(self):
        """A planner that saved on every filter change would fill the table
        with rounds nobody drove."""
        self.plan()
        self.assertEqual(FarmRoute.objects.count(), 0)

    def test_saving_writes_the_stops_in_order(self):
        plan = self.plan()
        route = save_route(plan, date=timezone.localdate(), branch=self.branch,
                           supervisor=self.sup, mode="distance",
                           start=("Head Office", 26.43, 82.53))
        self.assertTrue(route.route_no.startswith("RT-"))
        stops = list(route.stops.values_list("sequence", "kind"))
        self.assertEqual([s[0] for s in stops], sorted(s[0] for s in stops))
        self.assertEqual(stops[0][1], "start")
        self.assertEqual(route.farm_count, 2)

    def test_a_saved_estimate_records_that_it_was_one(self):
        route = save_route(self.plan(), date=timezone.localdate(),
                           start=("Head Office", 26.43, 82.53))
        self.assertEqual(route.distance_basis, FarmRoute.BASIS_STRAIGHT)


class LocationCaptureFeedsTheMapTests(TestCase):
    """Section 16: one place a coordinate comes from."""

    def setUp(self):
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region,
                                       prefix="AKB")
        sup = Supervisor.objects.create(branch=branch, name="A. Verma")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm_row = BroilerFarm.objects.create(
            branch=branch, supervisor=sup, farmer=farmer, region=region,
            line="L1", farm_name="Yadav Farm", farm_capacity=5000)

    def capture(self, lat, lng, accuracy=None, days_ago=0):
        capture = FarmLocationCapture.objects.create(
            farm=self.farm_row, date=timezone.localdate(), latitude=lat,
            longitude=lng, gps_accuracy=accuracy)
        capture.sync_farm()
        self.farm_row.refresh_from_db()
        return capture

    def test_a_capture_puts_the_farm_on_the_map(self):
        self.assertIsNone(farm_point(self.farm_row))
        self.capture(26.44, 82.55)
        self.assertEqual(farm_point(self.farm_row), (26.44, 82.55))

    def test_the_accuracy_and_the_date_travel_with_the_pin(self):
        """A fix good to two kilometres routes somebody to the wrong village,
        so the planner shows how good the reading was."""
        self.capture(26.44, 82.55, accuracy=8.5)
        self.assertEqual(self.farm_row.gps_accuracy, 8.5)
        self.assertEqual(self.farm_row.location_captured_at, timezone.localdate())


class PermissionTests(TestCase):
    """A supervisor sees their own farms. The filter bar is a convenience;
    the scoping is the rule, and it is enforced on the endpoint."""

    def setUp(self):
        self.region = Region.objects.create(description="East")
        self.mine = Branch.objects.create(branch_name="Akbarpur",
                                          region=self.region, prefix="AKB")
        self.theirs = Branch.objects.create(branch_name="Bahraich",
                                            region=self.region, prefix="BHR")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        for branch, name in ((self.mine, "Mine"), (self.theirs, "Theirs")):
            sup = Supervisor.objects.create(branch=branch, name=f"{name} sup")
            BroilerFarm.objects.create(
                branch=branch, supervisor=sup, farmer=farmer, region=self.region,
                line="L1", farm_name=f"{name} Farm", farm_capacity=5000,
                farm_latitude=26.4, farm_longitude=82.5)

    def scoped_client(self):
        from user.models import GroupAccessProfile, GroupTabPermission

        User = get_user_model()
        user = User.objects.create_user("routeclerk", "r@x.com", "Str0ngPass!")
        group = Group.objects.create(name="Akbarpur only")
        user.groups.add(group)
        GroupTabPermission.objects.create(group=group, tab_code="farm_map_planner",
                                          can_view=True)
        access = GroupAccessProfile.objects.create(group=group, all_branches=False)
        access.branches.add(self.mine)
        self.client.force_login(user)
        return user

    def test_an_unscoped_user_sees_every_farm(self):
        User = get_user_model()
        self.client.force_login(
            User.objects.create_superuser("routeadmin", "a@x.com", "Str0ngPass!"))
        data = self.client.get(reverse("farm_map_data")).json()
        self.assertEqual(data["counts"]["total"], 2)

    def test_a_scoped_user_sees_only_their_branch(self):
        self.scoped_client()
        data = self.client.get(reverse("farm_map_data")).json()
        names = [f["name"] for f in data["farms"]]
        self.assertEqual(names, ["Mine Farm"])

    def test_another_branch_s_farm_cannot_be_routed_by_id(self):
        """Posting an id straight at the endpoint must not reach past the
        scope — the filter bar is not the security boundary."""
        self.scoped_client()
        theirs = BroilerFarm.objects.get(farm_name="Theirs Farm")
        response = self.client.post(
            reverse("farm_route_calculate"),
            data={"farm_ids": [theirs.id]}, content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_the_page_needs_a_login(self):
        response = self.client.get(reverse("farm_map_planner"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)


class ErrorMessageTests(TestCase):
    """Section 33: every failure says what to do about it."""

    def setUp(self):
        User = get_user_model()
        self.client.force_login(
            User.objects.create_superuser("routeerr", "e@x.com", "Str0ngPass!"))
        region = Region.objects.create(description="East")
        self.branch = Branch.objects.create(branch_name="Akbarpur", region=region,
                                            prefix="AKB")
        sup = Supervisor.objects.create(branch=self.branch, name="A. Verma")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.blind = BroilerFarm.objects.create(
            branch=self.branch, supervisor=sup, farmer=farmer, region=region,
            line="L1", farm_name="No GPS Farm", farm_capacity=5000)

    def post(self, payload):
        return self.client.post(reverse("farm_route_calculate"), data=payload,
                                content_type="application/json")

    def test_no_farms_selected(self):
        response = self.post({"farm_ids": []})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Select the farms", response.json()["error"])

    def test_a_farm_with_no_gps_is_named_and_refused(self):
        """It must not be quietly dropped, and it must not be given a made-up
        coordinate — the sentence tells the user exactly what to go and do."""
        response = self.post({"farm_ids": [self.blind.id]})
        self.assertEqual(response.status_code, 422)
        body = response.json()
        self.assertIn("No GPS Farm", body["error"])
        self.assertIn("Capture their farm locations", body["error"])
        self.assertEqual(body["gps_missing"][0]["name"], "No GPS Farm")

    def test_a_route_with_nowhere_to_start_says_so(self):
        # Updated through the queryset: BroilerFarm.region is a CharField that
        # the fixtures hand a Region object to, which insert coerces and a
        # later save() refuses.
        BroilerFarm.objects.filter(pk=self.blind.pk).update(
            farm_latitude=26.4, farm_longitude=82.5)
        self.blind.refresh_from_db()
        response = self.post({"farm_ids": [self.blind.id]})
        self.assertEqual(response.status_code, 400)
        self.assertIn("no starting point", response.json()["error"])

    @override_settings(ROUTING={"PROVIDER": "straight", "MAX_WAYPOINTS": 2})
    def test_too_many_stops_is_a_sentence_not_a_stack_trace(self):
        service = RouteService(provider=StraightLineProvider())
        with self.assertRaises(RoutingError) as ctx:
            service.calculate([(26.4, 82.5), (26.5, 82.6), (26.6, 82.7)])
        self.assertIn("two rounds", str(ctx.exception).replace("2 rounds", "two rounds"))
