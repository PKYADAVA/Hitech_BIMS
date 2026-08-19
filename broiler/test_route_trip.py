"""A planned round against the journey actually driven.

The trip register already existed and is not rebuilt here: these tests are
about the seam. Creating a trip from a route must produce the visit rows the
phone checks into; a check-in must land on both sides; and the deviation
figures must say what happened without accusing anybody of anything the data
does not show.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from broiler.models import (Branch, BroilerFarm, Farmer, FarmRoute, FarmRouteStop,
                            Region, Supervisor)
from broiler.services.route_trip import (TripError, check_in, check_out,
                                         create_trip, deviation, employee_for)
from hr.models import Employee, SupervisorTrip


class TripSeamTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.region = Region.objects.create(description="East")
        self.branch = Branch.objects.create(branch_name="Akbarpur",
                                            region=self.region, prefix="AKB",
                                            latitude=26.43, longitude=82.53)
        self.employee = Employee.objects.create(full_name="A. Verma")
        self.sup = Supervisor.objects.create(branch=self.branch, name="A. Verma",
                                             employee=self.employee)
        self.farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farms = [self.farm("Alpha", 26.44, 82.54),
                      self.farm("Beta", 26.46, 82.57),
                      self.farm("Gamma", 26.49, 82.60)]
        self.route = self.build_route(self.farms)

    def farm(self, name, lat, lng):
        return BroilerFarm.objects.create(
            branch=self.branch, supervisor=self.sup, farmer=self.farmer,
            region=self.region, line="L1", farm_name=name, farm_capacity=5000,
            farm_latitude=lat, farm_longitude=lng)

    def build_route(self, farms, distance=Decimal("100.00")):
        route = FarmRoute.objects.create(
            date=self.today, branch=self.branch, supervisor=self.sup,
            start_label="Head Office", start_latitude=26.43, start_longitude=82.53,
            planned_distance_km=distance, planned_minutes=180,
            status=FarmRoute.STATUS_PLANNED)
        FarmRouteStop.objects.create(route=route, sequence=1, kind="start",
                                     label="Head Office", latitude=26.43,
                                     longitude=82.53)
        for i, farm in enumerate(farms, start=2):
            FarmRouteStop.objects.create(
                route=route, sequence=i, kind="farm", farm=farm,
                label=farm.farm_name, latitude=farm.farm_latitude,
                longitude=farm.farm_longitude,
                leg_distance_km=Decimal("25.00"),
                cumulative_distance_km=Decimal(str(25 * (i - 1))))
        return route

    # ---- creating the trip --------------------------------------------------

    def test_the_trip_is_raised_against_the_supervisor_s_employee_record(self):
        """Supervisor and Employee are two records of one person; the farm
        master points at the first and the trip register at the second."""
        trip = create_trip(self.route)
        self.assertEqual(trip.employee_id, self.employee.id)
        self.assertEqual(trip.date, self.today)
        self.assertTrue(trip.trip_no.startswith("TRP-"))

    def test_a_visit_row_exists_for_every_planned_farm_before_the_day_starts(self):
        """They are what the phone checks into. A supervisor with no signal at
        the farm gate still has something to record against."""
        trip = create_trip(self.route)
        self.assertEqual(trip.visits.count(), 3)
        self.assertEqual(list(trip.visits.values_list("farm__farm_name", flat=True)),
                         ["Alpha", "Beta", "Gamma"])

    def test_the_start_and_end_are_not_farms_to_be_visited(self):
        trip = create_trip(self.route)
        self.assertEqual(trip.visits.filter(farm__isnull=True).count(), 0)

    def test_the_route_records_the_trip_and_moves_to_started(self):
        trip = create_trip(self.route)
        self.route.refresh_from_db()
        self.assertEqual(self.route.trip_id, trip.id)
        self.assertEqual(self.route.status, FarmRoute.STATUS_STARTED)

    def test_a_route_can_only_be_started_once(self):
        """Re-planning a day makes a new route rather than rewriting the one
        whose journey is already recorded against it."""
        create_trip(self.route)
        with self.assertRaises(TripError) as ctx:
            create_trip(self.route)
        self.assertIn("already has trip", str(ctx.exception))

    def test_a_supervisor_with_no_employee_record_is_explained_not_crashed(self):
        lone = Supervisor.objects.create(branch=self.branch, name="Unlinked")
        route = self.build_route(self.farms[:1])
        route.supervisor = lone
        route.save()
        self.assertIsNone(employee_for(lone))
        with self.assertRaises(TripError) as ctx:
            create_trip(route)
        self.assertIn("link that supervisor to an employee", str(ctx.exception))

    # ---- arriving and leaving ----------------------------------------------

    def test_a_check_in_lands_on_the_trip_and_on_the_route(self):
        create_trip(self.route)
        visit = check_in(self.route, self.farms[0].id, latitude=26.44, longitude=82.54)
        self.assertIsNotNone(visit.checked_in_at)
        stop = self.route.stops.get(farm=self.farms[0])
        self.assertIsNotNone(stop.visited_at)
        self.assertEqual(stop.actual_sequence, 2)

    def test_checking_in_twice_is_refused_with_the_time_of_the_first(self):
        create_trip(self.route)
        check_in(self.route, self.farms[0].id)
        with self.assertRaises(TripError) as ctx:
            check_in(self.route, self.farms[0].id)
        self.assertIn("Already checked in", str(ctx.exception))

    def test_a_farm_not_on_the_trip_cannot_be_checked_into(self):
        create_trip(self.route)
        other = self.farm("Elsewhere", 26.9, 82.9)
        with self.assertRaises(TripError):
            check_in(self.route, other.id)

    def test_checking_out_before_checking_in_is_refused(self):
        create_trip(self.route)
        with self.assertRaises(TripError) as ctx:
            check_out(self.route, self.farms[0].id)
        self.assertIn("Check in", str(ctx.exception))

    def test_a_visit_becomes_a_duration(self):
        create_trip(self.route)
        now = timezone.now()
        check_in(self.route, self.farms[0].id, when=now - timedelta(minutes=40))
        visit = check_out(self.route, self.farms[0].id, when=now)
        self.assertEqual(visit.duration_minutes, 40)

    def test_checking_in_before_the_trip_exists_is_refused(self):
        with self.assertRaises(TripError) as ctx:
            check_in(self.route, self.farms[0].id)
        self.assertIn("Start the trip", str(ctx.exception))

    # ---- how far the day drifted -------------------------------------------

    def test_a_round_driven_in_order_is_not_a_deviation(self):
        create_trip(self.route)
        now = timezone.now()
        for i, farm in enumerate(self.farms):
            check_in(self.route, farm.id, when=now + timedelta(minutes=30 * i))
        report = deviation(self.route)
        self.assertFalse(report["sequence_changed"])
        self.assertEqual(report["out_of_turn"], [])
        self.assertEqual(report["visited_farms"], 3)

    def test_visiting_out_of_order_is_reported_as_a_deviation(self):
        """Planned Alpha, Beta, Gamma; driven Alpha, Gamma, Beta."""
        create_trip(self.route)
        now = timezone.now()
        check_in(self.route, self.farms[0].id, when=now)
        check_in(self.route, self.farms[2].id, when=now + timedelta(minutes=30))
        check_in(self.route, self.farms[1].id, when=now + timedelta(minutes=60))
        report = deviation(self.route)
        self.assertTrue(report["sequence_changed"])
        self.assertTrue(any(o["farm"] == "Gamma" for o in report["out_of_turn"]))

    def test_a_farm_nobody_reached_is_named(self):
        create_trip(self.route)
        check_in(self.route, self.farms[0].id)
        report = deviation(self.route)
        self.assertEqual(sorted(report["missed_farms"]), ["Beta", "Gamma"])

    def test_efficiency_compares_the_plan_with_the_odometer(self):
        trip = create_trip(self.route)
        trip.start_odometer, trip.end_odometer = 1000, 1125      # 125 km driven
        trip.save()
        report = deviation(self.route)
        self.assertTrue(report["actual_distance_known"])
        self.assertEqual(report["actual_distance_km"], 125.0)
        self.assertEqual(report["extra_distance_km"], 25.0)
        self.assertEqual(report["efficiency_pct"], 80.0)         # 100 / 125

    def test_a_missing_odometer_is_not_a_zero_kilometre_day(self):
        """A deviation report that treats an unfilled odometer as nought
        accuses somebody of never having gone out."""
        create_trip(self.route)
        report = deviation(self.route)
        self.assertFalse(report["actual_distance_known"])
        self.assertIsNone(report["efficiency_pct"])

    def test_a_shorter_day_than_planned_is_left_as_it_falls(self):
        """Above 100% means a farm was skipped or the router did not know a
        road. Capping it would hide exactly that."""
        trip = create_trip(self.route)
        trip.start_odometer, trip.end_odometer = 1000, 1080      # 80 km
        trip.save()
        self.assertEqual(deviation(self.route)["efficiency_pct"], 125.0)

    def test_a_route_never_started_has_nothing_to_compare(self):
        report = deviation(self.route)
        self.assertEqual(report["trip_no"], "")
        self.assertEqual(report["visited_farms"], 0)


class TripEndpointTests(TestCase):
    """The seam over HTTP, including who may work it."""

    def setUp(self):
        self.today = timezone.localdate()
        region = Region.objects.create(description="East")
        self.branch = Branch.objects.create(branch_name="Akbarpur", region=region,
                                            prefix="AKB")
        employee = Employee.objects.create(full_name="A. Verma")
        sup = Supervisor.objects.create(branch=self.branch, name="A. Verma",
                                        employee=employee)
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=self.branch, supervisor=sup, farmer=farmer, region=region,
            line="L1", farm_name="Alpha", farm_capacity=5000,
            farm_latitude=26.44, farm_longitude=82.54)
        self.route = FarmRoute.objects.create(
            date=self.today, branch=self.branch, supervisor=sup,
            start_label="Head Office", planned_distance_km=Decimal("50"),
            planned_minutes=90, status=FarmRoute.STATUS_PLANNED)
        FarmRouteStop.objects.create(route=self.route, sequence=1, kind="start",
                                     label="Head Office")
        FarmRouteStop.objects.create(route=self.route, sequence=2, kind="farm",
                                     farm=self.farm, label="Alpha",
                                     latitude=26.44, longitude=82.54)
        User = get_user_model()
        self.client.force_login(
            User.objects.create_superuser("tripadmin", "t@x.com", "Str0ngPass!"))

    def post(self, name, payload=None):
        from django.urls import reverse

        return self.client.post(reverse(name, args=[self.route.id]),
                                data=payload or {}, content_type="application/json")

    def test_start_trip_creates_the_trip(self):
        response = self.post("route_start_trip")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["trip_no"].startswith("TRP-"))
        self.assertEqual(SupervisorTrip.objects.count(), 1)

    def test_check_in_and_out_over_http(self):
        self.post("route_start_trip")
        response = self.post("route_check_in", {"farm_id": self.farm.id,
                                                "latitude": 26.44, "longitude": 82.54})
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.json()["checked_in_at"])
        response = self.post("route_check_out", {"farm_id": self.farm.id})
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.json()["checked_out_at"])

    def test_a_check_in_with_no_farm_is_refused(self):
        self.post("route_start_trip")
        self.assertEqual(self.post("route_check_in", {}).status_code, 400)

    def test_the_detail_endpoint_carries_the_deviation(self):
        from django.urls import reverse

        self.post("route_start_trip")
        response = self.client.get(reverse("route_detail", args=[self.route.id]))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["route"]["route_no"], self.route.route_no)
        self.assertIn("deviation", body)
        self.assertEqual(len(body["stops"]), 2)

    def test_another_branch_s_route_is_not_reachable(self):
        from django.contrib.auth.models import Group
        from django.urls import reverse
        from user.models import GroupAccessProfile, GroupTabPermission

        User = get_user_model()
        other = Branch.objects.create(branch_name="Bahraich",
                                      region=Region.objects.first(), prefix="BHR")
        clerk = User.objects.create_user("tripclerk", "c@x.com", "Str0ngPass!")
        group = Group.objects.create(name="Bahraich only")
        clerk.groups.add(group)
        GroupTabPermission.objects.create(group=group, tab_code="route_history",
                                          can_view=True)
        access = GroupAccessProfile.objects.create(group=group, all_branches=False)
        access.branches.add(other)
        self.client.force_login(clerk)
        response = self.client.get(reverse("route_detail", args=[self.route.id]))
        self.assertEqual(response.status_code, 404)
