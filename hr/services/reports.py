"""Query helpers behind HR > Reports.

Read-only. Nothing here writes, and nothing here recomputes a figure that
already has an owner elsewhere: leave balances come from
``hr.services.leave_balance``, and payroll figures are read off the stored
``Payroll`` rows rather than re-derived, so a report can never disagree
with what payroll actually paid.
"""
from calendar import monthrange
from datetime import date
from decimal import Decimal

from django.db.models import Q

from hr.models import (
    Attendance,
    Employee,
    EmployeeLeave,
    LeaveSelectedDate,
    Payroll,
)

ZERO = Decimal("0")

#: What each attendance status is worth as a day worked. Mirrors what
#: payroll counts (see EmployeePayrollDashboardView.generate_payroll) so
#: the register's totals and the payslip's days cannot drift apart.
STATUS_DAY_VALUE = {
    "Present": Decimal("1"),
    "First Half": Decimal("0.5"),
    "Second Half": Decimal("0.5"),
    "Half Day": Decimal("0.5"),
}

#: Short labels for the register grid — a month of full words is unreadable.
STATUS_SHORT = {
    "Present": "P",
    "Absent": "A",
    "On Leave": "L",
    "Half Day": "H",
    "First Half": "F",
    "Second Half": "S",
}


def month_days(year, month):
    """Every date in the month, with whether it is a working weekday.

    Payroll skips Saturday and Sunday outright, so the register marks them
    rather than showing them as days somebody failed to turn up for.
    """
    _, last = monthrange(year, month)
    out = []
    for day in range(1, last + 1):
        current = date(year, month, day)
        out.append({"date": current, "day": day,
                    "is_weekend": current.weekday() >= 5})
    return out


def active_employees(include_relieved=False):
    qs = Employee.objects.select_related(
        "designation", "department", "shift", "warehouse")
    if not include_relieved:
        qs = qs.exclude(relieve=True)
    return qs.order_by("full_name")


def attendance_register(year, month, employees):
    """Employee x day grid for a month, plus per-employee totals.

    ``working_minutes`` and ``ot_minutes`` are summed here because nothing
    else in the app surfaces them — attendance records them on every row
    and they have never been visible anywhere.
    """
    days = month_days(year, month)
    first = date(year, month, 1)
    last = date(year, month, monthrange(year, month)[1])

    by_employee = {}
    for row in (Attendance.objects
                .filter(employee__in=employees, date__range=(first, last))
                .only("employee_id", "date", "status",
                      "working_minutes", "ot_minutes")):
        by_employee.setdefault(row.employee_id, {})[row.date] = row

    # Approved leave, so a day off that was actually granted reads as leave
    # rather than as an absence nobody explained.
    leave_dates = {}
    for row in (LeaveSelectedDate.objects
                .filter(leave_request__employee__in=employees,
                        leave_request__status="Approved",
                        date__range=(first, last))
                .select_related("leave_request")):
        leave_dates.setdefault(
            row.leave_request.employee_id, set()).add(row.date)

    rows = []
    for employee in employees:
        marks = by_employee.get(employee.id, {})
        on_leave = leave_dates.get(employee.id, set())
        cells, present, leave_days = [], ZERO, ZERO
        worked_minutes = ot_minutes = 0

        for slot in days:
            record = marks.get(slot["date"])
            if record:
                code = STATUS_SHORT.get(record.status, "-")
                present += STATUS_DAY_VALUE.get(record.status, ZERO)
                worked_minutes += record.working_minutes or 0
                ot_minutes += record.ot_minutes or 0
                label = record.status
            elif slot["date"] in on_leave:
                code, label = "L", "On Leave"
                leave_days += Decimal("1")
            elif slot["is_weekend"]:
                code, label = "", "Weekend"
            else:
                code, label = "", "Not marked"
            cells.append({"code": code, "label": label,
                          "is_weekend": slot["is_weekend"]})

        rows.append({
            "employee": employee,
            "cells": cells,
            "present_days": present,
            "leave_days": leave_days,
            "worked_hours": round(worked_minutes / 60, 1),
            "ot_hours": round(ot_minutes / 60, 1),
        })
    return days, rows


def leave_register(from_date, to_date, employees, status=""):
    """Leave requests touching the window, one row per request.

    A request is included when any of its selected dates fall inside the
    window — a request spanning the month boundary belongs to both months
    it touches, not only the one it started in.
    """
    qs = (EmployeeLeave.objects
          .filter(employee__in=employees)
          .select_related("employee", "leave_category")
          .prefetch_related("selected_dates"))
    if status:
        qs = qs.filter(status=status)
    if from_date:
        qs = qs.filter(selected_dates__date__gte=from_date)
    if to_date:
        qs = qs.filter(selected_dates__date__lte=to_date)

    rows = []
    for request in qs.distinct().order_by("-created_date", "-id"):
        dates = sorted(d.date for d in request.selected_dates.all()
                       if (not from_date or d.date >= from_date)
                       and (not to_date or d.date <= to_date))
        if not dates:
            continue
        category = request.leave_category
        # Exactly the rule payroll applies: approved, and either paid or
        # from before leave types existed. Anything else is unpaid time.
        counts_paid = (request.status == "Approved"
                       and (category is None or category.is_paid))
        rows.append({
            "request": request,
            "employee": request.employee,
            "category": category.name if category else "—",
            "duration": request.leave_type or "—",
            "dates": dates,
            "day_count": len(dates),
            "status": request.status,
            "reason": request.reason or "",
            "counts_paid": counts_paid,
        })
    return rows


def payroll_register(year, month, employees):
    """Stored Payroll rows for a month, with their advance recoveries."""
    rows = []
    for payroll in (Payroll.objects
                    .filter(year=year, month=month, employee__in=employees)
                    .select_related("employee")
                    .prefetch_related("advance_recoveries__advance")
                    .order_by("employee__full_name")):
        recoveries = list(payroll.advance_recoveries.all())
        rows.append({
            "payroll": payroll,
            "employee": payroll.employee,
            "days": payroll.total_working_days,
            "gross": payroll.gross_salary or ZERO,
            "payable": payroll.payable_salary or ZERO,
            "deductions": payroll.deductions or ZERO,
            "net": payroll.net_salary or ZERO,
            "recoveries": [
                {"advance_no": r.advance.advance_no, "amount": r.amount}
                for r in recoveries
            ],
            "recovered": sum((r.amount or ZERO for r in recoveries), ZERO),
        })
    return rows


def sum_rows(rows, *keys):
    """Column totals for a report's footer."""
    return {key: sum((Decimal(str(row.get(key) or 0)) for row in rows), ZERO)
            for key in keys}
