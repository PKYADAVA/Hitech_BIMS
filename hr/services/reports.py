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


# ---------------------------------------------------------------------------
# Excel export
#
# Same shape as purchase's _ledger_excel: company name, report title, the
# criteria line the screen shows, a blank row, then a styled header row, the
# data, and a totals row. Numbers go in as numbers — a workbook whose figures
# are text cannot be summed, which is most of why anyone exports one.
# ---------------------------------------------------------------------------
XLSX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
HEADER_FILL = "1B3A6B"
WEEKEND_FILL = "EEF1F5"


def _num(value):
    """A number openpyxl will store as one, or the value unchanged."""
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def _start_sheet(title, company, report_title, criteria, headers):
    """A workbook opened at a styled header row, ready for data."""
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title[:31]          # Excel's own limit on a sheet name
    ws.append([company.name if company else ""])
    ws.append([report_title])
    ws.append([criteria or ""])
    ws.append([])
    ws.append(headers)
    for column in range(1, len(headers) + 1):
        cell = ws.cell(ws.max_row, column)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=HEADER_FILL)
        cell.alignment = Alignment(horizontal="center")
    return wb, ws


def _finish(wb, ws, headers, filename, widths=None):
    from django.http import HttpResponse
    from openpyxl.utils import get_column_letter

    for index in range(1, len(headers) + 1):
        letter = get_column_letter(index)
        ws.column_dimensions[letter].width = (
            widths.get(index, 15) if widths else 15)

    response = HttpResponse(content_type=XLSX_CONTENT_TYPE)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    wb.save(response)
    return response


def attendance_excel(company, criteria, month_name, days, rows, totals):
    from openpyxl.styles import PatternFill

    headers = (["Employee", "Code"]
               + [str(slot["date"].day) for slot in days]
               + ["Present Days", "Leave Days", "Worked Hours", "OT Hours"])
    wb, ws = _start_sheet("Attendance Register", company,
                          f"Attendance Register - {month_name}",
                          criteria, headers)
    header_row = ws.max_row

    for row in rows:
        employee = row["employee"]
        ws.append([employee.full_name or "", employee.employee_id or ""]
                  + [cell["code"] for cell in row["cells"]]
                  + [_num(row["present_days"]), _num(row["leave_days"]),
                     _num(row["worked_hours"]), _num(row["ot_hours"])])

    ws.append(["Total", ""] + [""] * len(days)
              + [_num(totals["present"]), _num(totals["leave"]),
                 _num(totals["worked_hours"]), _num(totals["ot_hours"])])

    # Shade the weekend columns, header included, so the grid reads the
    # same way it does on screen rather than looking like absences.
    shade = PatternFill("solid", fgColor=WEEKEND_FILL)
    for index, slot in enumerate(days):
        if not slot["is_weekend"]:
            continue
        column = index + 3
        for row_index in range(header_row, ws.max_row + 1):
            ws.cell(row_index, column).fill = shade

    widths = {1: 26, 2: 10}
    for column in range(3, 3 + len(days)):
        widths[column] = 4
    return _finish(wb, ws, headers, "attendance_register.xlsx", widths)


def leave_excel(company, criteria, rows, balance_rows, balance_employee,
                balance_year):
    headers = ["Employee", "Code", "Category", "Duration", "Dates", "Days",
               "Status", "Counts as Paid", "Reason"]
    wb, ws = _start_sheet("Leave Register", company, "Leave Register",
                          criteria, headers)

    for row in rows:
        employee = row["employee"]
        ws.append([
            employee.full_name or "", employee.employee_id or "",
            row["category"], row["duration"],
            ", ".join(d.strftime("%d-%m-%Y") for d in row["dates"]),
            _num(row["day_count"]), row["status"],
            "Yes" if row["counts_paid"] else "No",
            row["reason"],
        ])
    ws.append(["Total", "", "", "", "",
               _num(sum(r["day_count"] for r in rows)), "", "", ""])

    # The balance only exists when the report is down to one person, which
    # is the only scope a balance means anything in.
    if balance_rows and balance_employee:
        ws.append([])
        ws.append([f"Leave balance - {balance_employee.full_name} "
                   f"({balance_year})"])
        ws.append(["Type", "Entitled", "Taken", "Balance"])
        for balance in balance_rows:
            ws.append([balance["name"], _num(balance["entitled"]),
                       _num(balance["taken"]), _num(balance["balance"])])

    return _finish(wb, ws, headers, "leave_register.xlsx",
                   {1: 26, 3: 18, 4: 14, 5: 34, 9: 40})


def payroll_excel(company, criteria, month_name, rows, totals):
    headers = ["Employee", "Code", "Days", "Gross", "Payable", "Deductions",
               "Net", "Advance Recovered", "Recovered Against"]
    wb, ws = _start_sheet("Payroll Register", company,
                          f"Payroll Register - {month_name}",
                          criteria, headers)

    for row in rows:
        employee = row["employee"]
        # One cell listing every advance this month took from, rather than
        # a row per recovery — the register is one line per payroll.
        against = "; ".join(f"{rec['advance_no']} - {rec['amount']}"
                            for rec in row["recoveries"])
        ws.append([
            employee.full_name or "", employee.employee_id or "",
            _num(row["days"]), _num(row["gross"]), _num(row["payable"]),
            _num(row["deductions"]), _num(row["net"]),
            _num(row["recovered"]), against,
        ])

    ws.append(["Total", "", _num(totals.get("days")),
               _num(totals.get("gross")), _num(totals.get("payable")),
               _num(totals.get("deductions")), _num(totals.get("net")),
               _num(totals.get("recovered")), ""])

    return _finish(wb, ws, headers, "payroll_register.xlsx", {1: 26, 9: 38})


def employee_excel(company, criteria, employees, active_count,
                   relieved_count, total_salary):
    headers = ["Code", "Name", "Designation", "Department", "Shift",
               "Branch", "Date of Joining", "Salary", "Salary Type", "Status"]
    wb, ws = _start_sheet("Employee Master", company, "Employee Master",
                          criteria, headers)

    for employee in employees:
        ws.append([
            employee.employee_id or "",
            employee.full_name or "",
            employee.designation.title if employee.designation_id else "",
            employee.department.name if employee.department_id else "",
            employee.shift.name if employee.shift_id else "",
            employee.warehouse.name if employee.warehouse_id else "",
            employee.date_of_joining.strftime("%d-%m-%Y")
            if employee.date_of_joining else "",
            _num(employee.salary), employee.salary_type or "",
            "Relieved" if employee.relieve else "Active",
        ])

    ws.append([])
    ws.append([f"Active: {active_count}", f"Relieved: {relieved_count}",
               "", "", "", "", "Total Salary", _num(total_salary)])

    return _finish(wb, ws, headers, "employee_master.xlsx",
                   {1: 10, 2: 26, 3: 20, 4: 18, 5: 14, 6: 20, 7: 16})
