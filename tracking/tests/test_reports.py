# pylint: disable=no-member
"""Tests for Phase 8: route/timeline API and the report centre."""

import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from hr.models import Employee
from inventory.models import Warehouse
from sales.models import Customer

from tracking.models import (
    EmployeeCustomerVisit,
    EmployeeGpsAttendance,
    EmployeeLocationHistory,
    EmployeeRoute,
    TrackingLog,
)
from tracking.services.report_service import REPORTS, build
from tracking.services.route_service import RouteBuilder


def seed_day(employee, day_offset=0):
    """A realistic day: pings 09:00-13:00 with a long stop, visit, attendance."""
    day = timezone.localdate() - timedelta(days=day_offset)
    base = timezone.make_aware(
        timezone.datetime.combine(day, timezone.datetime.min.time())
    ) + timedelta(hours=9)

    # Travel 09:00→10:00 (moving), stop 10:00→11:00, travel 11:00→12:00.
    points = []
    for index in range(13):  # every 10 min, 09:00..11:00
        moving = index < 6
        offset = Decimal(index if moving else 6) * Decimal("0.005")
        points.append(EmployeeLocationHistory(
            employee=employee, latitude=Decimal("26.85") + offset,
            longitude=Decimal("80.95") + offset,
            speed_kmh=30.0 if moving else 0.0,
            recorded_at=base + timedelta(minutes=10 * index),
        ))
    EmployeeLocationHistory.objects.bulk_create(points)
    route = RouteBuilder().rebuild(employee, day)

    EmployeeGpsAttendance.objects.create(
        employee=employee, date=day,
        check_in_at=base, check_out_at=base + timedelta(hours=8),
        check_in_latitude="26.85", check_in_longitude="80.95",
        is_late=True, late_by=timedelta(minutes=15),
    )
    EmployeeCustomerVisit.objects.create(
        employee=employee, customer=Customer.objects.get_or_create(name="ACME")[0],
        visit_date=day, check_in_at=base + timedelta(hours=1),
        check_out_at=base + timedelta(hours=2), duration=timedelta(hours=1),
        check_in_latitude="26.88", check_in_longitude="80.98", status="completed",
    )
    return day, route


class RouteApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("tester", password="pass12345")
        self.client.login(username="tester", password="pass12345")
        self.warehouse = Warehouse.objects.create(name="Main")
        self.employee = Employee.objects.create(
            full_name="Route Runner", warehouse=self.warehouse)
        self.day, self.route = seed_day(self.employee)

    def test_route_summary_and_polyline(self):
        response = self.client.get(reverse("api_tracking_route"), {
            "employee": self.employee.pk, "date": self.day.isoformat(),
        })
        data = json.loads(response.content)
        self.assertEqual(data["employee"], "Route Runner")
        self.assertIsNotNone(data["route"])
        self.assertGreater(data["route"]["distance_km"], 0)
        self.assertTrue(data["route"]["polyline"])
        self.assertGreaterEqual(data["route"]["stops_count"], 1)

    def test_timeline_is_chronological_and_merged(self):
        response = self.client.get(reverse("api_tracking_route"), {
            "employee": self.employee.pk, "date": self.day.isoformat(),
        })
        data = json.loads(response.content)
        types = [entry["type"] for entry in data["timeline"]]
        self.assertEqual(types[0], "check_in")
        self.assertEqual(types[-1], "check_out")
        self.assertIn("visit", types)
        times = [entry["time"] for entry in data["timeline"]]
        self.assertEqual(times, sorted(times))
        self.assertIn("late", data["timeline"][0]["label"])

    def test_unknown_employee_404(self):
        response = self.client.get(reverse("api_tracking_route"), {"employee": 99999})
        self.assertEqual(response.status_code, 404)

    def test_page_renders(self):
        response = self.client.get(reverse("tracking_routes"))
        self.assertContains(response, "Route History")


class ReportServiceTests(TestCase):
    def setUp(self):
        self.warehouse = Warehouse.objects.create(name="Main")
        self.employee = Employee.objects.create(
            full_name="Report Subject", warehouse=self.warehouse)
        self.other = Employee.objects.create(full_name="Other Person")
        self.day, _ = seed_day(self.employee)
        seed_day(self.other, day_offset=1)
        TrackingLog.objects.create(
            log_type="alert", event="gps_disabled", severity="warning",
            message="GPS disabled on device", employee=self.employee,
        )
        self.start = timezone.localdate() - timedelta(days=7)
        self.end = timezone.localdate()

    def test_every_report_builds_with_consistent_shape(self):
        for key in REPORTS:
            data = build(key, self.start, self.end)
            self.assertIn("columns", data, key)
            self.assertIn("rows", data, key)
            self.assertIn("summary", data, key)
            column_keys = {column["key"] for column in data["columns"]}
            for row in data["rows"]:
                self.assertTrue(set(row) >= column_keys,
                                f"{key}: row missing columns {column_keys - set(row)}")

    def test_daily_tracking_counts_visits_per_day(self):
        data = build("daily_tracking", self.start, self.end,
                     employee_id=self.employee.pk)
        self.assertEqual(len(data["rows"]), 1)
        self.assertEqual(data["rows"][0]["visits"], 1)
        self.assertGreater(data["rows"][0]["distance_km"], 0)

    def test_attendance_report_flags_late(self):
        data = build("attendance_gps", self.start, self.end)
        late_rows = [row for row in data["rows"] if row["late"] == "Yes"]
        self.assertEqual(len(late_rows), 2)
        self.assertEqual(data["summary"]["Late arrivals"], 2)

    def test_travel_distance_aggregates(self):
        data = build("travel_distance", self.start, self.end)
        self.assertEqual(len(data["rows"]), 2)
        self.assertGreater(data["summary"]["Total distance (km)"], 0)

    def test_working_hours(self):
        data = build("working_hours", self.start, self.end,
                     employee_id=self.employee.pk)
        self.assertEqual(data["rows"][0]["hours"], 8.0)

    def test_exceptions_report_includes_alert(self):
        data = build("exceptions", self.start, self.end)
        # 2 late check-ins (one per seeded day) are logged? Alerts are only
        # written by the attendance service; here only the manual gps_disabled
        # log exists.
        events = [row["event"] for row in data["rows"]]
        self.assertIn("GPS Disabled", events)

    def test_warehouse_filter(self):
        data = build("monthly_summary", self.start, self.end,
                     warehouse_id=self.warehouse.pk)
        self.assertEqual(len(data["rows"]), 1)
        self.assertEqual(data["rows"][0]["employee"], "Report Subject")


class ReportsApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("tester", password="pass12345")
        self.client.login(username="tester", password="pass12345")
        self.employee = Employee.objects.create(full_name="Api Subject")
        seed_day(self.employee)

    def test_json_response(self):
        response = self.client.get(reverse("api_tracking_reports"),
                                   {"report": "daily_tracking"})
        data = json.loads(response.content)
        self.assertEqual(data["report"], "daily_tracking")
        self.assertEqual(len(data["rows"]), 1)

    def test_unknown_report_400(self):
        response = self.client.get(reverse("api_tracking_reports"),
                                   {"report": "nope"})
        self.assertEqual(response.status_code, 400)

    def test_csv_export(self):
        response = self.client.get(reverse("api_tracking_reports"), {
            "report": "travel_distance", "format": "csv",
        })
        self.assertEqual(response["Content-Type"], "text/csv")
        content = response.content.decode()
        self.assertIn("Total (km)", content)
        self.assertIn("Api Subject", content)

    def test_page_renders(self):
        response = self.client.get(reverse("tracking_reports"))
        self.assertContains(response, "Tracking Reports")
        self.assertContains(response, "Monthly Summary")
