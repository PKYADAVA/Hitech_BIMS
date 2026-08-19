"""The four gaps closed after the module was first built.

Each is a promise the interface was making and the code was not keeping: a
priority nobody could set, a route mode that silently duplicated another, two
missing actions on Route History, and a payload that queried per stop.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from broiler.models import (Branch, BroilerFarm, Farmer, FarmRoute, FarmRouteStop,
                            Region, Supervisor)
from broiler.services.route_planner import overdue_weights, plan_route
from broiler.services.route_trip import check_in, create_trip
from broiler.services.routing import RouteService, StraightLineProvider
from hr.models import Employee


def fixture(case, farm_count=3):
    case.today = timezone.localdate()
    case.region = Region.objects.create(description="East")
    case.branch = Branch.objects.create(branch_name="Akbarpur", region=case.region,
                                        prefix="AKB", latitude=26.43, longitude=82.53)
    case.employee = Employee.objects.create(full_name="A. Verma")
    case.sup = Supervisor.objects.create(branch=case.branch, name="A. Verma",
                                         employee=case.employee)
    farmer = Farmer.objects.create(farmer_name="S. Yadav")
    case.farms = [
        BroilerFarm.objects.create(
            branch=case.branch, supervisor=case.sup, farmer=farmer,
            region=case.region, line="L1", farm_name=f"Farm {i}",
            farm_capacity=5000, farm_latitude=26.4 + i * 0.02,
            farm_longitude=82.5 + i * 0.02)
        for i in range(1, farm_count + 1)
    ]
    return case


class VisitPriorityCanBeSetTests(TestCase):
    """The field existed, the algorithm used it, and nothing could set it."""

    def setUp(self):
        fixture(self, 1)
        User = get_user_model()
        self.client.force_login(
            User.objects.create_superuser("prioadmin", "p@x.com", "Str0ngPass!"))

    def test_the_farm_master_form_offers_the_three_priorities(self):
        html = self.client.get(reverse("branch_farm")).content.decode()
        self.assertIn('id="visit_priority"', html)
        for label in ("Normal", "High", "Critical"):
            self.assertIn(f">{label}</option>", html)

    def test_the_farm_api_returns_the_priority_it_holds(self):
        farm = self.farms[0]
        BroilerFarm.objects.filter(pk=farm.pk).update(visit_priority="critical")
        body = self.client.get(reverse("broiler_farm_detail", args=[farm.id])).json()
        self.assertEqual(body["visit_priority"], "critical")


class SupervisorDailyRouteIsItsOwnThingTests(TestCase):
    """It used to fall through to Shortest Distance — a menu option that
    silently duplicated another."""

    def setUp(self):
        fixture(self, 3)
        self.service = RouteService(provider=StraightLineProvider())

    def visit(self, farm, days_ago):
        """A recorded call at a farm, that many days back."""
        from datetime import timedelta

        route = FarmRoute.objects.create(
            date=self.today - timedelta(days=days_ago), branch=self.branch,
            supervisor=self.sup, start_label="HO",
            start_latitude=26.43, start_longitude=82.53)
        FarmRouteStop.objects.create(route=route, sequence=1, kind="start", label="HO")
        FarmRouteStop.objects.create(route=route, sequence=2, kind="farm", farm=farm,
                                     label=farm.farm_name)
        create_trip(route)
        when = timezone.now() - timedelta(days=days_ago)
        check_in(route, farm.id, when=when)

    def test_a_farm_nobody_has_visited_is_the_most_overdue_there_is(self):
        """Never visited is the most overdue, not the least — it is exactly the
        farm nobody has been to."""
        weights, last = overdue_weights(self.farms)
        self.assertEqual(weights[self.farms[0].id], 0.55)   # critical weight
        self.assertEqual(last, {})

    def test_a_farm_seen_yesterday_is_not_urgent(self):
        self.visit(self.farms[0], days_ago=1)
        weights, _ = overdue_weights(self.farms)
        self.assertEqual(weights[self.farms[0].id], 0.0)

    def test_a_fortnight_is_overdue_and_a_month_is_badly_overdue(self):
        self.visit(self.farms[0], days_ago=14)
        self.visit(self.farms[1], days_ago=30)
        weights, _ = overdue_weights(self.farms)
        self.assertEqual(weights[self.farms[0].id], 0.30)   # high
        self.assertEqual(weights[self.farms[1].id], 0.55)   # critical

    def test_the_mode_explains_itself_in_terms_of_visits_not_flags(self):
        """A priority route says "critical priority"; this one says how long it
        has been, because that is what it actually ordered by."""
        # Different days: the register allows one trip per person per day.
        self.visit(self.farms[0], days_ago=1)
        self.visit(self.farms[1], days_ago=2)
        plan = plan_route(start=("Head Office", 26.43, 82.53), farms=self.farms,
                          mode="supervisor", service=self.service)
        notes = " ".join(plan["priority_notes"])
        self.assertTrue("never visited" in notes or "days ago" in notes or not notes)

    def test_it_does_not_read_the_manual_priority_flag(self):
        """The two modes are different questions: one asks what somebody
        decided, the other what the register shows."""
        BroilerFarm.objects.filter(pk=self.farms[2].pk).update(visit_priority="critical")
        self.visit(self.farms[2], days_ago=1)      # seen yesterday, so not overdue
        weights, _ = overdue_weights(self.farms)
        self.assertEqual(weights[self.farms[2].id], 0.0)


class DuplicateAndRecalculateTests(TestCase):
    def setUp(self):
        fixture(self, 2)
        User = get_user_model()
        self.client.force_login(
            User.objects.create_superuser("histadmin", "h@x.com", "Str0ngPass!"))
        self.route = FarmRoute.objects.create(
            date=self.today, branch=self.branch, supervisor=self.sup,
            start_label="Head Office", start_latitude=26.43, start_longitude=82.53,
            planned_distance_km=Decimal("70"), planned_minutes=100,
            status=FarmRoute.STATUS_PLANNED)
        FarmRouteStop.objects.create(route=self.route, sequence=1, kind="start",
                                     label="Head Office", latitude=26.43,
                                     longitude=82.53)
        for i, farm in enumerate(self.farms, start=2):
            FarmRouteStop.objects.create(
                route=self.route, sequence=i, kind="farm", farm=farm,
                label=farm.farm_name, latitude=farm.farm_latitude,
                longitude=farm.farm_longitude, leg_distance_km=Decimal("35"))

    def post(self, name, route=None):
        return self.client.post(reverse(name, args=[(route or self.route).id]),
                                data={}, content_type="application/json")

    # ---- duplicate ---------------------------------------------------------

    def test_duplicating_makes_a_new_unstarted_round(self):
        response = self.post("route_duplicate")
        self.assertEqual(response.status_code, 200)
        copy = FarmRoute.objects.get(id=response.json()["id"])
        self.assertNotEqual(copy.id, self.route.id)
        self.assertIsNone(copy.trip_id)
        self.assertEqual(copy.status, FarmRoute.STATUS_PLANNED)
        self.assertEqual(copy.stops.count(), self.route.stops.count())

    def test_the_original_keeps_its_own_journey(self):
        """Copying must not disturb the round whose trip is already attached."""
        create_trip(self.route)
        self.post("route_duplicate")
        self.route.refresh_from_db()
        self.assertIsNotNone(self.route.trip_id)

    def test_the_copy_carries_the_measured_distance_rather_than_re_measuring(self):
        """The roads have not moved; spending a provider call to be told the
        same thing is what Recalculate is for."""
        copy = FarmRoute.objects.get(id=self.post("route_duplicate").json()["id"])
        self.assertEqual(copy.planned_distance_km, self.route.planned_distance_km)

    # ---- recalculate -------------------------------------------------------

    def test_recalculating_a_driven_round_is_refused(self):
        """Its distances are what its trip was measured against; changing them
        would rewrite a deviation report after the fact."""
        create_trip(self.route)
        response = self.post("route_recalculate")
        self.assertEqual(response.status_code, 400)
        self.assertIn("already been driven", response.json()["error"])

    def test_recalculating_an_unstarted_round_re_measures_it(self):
        from unittest.mock import patch

        with patch("broiler.services.route_planner.RouteService") as service:
            service.return_value = RouteService(provider=StraightLineProvider())
            response = self.post("route_recalculate")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["was_km"], 70.0)
        self.route.refresh_from_db()
        self.assertEqual(float(self.route.planned_distance_km), body["distance_km"])

    def test_a_farm_that_has_lost_its_pin_stops_the_recalculation(self):
        BroilerFarm.objects.filter(pk=self.farms[0].pk).update(
            farm_latitude=None, farm_longitude=None)
        response = self.post("route_recalculate")
        self.assertEqual(response.status_code, 422)
        self.assertIn("no longer have GPS", response.json()["error"])

    def test_another_branchs_route_cannot_be_touched(self):
        other = Branch.objects.create(branch_name="Bahraich", region=self.region,
                                      prefix="BHR")
        theirs = FarmRoute.objects.create(date=self.today, branch=other,
                                          start_label="X")
        from django.contrib.auth.models import Group
        from user.models import GroupAccessProfile, GroupTabPermission

        User = get_user_model()
        clerk = User.objects.create_user("histclerk", "c@x.com", "Str0ngPass!")
        group = Group.objects.create(name="Akbarpur history")
        clerk.groups.add(group)
        GroupTabPermission.objects.create(group=group, tab_code="route_history",
                                          can_view=True)
        access = GroupAccessProfile.objects.create(group=group, all_branches=False)
        access.branches.add(self.branch)
        self.client.force_login(clerk)
        self.assertEqual(self.post("route_duplicate", theirs).status_code, 404)
        self.assertEqual(self.post("route_recalculate", theirs).status_code, 404)


class MobilePayloadQueryCountTests(TestCase):
    """The phone polls this; it must not cost a query per farm."""

    def setUp(self):
        fixture(self, 4)
        User = get_user_model()
        self.user = User.objects.create_user("qsup", "q@x.com", "Str0ngPass!")
        self.employee.user = self.user
        self.employee.save()
        self.route = FarmRoute.objects.create(
            date=self.today, branch=self.branch, supervisor=self.sup,
            start_label="Head Office", planned_distance_km=Decimal("90"),
            planned_minutes=140)
        FarmRouteStop.objects.create(route=self.route, sequence=1, kind="start",
                                     label="Head Office")
        for i, farm in enumerate(self.farms, start=2):
            FarmRouteStop.objects.create(route=self.route, sequence=i, kind="farm",
                                         farm=farm, label=farm.farm_name)
        create_trip(self.route)

    def test_the_payload_does_not_grow_a_query_per_stop(self):
        """It used to ask, once per farm, whether that farm had been checked out
        of — a dozen extra queries on every refresh of every supervisor's
        screen.

        The invariant is that the cost does not depend on how many farms are on
        the round, which is what this measures: the same round with twice the
        stops must take the same number of queries.
        """
        from django.db import connection, reset_queries
        from django.test.utils import CaptureQueriesContext

        from broiler.api_route import _route_payload

        def cost():
            route = FarmRoute.objects.select_related("trip").prefetch_related(
                "stops__farm").get(pk=self.route.pk)
            with CaptureQueriesContext(connection) as ctx:
                _route_payload(route)
            return len(ctx)

        small = cost()
        # Four more farms on the same round.
        farmer = Farmer.objects.first()
        for i in range(5, 9):
            farm = BroilerFarm.objects.create(
                branch=self.branch, supervisor=self.sup, farmer=farmer,
                region=self.region, line="L1", farm_name=f"Farm {i}",
                farm_capacity=5000, farm_latitude=26.4, farm_longitude=82.5)
            FarmRouteStop.objects.create(route=self.route, sequence=i + 1,
                                         kind="farm", farm=farm,
                                         label=farm.farm_name)
        self.assertEqual(cost(), small)

    def test_the_states_are_still_right(self):
        from broiler.api_route import _route_payload
        from broiler.services.route_trip import check_out

        check_in(self.route, self.farms[0].id)
        check_in(self.route, self.farms[1].id)
        check_out(self.route, self.farms[1].id)
        payload = _route_payload(FarmRoute.objects.get(pk=self.route.pk))
        states = {s["label"]: s["state"] for s in payload["stops"] if s["kind"] == "farm"}
        self.assertEqual(states["Farm 1"], "here")
        self.assertEqual(states["Farm 2"], "done")
        self.assertEqual(states["Farm 3"], "pending")
