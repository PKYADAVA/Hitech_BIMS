# pylint: disable=no-member
"""GPS attendance integration.

Turns provider check-in/check-out events into ``EmployeeGpsAttendance`` rows
(geofence-verified, late/early evaluated) and mirrors approved rows into
``hr.Attendance`` — the table payroll reads.

HR-safety rules (payroll must keep working untouched):

* ``hr.Attendance`` is written only here, via :meth:`mirror_to_hr`.
* ``check_in_time`` is only filled when empty — a manually entered check-in
  is never overwritten.
* ``check_out_time`` follows the latest GPS check-out (people check out more
  than once; last wins), unless the HR row says "On Leave".
* ``status`` is set to Present only on rows this service creates or rows
  currently marked Absent; First Half / Second Half / On Leave set by HR
  staff are never changed.

Everything is idempotent: replaying a sync window re-applies the same events
onto the same (employee, date) row, and alerts fire only on state
transitions, never on re-processing.
"""

import logging
from datetime import datetime, timedelta

from django.utils import timezone

from hr.models import Attendance

from ..dtos import AttendanceEvent
from ..models import (
    EmployeeGeofence,
    EmployeeGpsAttendance,
    EmployeeLiveLocation,
    TrackingLog,
    TrackingSettings,
)
from .geo import haversine_km

logger = logging.getLogger("tracking.attendance")

#: Fence types an attendance check-in is verified against.
WORK_FENCE_TYPES = ("office", "warehouse", "farm")


class AttendanceIntegrationService:
    """Applies GPS check-in/out events for one provider run."""

    def __init__(self, settings: TrackingSettings = None):
        self._settings = settings or TrackingSettings.get_solo()
        self._fences = None  # lazy: only loaded when an event actually arrives

    # ---------------------------------------------------------------- events

    def apply_event(self, employee, provider, event: AttendanceEvent) -> EmployeeGpsAttendance:
        """Fold one check-in/out event into the employee's day record."""
        day = timezone.localtime(event.occurred_at).date()
        record, _created = EmployeeGpsAttendance.objects.get_or_create(
            employee=employee, date=day, defaults={"provider": provider}
        )

        if event.event == "check_in":
            self._apply_check_in(record, event)
        else:
            self._apply_check_out(record, event)
        record.save()

        if self._settings.attendance_auto_approve and record.status == "pending":
            self.approve(record, user=None, auto=True)
        return record

    def _apply_check_in(self, record, event):
        # First check-in of the day wins; later duplicates don't move it.
        if record.check_in_at and event.occurred_at >= record.check_in_at:
            return
        record.check_in_at = event.occurred_at
        record.check_in_latitude = event.latitude
        record.check_in_longitude = event.longitude
        record.check_in_address = event.address
        if event.photo_url:
            record.check_in_photo_url = event.photo_url[:500]
        record.geofence, record.check_in_inside_fence = self._fence_verdict(
            event.latitude, event.longitude
        )
        self._evaluate_late(record)
        self._sync_live_flag(record.employee_id, checked_in=True)

    def _apply_check_out(self, record, event):
        # Latest check-out of the day wins.
        if record.check_out_at and event.occurred_at <= record.check_out_at:
            return
        record.check_out_at = event.occurred_at
        record.check_out_latitude = event.latitude
        record.check_out_longitude = event.longitude
        record.check_out_address = event.address
        if event.photo_url:
            record.check_out_photo_url = event.photo_url[:500]
        _fence, record.check_out_inside_fence = self._fence_verdict(
            event.latitude, event.longitude
        )
        self._evaluate_early_exit(record)
        self._sync_live_flag(record.employee_id, checked_in=False)
        # An approved+mirrored row keeps the HR check-out current.
        if record.status == "approved" and record.attendance_id:
            self.mirror_to_hr(record)

    # ------------------------------------------------------------- verdicts

    def _fence_verdict(self, latitude, longitude):
        """(matched_fence, inside?) against active work fences; (None, None) if none exist."""
        if latitude is None or longitude is None:
            return None, None
        if self._fences is None:
            self._fences = list(EmployeeGeofence.objects.filter(
                is_active=True, geofence_type__in=WORK_FENCE_TYPES,
            ))
        if not self._fences:
            return None, None
        best_fence, best_distance = None, None
        for fence in self._fences:
            distance_m = haversine_km(
                latitude, longitude, fence.center_latitude, fence.center_longitude
            ) * 1000
            if best_distance is None or distance_m < best_distance:
                best_fence, best_distance = fence, distance_m
        return best_fence, best_distance <= best_fence.radius_m

    def _evaluate_late(self, record):
        threshold = self._settings.late_check_in_time
        if not (threshold and record.check_in_at):
            return
        local = timezone.localtime(record.check_in_at)
        was_late = record.is_late
        record.is_late = local.time() > threshold
        record.late_by = (
            local - local.replace(hour=threshold.hour, minute=threshold.minute,
                                  second=threshold.second, microsecond=0)
        ) if record.is_late else None
        if record.is_late and not was_late:
            self._alert(record, "late_check_in",
                        f"{record.employee} checked in late at {local:%H:%M} "
                        f"(threshold {threshold:%H:%M}).")

    def _evaluate_early_exit(self, record):
        threshold = self._settings.early_check_out_time
        if not (threshold and record.check_out_at):
            return
        local = timezone.localtime(record.check_out_at)
        was_early = record.is_early_exit
        record.is_early_exit = local.time() < threshold
        record.early_by = (
            local.replace(hour=threshold.hour, minute=threshold.minute,
                          second=threshold.second, microsecond=0) - local
        ) if record.is_early_exit else None
        if record.is_early_exit and not was_early:
            self._alert(record, "early_check_out",
                        f"{record.employee} checked out early at {local:%H:%M} "
                        f"(threshold {threshold:%H:%M}).")

    def _alert(self, record, event, message):
        if not self._settings.alerts_enabled:
            return
        TrackingLog.objects.create(
            log_type="alert", event=event, severity="warning", message=message,
            employee=record.employee, provider=record.provider,
            geofence=record.geofence,
        )

    @staticmethod
    def _sync_live_flag(employee_id, checked_in):
        EmployeeLiveLocation.objects.filter(employee_id=employee_id).update(
            is_checked_in=checked_in
        )

    # ------------------------------------------------------------- approval

    def approve(self, record, user, auto=False):
        """Approve a GPS record and mirror it into hr.Attendance."""
        record.status = "approved"
        record.approved_by = user
        record.approved_at = timezone.now()
        record.rejection_reason = ""
        self.mirror_to_hr(record)
        record.save()
        logger.info("GPS attendance %s for %s %s.", record.pk, record.employee,
                    "auto-approved" if auto else "approved")
        return record

    @staticmethod
    def reject(record, user, reason=""):
        record.status = "rejected"
        record.approved_by = user
        record.approved_at = timezone.now()
        record.rejection_reason = reason[:255]
        record.save()
        return record

    @staticmethod
    def mirror_to_hr(record):
        """Write/refresh the hr.Attendance row per the HR-safety rules above."""
        check_in_time = (
            timezone.localtime(record.check_in_at).time() if record.check_in_at else None
        )
        check_out_time = (
            timezone.localtime(record.check_out_at).time() if record.check_out_at else None
        )
        attendance, created = Attendance.objects.get_or_create(
            employee=record.employee, date=record.date,
            defaults={
                "check_in_time": check_in_time,
                "check_out_time": check_out_time,
                "status": "Present",
            },
        )
        if not created:
            if attendance.status == "On Leave":
                record.attendance = attendance
                record.save(update_fields=["attendance", "updated_at"])
                return attendance
            update_fields = []
            if attendance.check_in_time is None and check_in_time:
                attendance.check_in_time = check_in_time
                update_fields.append("check_in_time")
            if check_out_time and attendance.check_out_time != check_out_time:
                attendance.check_out_time = check_out_time
                update_fields.append("check_out_time")
            if attendance.status == "Absent":
                attendance.status = "Present"
                update_fields.append("status")
            if update_fields:
                attendance.save(update_fields=update_fields)
        record.attendance = attendance
        record.save(update_fields=["attendance", "updated_at"])
        return attendance
