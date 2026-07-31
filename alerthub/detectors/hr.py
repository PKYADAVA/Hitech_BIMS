"""HR detectors — attendance gaps, pending leave and payroll timing.

These alerts carry no branch: ``Employee.branch_name`` is free text rather than
a foreign key to ``broiler.Branch``, so there is nothing to scope against
without guessing at a string match. They reach whoever the rule's groups name,
which for HR is the right audience anyway.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from alerthub.constants import compare
from alerthub.engine import raise_alert
from alerthub.measures import safe_url
from alerthub.scoping import rule_applies_to

from . import detector


@detector("hr.attendance_missing")
def attendance_missing(rule):
    """Employees with no attendance row for a recent working day.

    One alert per day, listing the employees, rather than one per employee: a
    missing muster is a single administrative task, and fanning it out per head
    would put fifty identical notifications in the same inbox.

    **Known limitation.** The employee master has no resignation or active flag,
    so anyone who has left still counts as expected. The alert says so in its
    metadata rather than quietly overstating the gap.
    """
    from hr.models import Attendance, Employee

    today = timezone.localdate()
    target = today - timedelta(days=int(rule.threshold or 1))

    expected = Employee.objects.filter(
        date_of_joining__isnull=False, date_of_joining__lte=target
    )
    total = expected.count()
    if not total:
        return

    marked = set(
        Attendance.objects.filter(date=target).values_list("employee_id", flat=True)
    )
    missing = [e for e in expected if e.pk not in marked]
    if not missing:
        return
    if not rule_applies_to(rule):
        return

    names = ", ".join((e.full_name or f"#{e.employee_id}") for e in missing[:8])
    if len(missing) > 8:
        names += f" and {len(missing) - 8} more"

    raise_alert(
        rule,
        title="Attendance Missing",
        message=(
            f"{len(missing)} of {total} employees have no attendance recorded for "
            f"{target:%d %b %Y}: {names}."
        ),
        dedupe_key=f"{rule.pk}:attendance_missing:{target}",
        measured_value=Decimal(len(missing)),
        threshold_value=rule.threshold,
        object_label="hr.Attendance",
        object_display=f"Muster {target:%d %b %Y}",
        action_url=safe_url("daily_attendance") or safe_url("attendance"),
        metadata={
            "date": str(target),
            "missing": len(missing),
            "expected": total,
            "caveat": "The employee master has no resignation flag, so former "
                      "staff are still counted as expected.",
        },
    )


@detector("hr.leave_approval_pending")
def leave_approval_pending(rule):
    """Leave requests still sitting at Pending."""
    from hr.models import EmployeeLeave

    today = timezone.localdate()
    rows = (
        EmployeeLeave.objects.filter(status="Pending", created_date__isnull=False)
        .select_related("employee")
    )

    for leave in rows:
        waiting = Decimal((today - leave.created_date.date()).days)
        if not compare(waiting, rule.operator, rule.threshold):
            continue
        if not rule_applies_to(rule):
            continue

        who = getattr(leave.employee, "full_name", None) or "An employee"
        raise_alert(
            rule,
            title="Leave Approval Pending",
            message=(
                f"{who}'s {leave.leave_type} leave request has been pending for "
                f"{int(waiting)} day(s) — raised "
                f"{leave.created_date.date():%d %b %Y}."
            ),
            dedupe_key=f"{rule.pk}:leave_pending:{leave.pk}",
            measured_value=waiting,
            threshold_value=rule.threshold,
            object_label="hr.EmployeeLeave",
            object_id=leave.pk,
            object_display=f"{who} · {leave.leave_type}",
            action_url=safe_url("leave_employee"),
            metadata={"reason": (leave.reason or "")[:200]},
        )


@detector("hr.salary_processing_due")
def salary_processing_due(rule):
    """A closed month with no payroll rows.

    Checked against the previous month, since payroll for the month in progress
    is not late. The threshold is the day of the month after which the previous
    month's payroll counts as overdue.
    """
    from hr.models import Employee, Payroll

    today = timezone.localdate()
    if today.day < int(rule.threshold or 1):
        return

    last_month_end = today.replace(day=1) - timedelta(days=1)
    month, year = last_month_end.month, last_month_end.year

    if Payroll.objects.filter(month=month, year=year).exists():
        return
    if not Employee.objects.exists():
        return
    if not rule_applies_to(rule):
        return

    raise_alert(
        rule,
        title="Salary Processing Due",
        message=(
            f"No payroll has been processed for {last_month_end:%B %Y}."
        ),
        dedupe_key=f"{rule.pk}:payroll_due:{year}-{month:02d}",
        measured_value=Decimal(today.day),
        threshold_value=rule.threshold,
        object_label="hr.Payroll",
        object_display=f"Payroll {last_month_end:%B %Y}",
        action_url=safe_url("payroll"),
        metadata={"month": month, "year": year},
    )
