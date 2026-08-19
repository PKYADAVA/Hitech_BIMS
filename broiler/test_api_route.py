"""The supervisor's own round, over the mobile API.

What matters here is not the arithmetic — ``route_trip`` owns that and has its
own tests — but who the caller is allowed to be. A supervisor gets their own
day and nobody else's, and the endpoints must not become a way to read another
branch's rounds by guessing an id.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from broiler.models import (Branch, BroilerFarm, Farmer, FarmRoute, FarmRouteStop,
                            Region, Supervisor)
from hr.models import Employee


class MyRouteTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.region = Region.objects.create(description="East")
        self.branch = Branch.objects.create(branch_name="Akbarpur", region=self.region,
                                            prefix="AKB")
        User = get_user_model()

        # A supervisor, as the ERP links one: Supervisor -> Employee -> User.
        self.user = User.objects.create_user("fieldsup", "f@x.com", "Str0ngPass!")
        self.employee = Employee.objects.create(full_name="A. Verma", user=self.user)
        self.sup = Supervisor.objects.create(branch=self.branch, name="A. Verma",
                                             employee=self.employee)

        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=self.branch, supervisor=self.sup, farmer=farmer,
            region=self.region, line="L1", farm_name="Alpha Farm",
            farm_capacity=5000, farm_latitude=26.44, farm_longitude=82.54)
        self.route = self.make_route(self.sup)

        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def make_route(self, supervisor, day=None):
        route = FarmRoute.objects.create(
            date=day or self.today, branch=self.branch, supervisor=supervisor,
            start_label="Head Office", start_latitude=26.43, start_longitude=82.53,
            planned_distance_km=Decimal("80"), planned_minutes=150,
            status=FarmRoute.STATUS_PLANNED)
        FarmRouteStop.objects.create(route=route, sequence=1, kind="start",
                                     label="Head Office", latitude=26.43,
                                     longitude=82.53)
        FarmRouteStop.objects.create(route=route, sequence=2, kind="farm",
                                     farm=self.farm, label="Alpha Farm",
                                     latitude=26.44, longitude=82.54,
                                     leg_distance_km=Decimal("40"), leg_minutes=70)
        return route

    def url(self, name, *args):
        # The mobile API is namespaced; reversing bare names finds nothing.
        return reverse(f"api:{name}", args=args)

    # ---- reading the day ----------------------------------------------------

    def test_a_supervisor_gets_todays_round(self):
        response = self.client.get(self.url("broiler-my-route"))
        self.assertEqual(response.status_code, 200)
        body = response.json()["data"] if "data" in response.json() else response.json()
        route = body["route"]
        self.assertEqual(route["route_no"], self.route.route_no)
        self.assertEqual(route["farm_count"], 1)
        self.assertEqual(len(route["stops"]), 2)

    def test_every_stop_carries_the_state_the_button_reads(self):
        """Worked out on the server so the phone and the register cannot
        disagree about whether a call is still open."""
        body = self.client.get(self.url("broiler-my-route")).json()
        route = body.get("data", body)["route"]
        self.assertEqual([s["state"] for s in route["stops"]], ["pending", "pending"])

    def test_a_day_with_no_round_says_so_rather_than_erroring(self):
        FarmRoute.objects.all().delete()
        body = self.client.get(self.url("broiler-my-route")).json()
        body = body.get("data", body)
        self.assertIsNone(body["route"])
        self.assertIn("No round", body["message"])

    def test_another_supervisors_round_is_not_mine(self):
        other_user = get_user_model().objects.create_user("othersup", "o@x.com", "Str0ngPass!")
        other_emp = Employee.objects.create(full_name="B. Singh", user=other_user)
        other_sup = Supervisor.objects.create(branch=self.branch, name="B. Singh",
                                              employee=other_emp)
        self.make_route(other_sup)
        body = self.client.get(self.url("broiler-my-route")).json()
        route = body.get("data", body)["route"]
        self.assertEqual(route["route_no"], self.route.route_no)

    def test_it_needs_authentication(self):
        anonymous = APIClient()
        self.assertIn(anonymous.get(self.url("broiler-my-route")).status_code,
                      (401, 403))

    # ---- driving it ---------------------------------------------------------

    def test_start_trip_then_check_in_and_out(self):
        started = self.client.post(self.url("broiler-route-start-trip", self.route.id))
        self.assertEqual(started.status_code, 200)
        body = started.json()
        self.assertTrue((body.get("data") or body)["trip_no"].startswith("TRP-"))

        arrived = self.client.post(
            self.url("broiler-route-check-in", self.route.id),
            {"farm_id": self.farm.id, "latitude": 26.4401, "longitude": 82.5402},
            format="json")
        self.assertEqual(arrived.status_code, 200)
        payload = arrived.json()
        payload = payload.get("data") or payload
        self.assertIsNotNone(payload["checked_in_at"])
        # The refreshed route comes back with it, so the phone never has to ask
        # twice to redraw the list it just changed.
        states = [s["state"] for s in payload["route"]["stops"] if s["kind"] == "farm"]
        self.assertEqual(states, ["here"])

        left = self.client.post(
            self.url("broiler-route-check-out", self.route.id),
            {"farm_id": self.farm.id}, format="json")
        self.assertEqual(left.status_code, 200)
        payload = left.json()
        payload = payload.get("data") or payload
        self.assertIsNotNone(payload["checked_out_at"])
        states = [s["state"] for s in payload["route"]["stops"] if s["kind"] == "farm"]
        self.assertEqual(states, ["done"])

    def test_the_phones_own_fix_is_recorded_as_given(self):
        """Where the supervisor actually was is the evidence; nudging it towards
        the farm's pin would destroy the only thing a check-in proves."""
        from hr.models import SupervisorTripVisit

        self.client.post(self.url("broiler-route-start-trip", self.route.id))
        self.client.post(self.url("broiler-route-check-in", self.route.id),
                         {"farm_id": self.farm.id, "latitude": 26.4409,
                          "longitude": 82.5411}, format="json")
        visit = SupervisorTripVisit.objects.get(farm=self.farm)
        self.assertAlmostEqual(visit.latitude, 26.4409, places=4)
        self.assertAlmostEqual(visit.longitude, 82.5411, places=4)

    def test_checking_in_before_starting_the_trip_is_explained(self):
        response = self.client.post(self.url("broiler-route-check-in", self.route.id),
                                    {"farm_id": self.farm.id}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Start the trip", str(response.json()))

    def test_a_check_in_with_no_farm_is_refused(self):
        self.client.post(self.url("broiler-route-start-trip", self.route.id))
        response = self.client.post(self.url("broiler-route-check-in", self.route.id),
                                    {}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_another_supervisors_round_cannot_be_started_by_id(self):
        """The id is guessable; the ownership check is what stops it."""
        other_user = get_user_model().objects.create_user("thirdsup", "t@x.com", "Str0ngPass!")
        other_emp = Employee.objects.create(full_name="C. Kumar", user=other_user)
        other_sup = Supervisor.objects.create(branch=self.branch, name="C. Kumar",
                                              employee=other_emp)
        theirs = self.make_route(other_sup)
        response = self.client.post(self.url("broiler-route-start-trip", theirs.id))
        self.assertEqual(response.status_code, 404)

    def test_an_office_login_falls_back_to_its_branch_scope(self):
        """No employee record behind the login, so it is not a supervisor —
        which is what makes these endpoints usable from a tablet in the office
        as well as from the road."""
        User = get_user_model()
        office = User.objects.create_superuser("officeadmin", "a@x.com", "Str0ngPass!")
        client = APIClient()
        client.force_authenticate(office)
        body = client.get(self.url("broiler-my-route")).json()
        route = (body.get("data") or body)["route"]
        self.assertEqual(route["route_no"], self.route.route_no)


class EstimateHonestyTests(TestCase):
    """A straight-line figure must not reach a phone looking like a road one."""

    def setUp(self):
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region,
                                       prefix="AKB")
        User = get_user_model()
        user = User.objects.create_user("estsup", "e@x.com", "Str0ngPass!")
        employee = Employee.objects.create(full_name="D. Rao", user=user)
        sup = Supervisor.objects.create(branch=branch, name="D. Rao",
                                        employee=employee)
        self.route = FarmRoute.objects.create(
            date=timezone.localdate(), branch=branch, supervisor=sup,
            planned_distance_km=Decimal("50"), planned_minutes=90,
            distance_basis=FarmRoute.BASIS_STRAIGHT)
        FarmRouteStop.objects.create(route=self.route, sequence=1, kind="start",
                                     label="Head Office")
        self.client = APIClient()
        self.client.force_authenticate(user)

    def test_an_estimated_round_is_flagged_all_the_way_to_the_phone(self):
        body = self.client.get(reverse("api:broiler-my-route")).json()
        route = (body.get("data") or body)["route"]
        self.assertTrue(route["estimated"])
