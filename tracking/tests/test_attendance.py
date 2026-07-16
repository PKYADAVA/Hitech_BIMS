# pylint: disable=no-member
"""Tests for GPS attendance integration (Phase 6)."""

import json
from datetime import time as dt_time, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from hr.models import Attendance, Employee

from tracking.dtos import AttendanceEvent
from tracking.models import (
    EmployeeGeofence,
    EmployeeGpsAttendance,
    TrackingLog,
    TrackingProvider,
    TrackingSettings,
)
from tracking.services.attendance_service import AttendanceIntegrationService
from tracking.services.sync_service import SyncService

OFFICE_LAT = Decimal("26.850000")
OFFICE_LNG = Decimal("80.950000")


def event(kind, when, lat=OFFICE_LAT, lng=OFFICE_LNG, photo=""):
    return AttendanceEvent(
        external_employee_id="EXT-1", event=kind, occurred_at=when,
        latitude=lat, longitude=lng, photo_url=photo,
    )


class AttendanceServiceTests(TestCase):
    def setUp(self):
        self.employee = Employee.objects.create(full_name="Field Person")
        self.provider = TrackingProvider.objects.create(
            name="Mock", provider_type="mock", api_url="https://mock.invalid"
        )
        self.fence = EmployeeGeofence.objects.create(
            name="Head Office", geofence_type="office",
            center_latitude=OFFICE_LAT, center_longitude=OFFICE_LNG, radius_m=200,
        )
        self.settings = TrackingSettings.get_solo()
        self.settings.late_check_in_time = dt_time(9, 30)
        self.settings.early_check_out_time = dt_time(17, 0)
        self.settings.save()
        self.service = AttendanceIntegrationService(self.settings)
        # 08:55 local on today's date.
        self.morning = timezone.make_aware(
            timezone.datetime.combine(timezone.localdate(), dt_time(8, 55))
        )

    def test_check_in_inside_fence_on_time(self):
        record = self.service.apply_event(self.employee, self.provider,
                                          event("check_in", self.morning))
        self.assertEqual(record.date, timezone.localdate())
        self.assertTrue(record.check_in_inside_fence)
        self.assertEqual(record.geofence, self.fence)
        self.assertFalse(record.is_late)
        self.assertEqual(record.status, "pending")
        self.assertIsNone(record.attendance)  # not mirrored before approval

    def test_late_check_in_raises_alert_once(self):
        late_time = self.morning + timedelta(hours=1)  # 09:55
        record = self.service.apply_event(self.employee, self.provider,
                                          event("check_in", late_time))
        self.assertTrue(record.is_late)
        self.assertEqual(record.late_by, timedelta(minutes=25))
        self.assertEqual(
            TrackingLog.objects.filter(event="late_check_in").count(), 1)
        # Replaying the same event must not duplicate the alert.
        self.service.apply_event(self.employee, self.provider,
                                 event("check_in", late_time))
        self.assertEqual(
            TrackingLog.objects.filter(event="late_check_in").count(), 1)

    def test_check_in_outside_fence_flagged(self):
        record = self.service.apply_event(
            self.employee, self.provider,
            event("check_in", self.morning, lat=Decimal("26.900000")),  # ~5.5 km away
        )
        self.assertFalse(record.check_in_inside_fence)

    def test_first_check_in_and_last_check_out_win(self):
        self.service.apply_event(self.employee, self.provider,
                                 event("check_in", self.morning))
        self.service.apply_event(self.employee, self.provider,
                                 event("check_in", self.morning + timedelta(hours=2)))
        self.service.apply_event(self.employee, self.provider,
                                 event("check_out", self.morning + timedelta(hours=8)))
        self.service.apply_event(self.employee, self.provider,
                                 event("check_out", self.morning + timedelta(hours=9)))
        record = EmployeeGpsAttendance.objects.get()
        self.assertEqual(record.check_in_at, self.morning)
        self.assertEqual(record.check_out_at, self.morning + timedelta(hours=9))
        self.assertFalse(record.is_early_exit)  # 17:55 > 17:00

    def test_early_exit_flagged(self):
        self.service.apply_event(self.employee, self.provider,
                                 event("check_in", self.morning))
        self.service.apply_event(self.employee, self.provider,
                                 event("check_out", self.morning + timedelta(hours=6)))  # 14:55
        record = EmployeeGpsAttendance.objects.get()
        self.assertTrue(record.is_early_exit)
        self.assertTrue(TrackingLog.objects.filter(event="early_check_out").exists())

    def test_approval_mirrors_to_hr_attendance(self):
        record = self.service.apply_event(self.employee, self.provider,
                                          event("check_in", self.morning))
        self.assertEqual(Attendance.objects.count(), 0)
        approver = User.objects.create_user("approver")
        self.service.approve(record, user=approver)
        attendance = Attendance.objects.get()
        self.assertEqual(attendance.employee, self.employee)
        self.assertEqual(attendance.status, "Present")
        self.assertEqual(attendance.check_in_time,
                         timezone.localtime(self.morning).time())
        self.assertEqual(record.attendance, attendance)

    def test_manual_hr_check_in_never_overwritten(self):
        manual = Attendance.objects.create(
            employee=self.employee, date=timezone.localdate(),
            check_in_time=dt_time(9, 0), status="First Half",
        )
        record = self.service.apply_event(self.employee, self.provider,
                                          event("check_in", self.morning))
        self.service.approve(record, user=None)
        manual.refresh_from_db()
        self.assertEqual(manual.check_in_time, dt_time(9, 0))   # preserved
        self.assertEqual(manual.status, "First Half")           # preserved

    def test_on_leave_hr_row_left_untouched(self):
        Attendance.objects.create(
            employee=self.employee, date=timezone.localdate(),
            status="On Leave",
        )
        record = self.service.apply_event(self.employee, self.provider,
                                          event("check_in", self.morning))
        self.service.approve(record, user=None)
        attendance = Attendance.objects.get()
        self.assertEqual(attendance.status, "On Leave")
        self.assertIsNone(attendance.check_in_time)

    def test_auto_approve_mirrors_immediately(self):
        self.settings.attendance_auto_approve = True
        self.settings.save()
        service = AttendanceIntegrationService(TrackingSettings.get_solo())
        record = service.apply_event(self.employee, self.provider,
                                     event("check_in", self.morning))
        self.assertEqual(record.status, "approved")
        self.assertEqual(Attendance.objects.count(), 1)

    def test_approved_checkout_updates_hr_row(self):
        self.settings.attendance_auto_approve = True
        self.settings.save()
        service = AttendanceIntegrationService(TrackingSettings.get_solo())
        service.apply_event(self.employee, self.provider,
                            event("check_in", self.morning))
        service.apply_event(self.employee, self.provider,
                            event("check_out", self.morning + timedelta(hours=9)))
        attendance = Attendance.objects.get()
        self.assertEqual(
            attendance.check_out_time,
            timezone.localtime(self.morning + timedelta(hours=9)).time(),
        )


class AttendanceSyncIntegrationTests(TestCase):
    """The sync engine feeds the attendance service end-to-end."""

    def test_mock_provider_sync_builds_gps_attendance(self):
        TrackingProvider.objects.create(
            name="Mock", provider_type="mock", api_url="https://mock.invalid"
        )
        Employee.objects.create(full_name="Mock Employee One",
                                personal_contact=9000000001)
        service = SyncService(sleep=lambda seconds: None)
        runs = service.sync_all(kinds=["employees", "attendance"])
        self.assertEqual({run.status for run in runs}, {"success"})
        # Mock events sit at the window edges (24h apart), so the check-in
        # and check-out land on their own local dates — one record each.
        records = list(EmployeeGpsAttendance.objects.order_by("date"))
        self.assertEqual(len(records), 2)
        self.assertIsNotNone(records[0].check_in_at)
        self.assertIsNotNone(records[1].check_out_at)

    def test_attendance_sync_disabled_skips_gps_records(self):
        settings_row = TrackingSettings.get_solo()
        settings_row.attendance_sync_enabled = False
        settings_row.save()
        TrackingProvider.objects.create(
            name="Mock", provider_type="mock", api_url="https://mock.invalid"
        )
        Employee.objects.create(full_name="Mock Employee One",
                                personal_contact=9000000001)
        SyncService(sleep=lambda seconds: None).sync_all(
            kinds=["employees", "attendance"])
        self.assertEqual(EmployeeGpsAttendance.objects.count(), 0)


class AttendanceAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("tester", password="pass12345")
        self.client.login(username="tester", password="pass12345")
        self.employee = Employee.objects.create(full_name="Field Person")
        self.record = EmployeeGpsAttendance.objects.create(
            employee=self.employee, date=timezone.localdate(),
            check_in_at=timezone.now(), is_late=True,
            late_by=timedelta(minutes=12),
            check_in_latitude="26.85", check_in_longitude="80.95",
        )

    def test_list_and_tiles(self):
        response = self.client.get(
            reverse("api_tracking_attendance"),
            {"date": timezone.localdate().isoformat()},
        )
        data = json.loads(response.content)
        self.assertEqual(data["tiles"]["late"], 1)
        self.assertEqual(len(data["records"]), 1)
        self.assertEqual(data["records"][0]["late_by_minutes"], 12)

    def test_approve_endpoint_mirrors_hr(self):
        response = self.client.post(
            reverse("api_tracking_attendance_approve"),
            json.dumps({"action": "approve", "ids": [self.record.pk]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, "approved")
        self.assertTrue(Attendance.objects.filter(employee=self.employee).exists())
        self.assertTrue(
            TrackingLog.objects.filter(event="attendance_approval").exists())

    def test_reject_endpoint(self):
        response = self.client.post(
            reverse("api_tracking_attendance_approve"),
            json.dumps({"action": "reject", "ids": [self.record.pk],
                        "reason": "wrong location"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, "rejected")
        self.assertEqual(self.record.rejection_reason, "wrong location")
        self.assertEqual(Attendance.objects.count(), 0)

    def test_page_renders(self):
        response = self.client.get(reverse("tracking_attendance"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "GPS Attendance Map")
