"""The nine route and visit reports.

They are nine questions about three tables, so most of what can go wrong is
shared: a column that says one thing on screen and another in the spreadsheet,
a report that reaches past the reader's data scope, or a figure that quietly
turns an unknown into a nought. Those are what these tests are about.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from broiler.models import (Branch, BroilerBatch, BroilerFarm, Farmer, FarmRoute,
                            FarmRouteStop, Region, Supervisor)
from broiler.services import route_reports as reports
from broiler.services.route_trip import check_in, create_trip
from hr.models import Employee


class ReportShapeTests(TestCase):
    """Every report answers, whatever the data looks like."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser("repadmin", "r@x.com", "Str0ngPass!")

    def test_all_nine_are_registered_and_build_on_an_empty_database(self):
        """A report that only works once somebody has driven a round is a
        report that breaks on the day it is most needed — the first one."""
        self.assertEqual(len(reports.REPORTS), 9)
        for key, label in reports.REPORTS:
            with self.subTest(report=key):
                columns, rows, summary = reports.build(key, self.admin, {})
                self.assertTrue(columns, f"{key} has no columns")
                self.assertEqual(rows, [])
                self.assertIsInstance(summary, dict)

    def test_every_row_matches_its_column_count(self):
        """The screen and the spreadsheet render from the same pair; a row of
        the wrong width silently shifts every value one column left."""
        farm_fixture(self)
        for key, _label in reports.REPORTS:
            with self.subTest(report=key):
                columns, rows, _ = reports.build(key, self.admin, {})
                for row in rows:
                    self.assertEqual(len(row), len(columns))

    def test_an_unknown_report_is_refused(self):
        with self.assertRaises(KeyError):
            reports.build("not_a_report", self.admin, {})


def farm_fixture(case):
    """A branch, a supervisor, two farms — one pinned, one not."""
    case.region = Region.objects.create(description="East")
    case.branch = Branch.objects.create(branch_name="Akbarpur", region=case.region,
                                        prefix="AKB", latitude=26.43, longitude=82.53)
    case.employee = Employee.objects.create(full_name="A. Verma")
    case.sup = Supervisor.objects.create(branch=case.branch, name="A. Verma",
                                         employee=case.employee)
    farmer = Farmer.objects.create(farmer_name="S. Yadav")
    case.pinned = BroilerFarm.objects.create(
        branch=case.branch, supervisor=case.sup, farmer=farmer, region=case.region,
        line="L1", farm_name="Pinned Farm", farm_capacity=5000,
        farm_latitude=26.44, farm_longitude=82.54, gps_accuracy=6.0,
        location_captured_at=timezone.localdate())
    case.blind = BroilerFarm.objects.create(
        branch=case.branch, supervisor=case.sup, farmer=farmer, region=case.region,
        line="L1", farm_name="Blind Farm", farm_capacity=5000)
    return case


class GpsReportTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser("gpsadmin", "g@x.com", "Str0ngPass!")
        farm_fixture(self)

    def test_the_missing_report_lists_only_the_unpinned(self):
        _cols, rows, summary = reports.build("gps_missing", self.admin, {})
        self.assertEqual([r[1] for r in rows], ["Blind Farm"])
        self.assertEqual(summary["Farms without a pin"], 1)

    def test_a_farm_never_attempted_says_never(self):
        _cols, rows, _ = reports.build("gps_missing", self.admin, {})
        self.assertEqual(rows[0][7], "never")

    def test_the_accuracy_report_lists_only_the_pinned(self):
        _cols, rows, summary = reports.build("gps_accuracy", self.admin, {})
        self.assertEqual([r[1] for r in rows], ["Pinned Farm"])
        self.assertEqual(summary["Pinned farms"], 1)

    def test_a_good_fresh_unverified_pin_is_flagged_only_for_verification(self):
        _cols, rows, _ = reports.build("gps_accuracy", self.admin, {})
        self.assertEqual(rows[0][10], "not verified")

    def test_a_coarse_reading_is_called_coarse(self):
        """A fix good to two kilometres routes somebody to the wrong village."""
        BroilerFarm.objects.filter(pk=self.pinned.pk).update(gps_accuracy=2000)
        _cols, rows, _ = reports.build("gps_accuracy", self.admin, {})
        self.assertIn("coarse", rows[0][10])

    def test_an_old_pin_is_called_old(self):
        from datetime import timedelta

        BroilerFarm.objects.filter(pk=self.pinned.pk).update(
            location_captured_at=timezone.localdate() - timedelta(days=800),
            location_verified=True, gps_accuracy=5)
        _cols, rows, _ = reports.build("gps_accuracy", self.admin, {})
        self.assertIn("year(s) old", rows[0][10])


class DistanceReportTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser("distadmin", "d@x.com", "Str0ngPass!")
        farm_fixture(self)

    def test_an_unrouted_farm_has_no_distance_rather_than_a_guess(self):
        """Printing a ruler's answer under a column headed "by road" is how an
        estimate becomes a fact."""
        _cols, rows, summary = reports.build("farm_distance", self.admin, {})
        for row in rows:
            self.assertIsNone(row[6])
            self.assertEqual(row[7], "not routed yet")
        self.assertEqual(summary["Measured by road"], 0)
        self.assertIsNone(summary["Average distance"])

    def test_a_routed_farm_takes_the_distance_the_route_measured(self):
        route = FarmRoute.objects.create(
            date=timezone.localdate(), branch=self.branch, supervisor=self.sup,
            planned_distance_km=Decimal("40"), planned_minutes=60)
        FarmRouteStop.objects.create(route=route, sequence=1, kind="start",
                                     label="Head Office")
        FarmRouteStop.objects.create(route=route, sequence=2, kind="farm",
                                     farm=self.pinned, label="Pinned Farm",
                                     leg_distance_km=Decimal("18.40"))
        _cols, rows, summary = reports.build("farm_distance", self.admin, {})
        pinned = [r for r in rows if r[1] == "Pinned Farm"][0]
        self.assertEqual(pinned[6], 18.4)
        self.assertEqual(summary["Measured by road"], 1)


class ComplianceAndDeviationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser("compadmin", "c@x.com", "Str0ngPass!")
        farm_fixture(self)
        BroilerBatch.objects.create(broiler_farm=self.pinned, batch_name="B-1",
                                    start_date=timezone.localdate())
        self.route = FarmRoute.objects.create(
            date=timezone.localdate(), branch=self.branch, supervisor=self.sup,
            planned_distance_km=Decimal("100"), planned_minutes=120,
            start_label="Head Office")
        FarmRouteStop.objects.create(route=self.route, sequence=1, kind="start",
                                     label="Head Office")
        FarmRouteStop.objects.create(route=self.route, sequence=2, kind="farm",
                                     farm=self.pinned, label="Pinned Farm",
                                     leg_distance_km=Decimal("50"))

    def test_a_live_flock_nobody_visited_is_the_row_the_report_exists_for(self):
        _cols, rows, summary = reports.build("visit_compliance", self.admin, {})
        pinned = [r for r in rows if r[1] == "Pinned Farm"][0]
        self.assertEqual(pinned[10], "Not visited")
        self.assertEqual(summary["Not visited with a live flock"], 1)

    def test_an_empty_farm_is_not_accused_of_being_missed(self):
        _cols, rows, _ = reports.build("visit_compliance", self.admin, {})
        blind = [r for r in rows if r[1] == "Blind Farm"][0]
        self.assertEqual(blind[10], "No visit needed")

    def test_a_visited_farm_meets_its_plan(self):
        create_trip(self.route)
        check_in(self.route, self.pinned.id)
        _cols, rows, _ = reports.build("visit_compliance", self.admin, {})
        pinned = [r for r in rows if r[1] == "Pinned Farm"][0]
        self.assertEqual(pinned[10], "Met")

    def test_the_deviation_report_reports_an_unknown_odometer_as_unknown(self):
        """Not as a zero-kilometre day, which would accuse somebody of never
        having gone out."""
        create_trip(self.route)
        _cols, rows, _ = reports.build("route_deviation", self.admin, {})
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0][9])       # actual km
        self.assertIsNone(rows[0][11])      # efficiency

    def test_the_deviation_report_measures_a_filled_odometer(self):
        trip = create_trip(self.route)
        trip.start_odometer, trip.end_odometer = 500, 625
        trip.save()
        _cols, rows, _ = reports.build("route_deviation", self.admin, {})
        self.assertEqual(rows[0][9], 125.0)
        self.assertEqual(rows[0][11], 80.0)

    def test_planned_against_actual_marks_the_stop_reached(self):
        create_trip(self.route)
        check_in(self.route, self.pinned.id)
        _cols, rows, summary = reports.build("planned_vs_actual", self.admin, {})
        self.assertEqual(summary["Reached"], 1)
        self.assertEqual(rows[0][8], "Yes")

    def test_supervisor_travel_totals_the_rounds(self):
        _cols, rows, _ = reports.build("supervisor_travel", self.admin, {})
        self.assertEqual(rows[0][0], "A. Verma")
        self.assertEqual(rows[0][2], 1)          # rounds
        self.assertEqual(rows[0][4], 100.0)      # planned km
        self.assertIsNone(rows[0][5])            # no odometer yet


class ReportScopingTests(TestCase):
    """A report may not show a farm the map would not."""

    def setUp(self):
        farm_fixture(self)
        self.other = Branch.objects.create(branch_name="Bahraich",
                                           region=self.region, prefix="BHR")
        farmer = Farmer.objects.create(farmer_name="Other Farmer")
        other_sup = Supervisor.objects.create(branch=self.other, name="Other Sup")
        BroilerFarm.objects.create(
            branch=self.other, supervisor=other_sup, farmer=farmer,
            region=self.region, line="L1", farm_name="Other Farm",
            farm_capacity=5000, farm_latitude=26.9, farm_longitude=82.9)

    def scoped_user(self):
        from user.models import GroupAccessProfile, GroupTabPermission

        User = get_user_model()
        user = User.objects.create_user("repclerk", "rc@x.com", "Str0ngPass!")
        group = Group.objects.create(name="Akbarpur reports")
        user.groups.add(group)
        GroupTabPermission.objects.create(group=group, tab_code="route_reports",
                                          can_view=True)
        access = GroupAccessProfile.objects.create(group=group, all_branches=False)
        access.branches.add(self.branch)
        return user

    def test_a_scoped_reader_sees_only_their_own_farms(self):
        user = self.scoped_user()
        _cols, rows, _ = reports.build("gps_accuracy", user, {})
        self.assertNotIn("Other Farm", [r[1] for r in rows])

    def test_the_same_holds_for_the_compliance_report(self):
        user = self.scoped_user()
        _cols, rows, _ = reports.build("visit_compliance", user, {})
        self.assertNotIn("Other Farm", [r[1] for r in rows])


class ReportPageTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.client.force_login(
            User.objects.create_superuser("reppage", "p@x.com", "Str0ngPass!"))
        farm_fixture(self)

    def test_the_page_offers_every_report(self):
        html = self.client.get(reverse("route_reports")).content.decode()
        for _key, label in reports.REPORTS:
            self.assertIn(label, html)

    def test_an_unknown_report_falls_back_rather_than_erroring(self):
        response = self.client.get(reverse("route_reports"),
                                   {"report": "nonsense", "submit": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["report_key"], reports.REPORTS[0][0])

    def test_the_spreadsheet_carries_the_same_columns_as_the_screen(self):
        """The export builds from the same (columns, rows) pair the page does,
        and this is what keeps that true rather than merely intended."""
        import io

        import openpyxl

        user = get_user_model().objects.get(username="reppage")
        columns, _rows, _summary = reports.build("gps_accuracy", user, {})

        response = self.client.get(reverse("route_reports"),
                                   {"report": "gps_accuracy", "submit": "1",
                                    "export": "excel"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("spreadsheet", response["Content-Type"])
        sheet = openpyxl.load_workbook(io.BytesIO(response.content)).active
        header = [cell.value for cell in next(sheet.iter_rows(max_row=1))]
        self.assertEqual(header, columns)
