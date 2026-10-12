"""Template context for the navbar's check in/out status badge.

Mirrors alerthub.context_processors.alert_preferences: rendered into every
page via the navbar, so it must stay cheap, never run for an anonymous
request, and never be the reason a page fails to render.
"""
from __future__ import annotations


def self_attendance_status(request):
    """Expose the signed-in employee's today-status as ``nav_attendance``.

    None for anyone without a linked Employee record (most web-only users),
    so the navbar badge only shows for people who actually have an
    attendance record to show.
    """
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return {}

    employee = getattr(user, "employee", None)
    if employee is None:
        return {}

    try:
        from django.utils import timezone

        from tracking.models import EmployeeGpsAttendance

        today = timezone.localdate()
        record = EmployeeGpsAttendance.objects.filter(employee=employee, date=today).first()
        # A prior day with no checkout blocks today's check-in (see
        # hr.views._self_attendance_punch) — the badge needs to know so it
        # can point at the problem instead of just refusing the click.
        open_prior_day = (EmployeeGpsAttendance.objects
                          .filter(employee=employee, check_in_at__isnull=False,
                                  check_out_at__isnull=True)
                          .exclude(date=today)
                          .only("date")
                          .order_by("-date")
                          .first())

        nav_status = None
        if record:
            from hr.views import _self_attendance_row
            nav_status = _self_attendance_row(record, today, employee)

        return {"nav_attendance": record, "nav_open_prior_day": open_prior_day, "nav_status": nav_status}
    except Exception:
        return {}
