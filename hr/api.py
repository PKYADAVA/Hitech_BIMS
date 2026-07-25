"""HR domain — mobile API v1 resources.

Mirrors the web HR module. Simple master data (departments, designations,
shifts, groups) gets full CRUD via the generic form; employees carry a user
link + many fields, and leave/attendance/payroll are workflow/computed records,
so those are exposed **read-only**.

Registered under ``/api/v1/hr/…`` by :func:`register` (called from
``api/urls.py``).
"""
from __future__ import annotations

from api.viewsets import register_model

from .models import (
    Attendance,
    Department,
    Designation,
    Employee,
    EmployeeLeave,
    Group,
    LeaveSelectedDate,
    Payroll,
    Shift,
)


def register(router) -> None:
    # --- Master data (full CRUD; list also serves as picker data) -------
    register_model(router, "hr/departments", Department,
                   search_fields=["code", "name"], ordering=["name"])
    register_model(router, "hr/designations", Designation,
                   search_fields=["code", "title"], ordering=["title"])
    register_model(router, "hr/shifts", Shift,
                   search_fields=["name"], ordering=["name"])
    register_model(router, "hr/groups", Group,
                   search_fields=["name"], ordering=["name"])

    # --- Employees (read-only: user link + many fields) -----------------
    register_model(router, "hr/employees", Employee, read_only=True,
                   search_fields=["full_name", "pan_card", "aadhar_number"],
                   ordering=["full_name"])

    # --- Transactions (read-only: workflow / computed records) ----------
    register_model(router, "hr/leaves", EmployeeLeave, read_only=True,
                   search_fields=["reason", "leave_type", "status"], cursor=True)
    register_model(router, "hr/attendance", Attendance, read_only=True,
                   search_fields=["status"], cursor=True)
    register_model(router, "hr/payroll", Payroll, read_only=True, cursor=True)

    # --- Line items (read-only; shown inside their parent's detail) -----
    register_model(router, "hr/leave-dates", LeaveSelectedDate, read_only=True)
