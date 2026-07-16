# pylint: disable=no-member
"""Page views for the Employee Tracking module.

Thin render-only views: all data flows through the JSON APIs in
``tracking.api_views``, refreshed client-side. Both pages are registered in
the Web-Access matrix (``user/access.py``) under the HR module.
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from hr.models import Designation, Employee, Group
from inventory.models import Warehouse
from sales.models import Customer

from .models import TrackingProvider, TrackingSettings


@login_required(login_url="login")
def tracking_dashboard(request):
    """Live map + status tiles + employee grid."""
    settings_row = TrackingSettings.get_solo()
    return render(request, "tracking_dashboard.html", {
        "tracking_enabled": settings_row.enabled,
        "refresh_seconds": settings_row.dashboard_refresh_seconds,
        "map_provider": settings_row.map_provider,
        "warehouses": Warehouse.objects.all().order_by("name"),
        "groups": Group.objects.all().order_by("name"),
        "designations": Designation.objects.all().order_by("title"),
    })


@login_required(login_url="login")
def tracking_attendance(request):
    """GPS attendance verification: map, late/early flags, approval queue."""
    settings_row = TrackingSettings.get_solo()
    return render(request, "tracking_attendance.html", {
        "tracking_enabled": settings_row.enabled,
        "auto_approve": settings_row.attendance_auto_approve,
    })


@login_required(login_url="login")
def tracking_visits(request):
    """Customer visit register: history, follow-ups, unmatched repair."""
    settings_row = TrackingSettings.get_solo()
    employees = (
        Employee.objects.exclude(relieve=True)
        .order_by("full_name").values("id", "full_name", "employee_id")
    )
    customers = Customer.objects.order_by("name").values("id", "name")
    return render(request, "tracking_visits.html", {
        "tracking_enabled": settings_row.enabled,
        "employees": list(employees),
        "customers": list(customers),
    })


@login_required(login_url="login")
def tracking_routes(request):
    """Route history replay with the day's chronological timeline."""
    employees = (
        Employee.objects.exclude(relieve=True)
        .order_by("full_name").values("id", "full_name", "employee_id")
    )
    return render(request, "tracking_routes.html", {
        "employees": list(employees),
    })


@login_required(login_url="login")
def tracking_reports(request):
    """Report centre: selectable tabular reports with CSV export."""
    from .services.report_service import REPORTS

    employees = (
        Employee.objects.exclude(relieve=True)
        .order_by("full_name").values("id", "full_name", "employee_id")
    )
    return render(request, "tracking_reports.html", {
        "reports": [(key, label) for key, (label, _fn) in REPORTS.items()],
        "employees": list(employees),
        "warehouses": Warehouse.objects.all().order_by("name"),
    })


@login_required(login_url="login")
def tracking_geofences(request):
    """Geofence master: office/warehouse/farm/customer fences with alerts."""
    from .models import EmployeeGeofence

    settings_row = TrackingSettings.get_solo()
    customers = Customer.objects.order_by("name").values("id", "name")
    return render(request, "tracking_geofences.html", {
        "geofence_types": EmployeeGeofence.TYPE_CHOICES,
        "warehouses": Warehouse.objects.all().order_by("name"),
        "customers": list(customers),
        "default_radius": settings_row.default_geofence_radius_m,
    })


@login_required(login_url="login")
def tracking_alerts(request):
    """Alert inbox: offline, GPS off, geofence, late check-in, missed visit."""
    from .models import TrackingLog

    employees = (
        Employee.objects.exclude(relieve=True)
        .order_by("full_name").values("id", "full_name", "employee_id")
    )
    alert_events = [
        (value, label) for value, label in TrackingLog.EVENT_CHOICES
        if value in {
            "employee_offline", "gps_disabled", "no_internet", "geofence_entry",
            "geofence_exit", "outside_working_area", "late_check_in",
            "early_check_out", "missed_visit",
        }
    ]
    return render(request, "tracking_alerts.html", {
        "employees": list(employees),
        "alert_events": alert_events,
    })


@login_required(login_url="login")
def tracking_settings(request):
    """Runtime settings, provider masters, and identity mapping."""
    employees = (
        Employee.objects.exclude(relieve=True)
        .order_by("full_name")
        .values("id", "full_name", "employee_id")
    )
    return render(request, "tracking_settings.html", {
        "provider_types": TrackingProvider.PROVIDER_CHOICES,
        "employees": list(employees),
    })
