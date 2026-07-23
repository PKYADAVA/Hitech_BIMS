"""Seed HR attendance demo data — Departments, Shifts, assign them to existing
employees, and create today's Attendance for a realistic Present/Absent/Leave
mix so the Daily/Mark Attendance pages show data. Idempotent — safe to re-run.

  python manage.py seed_attendance
"""
from datetime import time

from django.core.management.base import BaseCommand
from django.utils import timezone

from hr.models import Attendance, Department, Employee, Shift


DEPARTMENTS = [
    "Broiler Production", "Feed Store", "Transport", "Accounts",
    "Hatchery", "Maintenance", "Housekeeping", "Dispatch",
]
SHIFTS = [
    ("General", time(8, 30), time(17, 30)),
    ("Morning", time(7, 0), time(15, 0)),
]
# (status, in, out, source, remarks) cycled across employees — interleaved so
# even a handful of employees show a Present/Absent/Leave/Half-day mix.
PATTERN = [
    ("Present", time(8, 32), time(17, 41), "Biometric", ""),
    ("Absent", None, None, "Manual", "Absent"),
    ("On Leave", None, None, "Manual", "Casual Leave"),
    ("Half Day", time(8, 40), time(12, 45), "Manual", "Half day work"),
    ("Present", time(8, 45), time(17, 36), "Biometric", ""),
    ("Present", time(7, 5), time(15, 2), "Mobile App", ""),
    ("On Leave", None, None, "Manual", "Sick Leave"),
    ("Present", time(8, 35), time(17, 28), "Biometric", ""),
]


def _mins(a, b):
    if not a or not b:
        return 0
    return (b.hour * 60 + b.minute) - (a.hour * 60 + a.minute)


class Command(BaseCommand):
    help = "Seed HR attendance demo data (departments, shifts, today's attendance)."

    def handle(self, *args, **options):
        depts = [Department.objects.get_or_create(name=n)[0] for n in DEPARTMENTS]
        shifts = [Shift.objects.get_or_create(
            name=n, defaults={"start_time": s, "end_time": e})[0] for n, s, e in SHIFTS]

        employees = list(Employee.objects.filter(relieve=False).order_by("id"))
        if not employees:
            self.stdout.write(self.style.WARNING("No active employees — create some first."))
            return

        today = timezone.localdate()
        for i, emp in enumerate(employees):
            # assign a department/shift if missing
            changed = []
            if not emp.department_id:
                emp.department = depts[i % len(depts)]
                changed.append("department")
            if not emp.shift_id:
                emp.shift = shifts[i % len(shifts)]
                changed.append("shift")
            if changed:
                emp.save(update_fields=changed)

            status, cin, cout, src, rem = PATTERN[i % len(PATTERN)]
            Attendance.objects.update_or_create(
                employee=emp, date=today,
                defaults={
                    "status": status, "check_in_time": cin, "check_out_time": cout,
                    "working_minutes": _mins(cin, cout), "shift": emp.shift,
                    "attendance_source": src, "remarks": rem,
                },
            )

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(depts)} departments, {len(shifts)} shifts and today's "
            f"attendance for {len(employees)} employees ({today})."))
