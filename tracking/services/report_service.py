# pylint: disable=no-member
"""Report builders for the Employee Tracking module.

Every report reads exclusively from the pre-aggregated tracking tables
(routes, GPS attendance, visits, logs) — never from raw pings — so report
latency is independent of location-history volume.

All builders return the same shape so one page template and one CSV writer
serve every report::

    {"columns": [{"key": ..., "label": ...}, ...],
     "rows": [dict, ...],
     "summary": {label: value, ...}}
"""

from datetime import timedelta

from django.db.models import Avg, Count, Max, Q, Sum

from ..models import (
    EmployeeCustomerVisit,
    EmployeeGpsAttendance,
    EmployeeRoute,
    TrackingLog,
)

#: Alert events surfaced by the GPS-exceptions report.
EXCEPTION_EVENTS = (
    "late_check_in", "early_check_out", "employee_offline", "gps_disabled",
    "no_internet", "geofence_exit", "outside_working_area", "missed_visit",
)


def _hm(duration):
    """timedelta → 'Hh Mm' (blank for None)."""
    if not duration:
        return ""
    minutes = int(duration.total_seconds() // 60)
    return f"{minutes // 60}h {minutes % 60:02d}m"


def _hours(duration):
    return round(duration.total_seconds() / 3600, 2) if duration else 0.0


def _employee_cols():
    return [{"key": "employee", "label": "Employee"},
            {"key": "employee_code", "label": "ID"},
            {"key": "warehouse", "label": "Branch"}]


def _employee_cells(employee):
    return {
        "employee": employee.full_name or "",
        "employee_code": employee.employee_id,
        "warehouse": employee.warehouse.name if employee.warehouse else "",
    }


def _scoped(queryset, employee_id, warehouse_id, employee_field="employee"):
    if employee_id:
        queryset = queryset.filter(**{f"{employee_field}_id": employee_id})
    if warehouse_id:
        queryset = queryset.filter(**{f"{employee_field}__warehouse_id": warehouse_id})
    return queryset


# ------------------------------------------------------------------ reports

def daily_tracking(start, end, employee_id=None, warehouse_id=None):
    """Route summary per employee per day: distance, times, stops, visits."""
    routes = _scoped(
        EmployeeRoute.objects.filter(date__range=(start, end))
        .select_related("employee", "employee__warehouse")
        .order_by("employee__full_name", "date"),
        employee_id, warehouse_id,
    )
    visits = {
        (item["employee_id"], item["visit_date"]): item["n"]
        for item in _scoped(
            EmployeeCustomerVisit.objects.filter(visit_date__range=(start, end)),
            employee_id, warehouse_id)
        .values("employee_id", "visit_date").annotate(n=Count("id"))
    }
    rows = []
    for route in routes:
        rows.append({
            **_employee_cells(route.employee),
            "date": route.date.isoformat(),
            "distance_km": float(route.total_distance_km),
            "travel_time": _hm(route.travel_time),
            "idle_time": _hm(route.idle_time),
            "stops": route.stops_count,
            "avg_speed": route.average_speed_kmh or "",
            "max_speed": route.max_speed_kmh or "",
            "first_seen": route.first_point_at.isoformat() if route.first_point_at else "",
            "last_seen": route.last_point_at.isoformat() if route.last_point_at else "",
            "visits": visits.get((route.employee_id, route.date), 0),
        })
    columns = _employee_cols() + [
        {"key": "date", "label": "Date"},
        {"key": "distance_km", "label": "Distance (km)"},
        {"key": "travel_time", "label": "Travel Time"},
        {"key": "idle_time", "label": "Idle Time"},
        {"key": "stops", "label": "Stops"},
        {"key": "avg_speed", "label": "Avg km/h"},
        {"key": "max_speed", "label": "Max km/h"},
        {"key": "first_seen", "label": "First Seen"},
        {"key": "last_seen", "label": "Last Seen"},
        {"key": "visits", "label": "Visits"},
    ]
    summary = {
        "Total distance (km)": round(sum(r["distance_km"] for r in rows), 1),
        "Days tracked": len(rows),
        "Total visits": sum(r["visits"] for r in rows),
    }
    return {"columns": columns, "rows": rows, "summary": summary}


def attendance_gps(start, end, employee_id=None, warehouse_id=None):
    """GPS attendance detail: in/out, late, early exit, fence verdicts."""
    records = _scoped(
        EmployeeGpsAttendance.objects.filter(date__range=(start, end))
        .select_related("employee", "employee__warehouse", "geofence")
        .order_by("employee__full_name", "date"),
        employee_id, warehouse_id,
    )
    rows = []
    for record in records:
        rows.append({
            **_employee_cells(record.employee),
            "date": record.date.isoformat(),
            "check_in": record.check_in_at.isoformat() if record.check_in_at else "",
            "check_out": record.check_out_at.isoformat() if record.check_out_at else "",
            "late": "Yes" if record.is_late else "",
            "late_by": _hm(record.late_by),
            "early_exit": "Yes" if record.is_early_exit else "",
            "fence": record.geofence.name if record.geofence else "",
            "inside_fence": {True: "Yes", False: "No", None: ""}[record.check_in_inside_fence],
            "status": record.status,
        })
    columns = _employee_cols() + [
        {"key": "date", "label": "Date"},
        {"key": "check_in", "label": "Check In"},
        {"key": "check_out", "label": "Check Out"},
        {"key": "late", "label": "Late"},
        {"key": "late_by", "label": "Late By"},
        {"key": "early_exit", "label": "Early Exit"},
        {"key": "fence", "label": "Geofence"},
        {"key": "inside_fence", "label": "Inside Fence"},
        {"key": "status", "label": "Approval"},
    ]
    summary = {
        "Records": len(rows),
        "Late arrivals": sum(1 for r in rows if r["late"]),
        "Early exits": sum(1 for r in rows if r["early_exit"]),
        "Outside fence": sum(1 for r in rows if r["inside_fence"] == "No"),
    }
    return {"columns": columns, "rows": rows, "summary": summary}


def travel_distance(start, end, employee_id=None, warehouse_id=None):
    """Aggregate distance per employee over the range."""
    aggregates = (
        _scoped(EmployeeRoute.objects.filter(date__range=(start, end))
                .select_related("employee", "employee__warehouse"),
                employee_id, warehouse_id)
        .values("employee_id", "employee__full_name", "employee__employee_id",
                "employee__warehouse__name")
        .annotate(total_km=Sum("total_distance_km"), days=Count("id"),
                  avg_km=Avg("total_distance_km"), max_km=Max("total_distance_km"))
        .order_by("-total_km")
    )
    rows = [{
        "employee": item["employee__full_name"] or "",
        "employee_code": item["employee__employee_id"],
        "warehouse": item["employee__warehouse__name"] or "",
        "days": item["days"],
        "total_km": round(float(item["total_km"] or 0), 1),
        "avg_km": round(float(item["avg_km"] or 0), 1),
        "max_km": round(float(item["max_km"] or 0), 1),
    } for item in aggregates]
    columns = _employee_cols() + [
        {"key": "days", "label": "Days Tracked"},
        {"key": "total_km", "label": "Total (km)"},
        {"key": "avg_km", "label": "Avg / Day (km)"},
        {"key": "max_km", "label": "Max Day (km)"},
    ]
    summary = {"Total distance (km)": round(sum(r["total_km"] for r in rows), 1)}
    return {"columns": columns, "rows": rows, "summary": summary}


def working_hours(start, end, employee_id=None, warehouse_id=None):
    """Hours between GPS check-in and check-out, per employee per day."""
    records = _scoped(
        EmployeeGpsAttendance.objects.filter(
            date__range=(start, end),
            check_in_at__isnull=False, check_out_at__isnull=False)
        .select_related("employee", "employee__warehouse")
        .order_by("employee__full_name", "date"),
        employee_id, warehouse_id,
    )
    rows = []
    for record in records:
        worked = record.check_out_at - record.check_in_at
        rows.append({
            **_employee_cells(record.employee),
            "date": record.date.isoformat(),
            "check_in": record.check_in_at.isoformat(),
            "check_out": record.check_out_at.isoformat(),
            "hours": _hours(worked),
            "worked": _hm(worked),
        })
    columns = _employee_cols() + [
        {"key": "date", "label": "Date"},
        {"key": "check_in", "label": "Check In"},
        {"key": "check_out", "label": "Check Out"},
        {"key": "worked", "label": "Worked"},
        {"key": "hours", "label": "Hours"},
    ]
    summary = {
        "Total hours": round(sum(r["hours"] for r in rows), 1),
        "Days": len(rows),
        "Avg hours/day": round(sum(r["hours"] for r in rows) / len(rows), 2) if rows else 0,
    }
    return {"columns": columns, "rows": rows, "summary": summary}


def customer_visits(start, end, employee_id=None, warehouse_id=None):
    """Visit performance per employee: counts, duration, coverage."""
    visits = _scoped(
        EmployeeCustomerVisit.objects.filter(visit_date__range=(start, end)),
        employee_id, warehouse_id,
    )
    aggregates = (
        visits.values("employee_id", "employee__full_name",
                      "employee__employee_id", "employee__warehouse__name")
        .annotate(
            total=Count("id"),
            completed=Count("id", filter=Q(status="completed")),
            customers=Count("customer_id", distinct=True,
                            filter=Q(customer__isnull=False)),
            avg_duration=Avg("duration"),
            total_duration=Sum("duration"),
        )
        .order_by("-total")
    )
    rows = [{
        "employee": item["employee__full_name"] or "",
        "employee_code": item["employee__employee_id"],
        "warehouse": item["employee__warehouse__name"] or "",
        "visits": item["total"],
        "completed": item["completed"],
        "customers": item["customers"],
        "avg_duration": _hm(item["avg_duration"]),
        "total_duration": _hm(item["total_duration"]),
    } for item in aggregates]
    columns = _employee_cols() + [
        {"key": "visits", "label": "Visits"},
        {"key": "completed", "label": "Completed"},
        {"key": "customers", "label": "Unique Customers"},
        {"key": "avg_duration", "label": "Avg Duration"},
        {"key": "total_duration", "label": "Total Duration"},
    ]
    summary = {"Total visits": sum(r["visits"] for r in rows)}
    return {"columns": columns, "rows": rows, "summary": summary}


def idle_time(start, end, employee_id=None, warehouse_id=None):
    """Idle vs travel split per employee."""
    aggregates = (
        _scoped(EmployeeRoute.objects.filter(date__range=(start, end)),
                employee_id, warehouse_id)
        .values("employee_id", "employee__full_name", "employee__employee_id",
                "employee__warehouse__name")
        .annotate(idle=Sum("idle_time"), travel=Sum("travel_time"), days=Count("id"))
        .order_by("employee__full_name")
    )
    rows = []
    for item in aggregates:
        idle_hours, travel_hours = _hours(item["idle"]), _hours(item["travel"])
        total = idle_hours + travel_hours
        rows.append({
            "employee": item["employee__full_name"] or "",
            "employee_code": item["employee__employee_id"],
            "warehouse": item["employee__warehouse__name"] or "",
            "days": item["days"],
            "idle": _hm(item["idle"]),
            "travel": _hm(item["travel"]),
            "idle_pct": round(idle_hours / total * 100, 1) if total else 0,
        })
    columns = _employee_cols() + [
        {"key": "days", "label": "Days"},
        {"key": "travel", "label": "Travel Time"},
        {"key": "idle", "label": "Idle Time"},
        {"key": "idle_pct", "label": "Idle %"},
    ]
    return {"columns": columns, "rows": rows, "summary": {"Employees": len(rows)}}


def exceptions(start, end, employee_id=None, warehouse_id=None):
    """GPS exceptions: late, early, offline, GPS off, fence and visit alerts."""
    logs = (
        TrackingLog.objects.filter(
            log_type="alert", event__in=EXCEPTION_EVENTS,
            created_at__date__range=(start, end))
        .select_related("employee", "employee__warehouse")
        .order_by("-created_at")
    )
    if employee_id:
        logs = logs.filter(employee_id=employee_id)
    if warehouse_id:
        logs = logs.filter(employee__warehouse_id=warehouse_id)

    rows = [{
        "when": log.created_at.isoformat(),
        "employee": log.employee.full_name if log.employee else "",
        "employee_code": log.employee.employee_id if log.employee else "",
        "warehouse": (log.employee.warehouse.name
                      if log.employee and log.employee.warehouse else ""),
        "event": log.get_event_display(),
        "severity": log.severity,
        "message": log.message,
    } for log in logs[:2000]]
    columns = [
        {"key": "when", "label": "When"},
        {"key": "employee", "label": "Employee"},
        {"key": "employee_code", "label": "ID"},
        {"key": "warehouse", "label": "Branch"},
        {"key": "event", "label": "Exception"},
        {"key": "severity", "label": "Severity"},
        {"key": "message", "label": "Detail"},
    ]
    by_event = {}
    for row in rows:
        by_event[row["event"]] = by_event.get(row["event"], 0) + 1
    return {"columns": columns, "rows": rows, "summary": by_event or {"Exceptions": 0}}


def monthly_summary(start, end, employee_id=None, warehouse_id=None):
    """One row per employee for the range: presence, hours, distance, visits."""
    routes = (
        _scoped(EmployeeRoute.objects.filter(date__range=(start, end)),
                employee_id, warehouse_id)
        .values("employee_id", "employee__full_name", "employee__employee_id",
                "employee__warehouse__name")
        .annotate(days=Count("id"), km=Sum("total_distance_km"))
    )
    attendance = {
        item["employee_id"]: item for item in
        _scoped(EmployeeGpsAttendance.objects.filter(date__range=(start, end)),
                employee_id, warehouse_id)
        .values("employee_id")
        .annotate(
            present=Count("id", filter=Q(check_in_at__isnull=False)),
            late=Count("id", filter=Q(is_late=True)),
            early=Count("id", filter=Q(is_early_exit=True)),
            pending=Count("id", filter=Q(status="pending")),
        )
    }
    visit_counts = dict(
        _scoped(EmployeeCustomerVisit.objects.filter(visit_date__range=(start, end)),
                employee_id, warehouse_id)
        .values("employee_id").annotate(n=Count("id"))
        .values_list("employee_id", "n")
    )
    rows = []
    for item in routes:
        att = attendance.get(item["employee_id"], {})
        rows.append({
            "employee": item["employee__full_name"] or "",
            "employee_code": item["employee__employee_id"],
            "warehouse": item["employee__warehouse__name"] or "",
            "days_tracked": item["days"],
            "present_days": att.get("present", 0),
            "late_days": att.get("late", 0),
            "early_exits": att.get("early", 0),
            "pending_approvals": att.get("pending", 0),
            "distance_km": round(float(item["km"] or 0), 1),
            "visits": visit_counts.get(item["employee_id"], 0),
        })
    rows.sort(key=lambda row: row["employee"])
    columns = _employee_cols() + [
        {"key": "days_tracked", "label": "Days Tracked"},
        {"key": "present_days", "label": "GPS Present"},
        {"key": "late_days", "label": "Late Days"},
        {"key": "early_exits", "label": "Early Exits"},
        {"key": "pending_approvals", "label": "Pending Approvals"},
        {"key": "distance_km", "label": "Distance (km)"},
        {"key": "visits", "label": "Visits"},
    ]
    summary = {
        "Employees": len(rows),
        "Total distance (km)": round(sum(r["distance_km"] for r in rows), 1),
        "Total visits": sum(r["visits"] for r in rows),
    }
    return {"columns": columns, "rows": rows, "summary": summary}


#: Report registry: key -> (label, builder). Drives the API and the UI select.
REPORTS = {
    "daily_tracking": ("Daily Tracking / Route Summary", daily_tracking),
    "attendance_gps": ("Attendance GPS", attendance_gps),
    "travel_distance": ("Travel Distance", travel_distance),
    "working_hours": ("Working Hours", working_hours),
    "customer_visits": ("Customer Visits / Visit Duration", customer_visits),
    "idle_time": ("Idle Time", idle_time),
    "exceptions": ("Late / Missed / GPS Exceptions", exceptions),
    "monthly_summary": ("Monthly Summary", monthly_summary),
}


def build(report, start, end, employee_id=None, warehouse_id=None):
    """Run one registered report; raises KeyError for unknown keys."""
    _label, builder = REPORTS[report]
    return builder(start, end, employee_id=employee_id, warehouse_id=warehouse_id)
