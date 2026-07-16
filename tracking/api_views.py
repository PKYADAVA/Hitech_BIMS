# pylint: disable=no-member
"""JSON APIs for the Employee Tracking module.

All endpoints require login and are additionally guarded by the Web-Access
matrix (each url-name is registered under its owning tab in
``user/access.py``). Follows the account-app API conventions: plain Django
views, JsonResponse, explicit audit logging with acting user + client IP.

The browser only ever talks to these endpoints — never to a GPS vendor.

Routes (see tracking/urls.py):
    GET  /api/tracking/live/            dashboard tiles + live employee rows
    GET  /api/tracking/settings/        runtime settings (secrets omitted)
    POST /api/tracking/settings/        save settings
    GET  /api/tracking/providers/       provider list (secrets never returned)
    POST /api/tracking/providers/       create / update a provider
    DELETE /api/tracking/providers/     deactivate a provider (?id=)
    POST /api/tracking/providers/test/  server-side connection test
    GET  /api/tracking/mappings/        vendor directory + current mappings
    POST /api/tracking/mappings/        map / unmap one vendor identity
    POST /api/tracking/sync-now/        run a manual sync (lock-guarded)
"""

import json
import logging
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from hr.models import Employee, LeaveSelectedDate
from inventory.models import Warehouse
from sales.models import Customer

from .exceptions import TrackingConfigurationError, TrackingProviderError
from .models import (
    EmployeeCustomerVisit,
    EmployeeGeofence,
    EmployeeGpsAttendance,
    EmployeeLiveLocation,
    EmployeeProviderMapping,
    EmployeeRoute,
    SyncLock,
    TrackingLog,
    TrackingProvider,
    TrackingSettings,
)
from .providers import get_adapter
from .services.attendance_service import AttendanceIntegrationService
from .services.sync_service import DEFAULT_KINDS, SyncService

logger = logging.getLogger("tracking.api")

MAX_LIVE_ROWS = 2000

#: Provider secret fields: accepted on write, never returned on read.
_PROVIDER_SECRETS = ("password", "access_token", "api_key", "webhook_secret")
#: Plain provider fields settable straight from the request body.
_PROVIDER_FIELDS = ("name", "provider_type", "api_url", "username",
                    "webhook_url", "priority", "is_active",
                    "refresh_interval_seconds")
#: Settings fields settable from the request body.
_SETTINGS_FIELDS = (
    "enabled", "map_provider", "dashboard_refresh_seconds",
    "offline_after_minutes", "idle_after_minutes", "late_check_in_time",
    "early_check_out_time", "working_start", "working_end",
    "default_geofence_radius_m", "distance_unit", "history_retention_days",
    "alerts_enabled", "sms_alerts_enabled",
    "attendance_sync_enabled", "attendance_auto_approve",
)
#: Settings fields that are booleans (re-asserted after the ""->None pass).
_SETTINGS_BOOLS = ("enabled", "alerts_enabled", "sms_alerts_enabled",
                   "attendance_sync_enabled", "attendance_auto_approve")


# ------------------------------------------------------------------- helpers

def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    return forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")


def _body(request) -> dict:
    try:
        return json.loads(request.body.decode() or "{}")
    except (ValueError, UnicodeDecodeError):
        return {}


def _audit(request, event, message, provider=None):
    TrackingLog.objects.create(
        log_type="audit", event=event, severity="info", message=message,
        provider=provider, user=request.user, ip_address=_client_ip(request),
    )


def _provider_payload(provider):
    config = provider.extra_config or {}
    return {
        "id": provider.pk,
        "name": provider.name,
        "provider_type": provider.provider_type,
        "api_url": provider.api_url,
        "username": provider.username,
        "customer_id": config.get("customer_id", ""),
        "endpoints": config.get("endpoints", {}),
        "timeout": config.get("timeout", 15),
        "refresh_interval_seconds": provider.refresh_interval_seconds,
        "webhook_url": provider.webhook_url,
        "priority": provider.priority,
        "is_active": provider.is_active,
        "last_sync_status": provider.last_sync_status,
        "last_synced_at": provider.last_synced_at.isoformat() if provider.last_synced_at else None,
        "last_error": provider.last_error,
        # Presence flags only — secret values never leave the server.
        "has_password": bool(provider.password),
        "has_access_token": bool(provider.access_token),
        "has_api_key": bool(provider.api_key),
        "has_webhook_secret": bool(provider.webhook_secret),
    }


# ------------------------------------------------------------ live dashboard

@method_decorator(login_required, name="dispatch")
class LiveDashboardAPI(View):
    """Tiles + live rows for the dashboard; filterable, refresh-polled."""

    def get(self, request):
        settings_row = TrackingSettings.get_solo()
        now = timezone.now()
        today = timezone.localdate()
        offline_after = timedelta(minutes=settings_row.offline_after_minutes)

        rows = (
            EmployeeLiveLocation.objects
            .select_related("employee", "employee__designation",
                            "employee__warehouse", "employee__group",
                            "current_customer")
            .exclude(employee__relieve=True)
        )
        rows = self._apply_filters(rows, request)[:MAX_LIVE_ROWS]

        distance_by_employee = dict(
            EmployeeRoute.objects.filter(date=today)
            .values_list("employee_id", "total_distance_km")
        )
        visits_by_employee = dict(
            EmployeeCustomerVisit.objects.filter(visit_date=today)
            .values("employee_id").annotate(n=Count("id"))
            .values_list("employee_id", "n")
        )

        employees, status_filter = [], (request.GET.get("status") or "").strip()
        for row in rows:
            status = row.status
            if now - row.recorded_at > offline_after:
                status = "offline"
            if status_filter and status != status_filter:
                continue
            employee = row.employee
            employees.append({
                "employee_id": employee.pk,
                "employee_code": employee.employee_id,
                "name": employee.full_name or "",
                "photo": employee.image.url if employee.image else "",
                "designation": employee.designation.title if employee.designation else "",
                "warehouse": employee.warehouse.name if employee.warehouse else "",
                "group": employee.group.name if employee.group else "",
                "latitude": float(row.latitude),
                "longitude": float(row.longitude),
                "accuracy_m": row.accuracy_m,
                "speed_kmh": row.speed_kmh,
                "battery_pct": row.battery_pct,
                "network": row.network,
                "gps_enabled": row.gps_enabled,
                "status": status,
                "is_checked_in": row.is_checked_in,
                "address": row.address,
                "current_customer": row.current_customer.name if row.current_customer else "",
                "recorded_at": row.recorded_at.isoformat(),
                "today_distance_km": float(distance_by_employee.get(employee.pk, 0)),
                "today_visits": visits_by_employee.get(employee.pk, 0),
            })

        return JsonResponse({
            "enabled": settings_row.enabled,
            "refresh_seconds": settings_row.dashboard_refresh_seconds,
            "tiles": self._tiles(now, today, offline_after),
            "employees": employees,
            "generated_at": now.isoformat(),
        })

    @staticmethod
    def _apply_filters(rows, request):
        q = (request.GET.get("q") or "").strip()
        if q:
            q_filter = Q(employee__full_name__icontains=q)
            if q.isdigit():
                q_filter |= Q(employee__employee_id=int(q))
            rows = rows.filter(q_filter)
        for param, field in (("warehouse", "employee__warehouse_id"),
                             ("group", "employee__group_id"),
                             ("designation", "employee__designation_id")):
            value = request.GET.get(param)
            if value and value.isdigit():
                rows = rows.filter(**{field: int(value)})
        return rows

    @staticmethod
    def _tiles(now, today, offline_after):
        total_employees = Employee.objects.exclude(relieve=True).count()
        live = EmployeeLiveLocation.objects.exclude(employee__relieve=True)
        stale_cutoff = now - offline_after
        fresh = live.filter(recorded_at__gte=stale_cutoff)

        online = fresh.exclude(status="offline").count()
        tracked = live.count()
        on_leave = (
            LeaveSelectedDate.objects
            .filter(date=today, leave_request__status="Approved")
            .values("leave_request__employee_id").distinct().count()
        )
        distance_today = sum(
            (float(d) for d in EmployeeRoute.objects.filter(date=today)
             .values_list("total_distance_km", flat=True)), 0.0
        )
        today_start = timezone.make_aware(
            timezone.datetime.combine(today, timezone.datetime.min.time())
        )
        return {
            "total_employees": total_employees,
            "online": online,
            "moving": fresh.filter(status="moving").count(),
            "idle": fresh.filter(status="idle").count(),
            "offline": tracked - online,
            "not_tracked": total_employees - tracked,
            "checked_in": live.filter(is_checked_in=True).count(),
            "on_leave": on_leave,
            "distance_today_km": round(distance_today, 1),
            "visits_today": EmployeeCustomerVisit.objects.filter(visit_date=today).count(),
            "gps_disabled": live.filter(gps_enabled=False).count(),
            "late_check_ins": TrackingLog.objects.filter(
                event="late_check_in", created_at__gte=today_start).count(),
            "unread_alerts": TrackingLog.objects.filter(
                log_type="alert", is_read=False).count(),
        }


# ----------------------------------------------------------------- settings

@method_decorator(login_required, name="dispatch")
class TrackingSettingsAPI(View):
    """Read/save the runtime settings singleton (secrets write-only)."""

    def get(self, request):
        return JsonResponse(self._payload(TrackingSettings.get_solo()))

    def post(self, request):
        body = _body(request)
        settings_row = TrackingSettings.get_solo()
        for field in _SETTINGS_FIELDS:
            if field in body:
                setattr(settings_row, field, body[field] if body[field] != "" else None)
        # Boolean fields must not be nulled by the ""->None normalisation.
        for field in _SETTINGS_BOOLS:
            if field in body:
                setattr(settings_row, field, bool(body[field]))
        google_key = body.get("google_maps_api_key")
        if google_key:  # blank keeps the stored key
            settings_row.google_maps_api_key = google_key
        settings_row.modified_by = request.user
        try:
            settings_row.full_clean(exclude=["modified_by"])
        except Exception as exc:  # noqa: BLE001 — surfaced as a 400
            return JsonResponse({"error": str(exc)}, status=400)
        settings_row.save()
        _audit(request, "settings_changed", "Tracking settings updated.")
        return JsonResponse(self._payload(settings_row))

    @staticmethod
    def _payload(settings_row):
        return {
            "enabled": settings_row.enabled,
            "map_provider": settings_row.map_provider,
            "has_google_maps_api_key": bool(settings_row.google_maps_api_key),
            "dashboard_refresh_seconds": settings_row.dashboard_refresh_seconds,
            "offline_after_minutes": settings_row.offline_after_minutes,
            "idle_after_minutes": settings_row.idle_after_minutes,
            "late_check_in_time": str(settings_row.late_check_in_time or ""),
            "early_check_out_time": str(settings_row.early_check_out_time or ""),
            "working_start": str(settings_row.working_start or ""),
            "working_end": str(settings_row.working_end or ""),
            "default_geofence_radius_m": settings_row.default_geofence_radius_m,
            "distance_unit": settings_row.distance_unit,
            "history_retention_days": settings_row.history_retention_days,
            "alerts_enabled": settings_row.alerts_enabled,
            "sms_alerts_enabled": settings_row.sms_alerts_enabled,
            "attendance_sync_enabled": settings_row.attendance_sync_enabled,
            "attendance_auto_approve": settings_row.attendance_auto_approve,
        }


# ---------------------------------------------------------------- providers

@method_decorator(login_required, name="dispatch")
class TrackingProviderAPI(View):
    """Provider master CRUD. Secret values are write-only."""

    def get(self, request):
        providers = TrackingProvider.objects.all().order_by("priority", "id")
        return JsonResponse({"providers": [_provider_payload(p) for p in providers]})

    @transaction.atomic
    def post(self, request):
        body = _body(request)
        provider_id = body.get("id")
        if provider_id:
            try:
                provider = TrackingProvider.objects.select_for_update().get(pk=provider_id)
            except TrackingProvider.DoesNotExist:
                return JsonResponse({"error": "Provider not found."}, status=404)
        else:
            if not body.get("name") or not body.get("api_url"):
                return JsonResponse({"error": "Name and API URL are required."}, status=400)
            provider = TrackingProvider(created_by=request.user)

        valid_types = {choice for choice, _ in TrackingProvider.PROVIDER_CHOICES}
        if body.get("provider_type") and body["provider_type"] not in valid_types:
            return JsonResponse({"error": "Unknown provider type."}, status=400)

        for field in _PROVIDER_FIELDS:
            if field in body:
                setattr(provider, field, body[field])
        for secret in _PROVIDER_SECRETS:
            if body.get(secret):  # blank keeps the stored secret
                setattr(provider, secret, body[secret])

        config = dict(provider.extra_config or {})
        for key in ("customer_id", "endpoints", "param_names", "timeout"):
            if key in body:
                config[key] = body[key]
        provider.extra_config = config
        provider.modified_by = request.user
        try:
            provider.full_clean(exclude=["created_by", "modified_by"])
        except Exception as exc:  # noqa: BLE001
            return JsonResponse({"error": str(exc)}, status=400)
        provider.save()
        _audit(request, "provider_changed",
               f"Provider '{provider.name}' saved.", provider=provider)
        return JsonResponse(_provider_payload(provider))

    def delete(self, request):
        provider_id = request.GET.get("id")
        try:
            provider = TrackingProvider.objects.get(pk=provider_id)
        except (TrackingProvider.DoesNotExist, ValueError, TypeError):
            return JsonResponse({"error": "Provider not found."}, status=404)
        provider.is_active = False
        provider.modified_by = request.user
        provider.save(update_fields=["is_active", "modified_by", "updated_at"])
        _audit(request, "provider_changed",
               f"Provider '{provider.name}' deactivated.", provider=provider)
        return JsonResponse({"ok": True})


@method_decorator(login_required, name="dispatch")
class ProviderTestAPI(View):
    """Server-side connection test — the browser never holds credentials."""

    def post(self, request):
        body = _body(request)
        try:
            provider = TrackingProvider.objects.get(pk=body.get("id"))
        except (TrackingProvider.DoesNotExist, ValueError, TypeError):
            return JsonResponse({"error": "Provider not found."}, status=404)
        try:
            adapter = get_adapter(provider)
        except TrackingConfigurationError as exc:
            return JsonResponse({"success": False, "message": str(exc)})
        result = adapter.test_connection()
        return JsonResponse({
            "success": result.success,
            "message": result.message,
            "details": result.details or {},
        })


# ----------------------------------------------------------------- mappings

@method_decorator(login_required, name="dispatch")
class MappingAPI(View):
    """Identity mapping editor: vendor directory ↔ hr.Employee."""

    def get(self, request):
        try:
            provider = TrackingProvider.objects.get(pk=request.GET.get("provider"))
        except (TrackingProvider.DoesNotExist, ValueError, TypeError):
            return JsonResponse({"error": "Provider not found."}, status=404)
        try:
            adapter = get_adapter(provider)
            directory = adapter.fetch_employees()
        except (TrackingConfigurationError, TrackingProviderError) as exc:
            return JsonResponse({"error": str(exc)}, status=502)

        mapped = {
            m.external_id: m
            for m in EmployeeProviderMapping.objects.filter(provider=provider)
            .select_related("employee")
        }
        people = []
        for person in directory:
            mapping = mapped.get(person.external_id)
            people.append({
                "external_id": person.external_id,
                "external_name": person.name,
                "phone": person.phone,
                "is_active": person.is_active,
                "employee_id": mapping.employee_id if mapping else None,
                "employee_label": (
                    f"{mapping.employee.full_name} ({mapping.employee.employee_id})"
                    if mapping else ""
                ),
            })
        return JsonResponse({"provider": provider.pk, "people": people})

    def post(self, request):
        body = _body(request)
        try:
            provider = TrackingProvider.objects.get(pk=body.get("provider"))
        except (TrackingProvider.DoesNotExist, ValueError, TypeError):
            return JsonResponse({"error": "Provider not found."}, status=404)
        external_id = str(body.get("external_id") or "").strip()
        if not external_id:
            return JsonResponse({"error": "external_id is required."}, status=400)

        employee_id = body.get("employee_id")
        if not employee_id:  # unmap
            deleted, _ = EmployeeProviderMapping.objects.filter(
                provider=provider, external_id=external_id).delete()
            if deleted:
                _audit(request, "mapping_changed",
                       f"Unmapped provider identity {external_id}.", provider=provider)
            return JsonResponse({"ok": True, "mapped": False})

        try:
            employee = Employee.objects.get(pk=employee_id)
        except (Employee.DoesNotExist, ValueError, TypeError):
            return JsonResponse({"error": "Employee not found."}, status=404)

        conflict = (
            EmployeeProviderMapping.objects
            .filter(provider=provider, employee=employee)
            .exclude(external_id=external_id).first()
        )
        if conflict:
            return JsonResponse({
                "error": f"{employee.full_name} is already mapped to provider "
                         f"identity {conflict.external_id}. Unmap that first.",
            }, status=400)

        EmployeeProviderMapping.objects.update_or_create(
            provider=provider, external_id=external_id,
            defaults={
                "employee": employee,
                "external_name": str(body.get("external_name") or ""),
                "is_active": True,
            },
        )
        _audit(request, "mapping_changed",
               f"Mapped provider identity {external_id} to {employee.full_name}.",
               provider=provider)
        return JsonResponse({"ok": True, "mapped": True})


# ----------------------------------------------------------- route/timeline

@method_decorator(login_required, name="dispatch")
class RouteAPI(View):
    """One employee's day: route summary, replay polyline, and merged timeline."""

    def get(self, request):
        try:
            employee = Employee.objects.get(pk=request.GET.get("employee"))
        except (Employee.DoesNotExist, ValueError, TypeError):
            return JsonResponse({"error": "Employee not found."}, status=404)
        try:
            day = timezone.datetime.strptime(
                request.GET.get("date", ""), "%Y-%m-%d").date()
        except ValueError:
            day = timezone.localdate()

        route = (
            EmployeeRoute.objects.filter(employee=employee, date=day)
            .prefetch_related("points__customer").first()
        )
        payload = {
            "employee": employee.full_name or "",
            "employee_code": employee.employee_id,
            "date": day.isoformat(),
            "route": None,
            "timeline": self._timeline(employee, day, route),
        }
        if route:
            payload["route"] = {
                "distance_km": float(route.total_distance_km),
                "travel_time_min": int(route.travel_time.total_seconds() // 60)
                    if route.travel_time else None,
                "idle_time_min": int(route.idle_time.total_seconds() // 60)
                    if route.idle_time else None,
                "average_speed_kmh": route.average_speed_kmh,
                "max_speed_kmh": route.max_speed_kmh,
                "stops_count": route.stops_count,
                "points_count": route.points_count,
                "first_point_at": route.first_point_at.isoformat() if route.first_point_at else None,
                "last_point_at": route.last_point_at.isoformat() if route.last_point_at else None,
                "start_address": route.start_address,
                "end_address": route.end_address,
                "polyline": route.polyline,
                "is_finalized": route.is_finalized,
            }
        return JsonResponse(payload)

    @staticmethod
    def _timeline(employee, day, route):
        """Chronological merge: attendance, route stops/legs, customer visits."""
        entries = []

        attendance = EmployeeGpsAttendance.objects.filter(
            employee=employee, date=day).first()
        if attendance and attendance.check_in_at:
            entries.append({
                "time": attendance.check_in_at.isoformat(), "type": "check_in",
                "label": "Checked in" + (" (late)" if attendance.is_late else ""),
                "address": attendance.check_in_address,
                "latitude": float(attendance.check_in_latitude)
                    if attendance.check_in_latitude is not None else None,
                "longitude": float(attendance.check_in_longitude)
                    if attendance.check_in_longitude is not None else None,
                "duration_min": None,
            })
        if route:
            for point in route.points.all():
                if point.point_type in ("check_in", "check_out"):
                    continue  # attendance entries above are richer
                label = {"stop": "Stopped", "idle": "Idle",
                         "visit": "Customer visit", "travel": "Travelling"}.get(
                             point.point_type, point.point_type)
                if point.customer:
                    label = f"At {point.customer.name}"
                entries.append({
                    "time": point.started_at.isoformat(), "type": point.point_type,
                    "label": label, "address": point.address,
                    "latitude": float(point.latitude), "longitude": float(point.longitude),
                    "duration_min": int(point.duration.total_seconds() // 60)
                        if point.duration else None,
                    "distance_km": float(point.distance_from_previous_km)
                        if point.distance_from_previous_km is not None else None,
                })
        for visit in EmployeeCustomerVisit.objects.filter(
                employee=employee, visit_date=day).select_related("customer"):
            if not visit.check_in_at:
                continue
            entries.append({
                "time": visit.check_in_at.isoformat(), "type": "visit",
                "label": "Visit: " + (visit.customer.name if visit.customer
                                      else visit.external_customer_name or "customer"),
                "address": visit.address,
                "latitude": float(visit.check_in_latitude)
                    if visit.check_in_latitude is not None else None,
                "longitude": float(visit.check_in_longitude)
                    if visit.check_in_longitude is not None else None,
                "duration_min": int(visit.duration.total_seconds() // 60)
                    if visit.duration else None,
            })
        if attendance and attendance.check_out_at:
            entries.append({
                "time": attendance.check_out_at.isoformat(), "type": "check_out",
                "label": "Checked out" + (" (early)" if attendance.is_early_exit else ""),
                "address": attendance.check_out_address,
                "latitude": float(attendance.check_out_latitude)
                    if attendance.check_out_latitude is not None else None,
                "longitude": float(attendance.check_out_longitude)
                    if attendance.check_out_longitude is not None else None,
                "duration_min": None,
            })
        entries.sort(key=lambda entry: entry["time"])
        return entries


# ------------------------------------------------------------------ reports

@method_decorator(login_required, name="dispatch")
class ReportsAPI(View):
    """Runs a registered tracking report; ?format=csv streams a download."""

    def get(self, request):
        from .services import report_service

        report = request.GET.get("report", "daily_tracking")
        if report not in report_service.REPORTS:
            return JsonResponse({"error": f"Unknown report '{report}'."}, status=400)

        end = self._date(request.GET.get("to")) or timezone.localdate()
        start = self._date(request.GET.get("from")) or (end - timedelta(days=6))
        employee_id = self._int(request.GET.get("employee"))
        warehouse_id = self._int(request.GET.get("warehouse"))

        data = report_service.build(
            report, start, end, employee_id=employee_id, warehouse_id=warehouse_id
        )
        if request.GET.get("format") == "csv":
            return self._csv(report, data)
        data.update({
            "report": report,
            "label": report_service.REPORTS[report][0],
            "from": start.isoformat(), "to": end.isoformat(),
        })
        return JsonResponse(data)

    @staticmethod
    def _date(value):
        try:
            return timezone.datetime.strptime(value or "", "%Y-%m-%d").date()
        except ValueError:
            return None

    @staticmethod
    def _int(value):
        return int(value) if value and str(value).isdigit() else None

    @staticmethod
    def _csv(report, data):
        import csv

        from django.http import HttpResponse

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{report}.csv"'
        writer = csv.writer(response)
        writer.writerow([column["label"] for column in data["columns"]])
        for row in data["rows"]:
            writer.writerow([row.get(column["key"], "") for column in data["columns"]])
        return response


# ------------------------------------------------------------------- visits

@method_decorator(login_required, name="dispatch")
class VisitsAPI(View):
    """Customer visits: list + tiles, filterable; also feeds Customer Master."""

    MAX_PAGE_SIZE = 200

    def get(self, request):
        visits = (
            EmployeeCustomerVisit.objects
            .select_related("employee", "customer")
            .order_by("-visit_date", "-check_in_at")
        )
        visits = self._apply_filters(visits, request)

        try:
            page_size = min(int(request.GET.get("page_size", 50)), self.MAX_PAGE_SIZE)
            page = max(int(request.GET.get("page", 1)), 1)
        except ValueError:
            page_size, page = 50, 1
        total = visits.count()
        rows = [self._row(v) for v in visits[(page - 1) * page_size: page * page_size]]

        return JsonResponse({
            "tiles": self._tiles(visits),
            "visits": rows,
            "page": page, "page_size": page_size, "total": total,
        })

    @staticmethod
    def _apply_filters(visits, request):
        get = request.GET
        for param, field in (("from", "visit_date__gte"), ("to", "visit_date__lte")):
            value = get.get(param)
            if value:
                try:
                    visits = visits.filter(**{
                        field: timezone.datetime.strptime(value, "%Y-%m-%d").date()
                    })
                except ValueError:
                    pass
        for param, field in (("employee", "employee_id"), ("customer", "customer_id")):
            value = get.get(param)
            if value and value.isdigit():
                visits = visits.filter(**{field: int(value)})
        status = get.get("status")
        if status in dict(EmployeeCustomerVisit.STATUS_CHOICES):
            visits = visits.filter(status=status)
        if get.get("unmatched") == "1":
            visits = visits.filter(customer__isnull=True)
        q = (get.get("q") or "").strip()
        if q:
            visits = visits.filter(
                Q(employee__full_name__icontains=q)
                | Q(customer__name__icontains=q)
                | Q(external_customer_name__icontains=q)
            )
        return visits

    @staticmethod
    def _row(visit):
        duration_min = (
            int(visit.duration.total_seconds() // 60) if visit.duration else None
        )
        return {
            "id": visit.pk,
            "employee_id": visit.employee_id,
            "employee": visit.employee.full_name or "",
            "employee_code": visit.employee.employee_id,
            "customer_id": visit.customer_id,
            "customer": visit.customer.name if visit.customer else "",
            "external_customer_name": visit.external_customer_name,
            "matched": visit.customer_id is not None,
            "visit_date": visit.visit_date.isoformat(),
            "status": visit.status,
            "check_in_at": visit.check_in_at.isoformat() if visit.check_in_at else None,
            "check_out_at": visit.check_out_at.isoformat() if visit.check_out_at else None,
            "duration_min": duration_min,
            "latitude": float(visit.check_in_latitude) if visit.check_in_latitude is not None else None,
            "longitude": float(visit.check_in_longitude) if visit.check_in_longitude is not None else None,
            "address": visit.address,
            "remarks": visit.remarks,
            "next_follow_up": visit.next_follow_up.isoformat() if visit.next_follow_up else None,
            "photo_url": visit.photo_url or (visit.photo.url if visit.photo else ""),
            "distance_travelled_km": float(visit.distance_travelled_km)
                if visit.distance_travelled_km is not None else None,
        }

    @staticmethod
    def _tiles(visits):
        durations = list(
            visits.filter(duration__isnull=False)
            .values_list("duration", flat=True)[:1000]
        )
        avg_minutes = (
            int(sum((d.total_seconds() for d in durations), 0) / len(durations) // 60)
            if durations else 0
        )
        return {
            "total": visits.count(),
            "completed": visits.filter(status="completed").count(),
            "in_progress": visits.filter(status="in_progress").count(),
            "unique_customers": visits.filter(customer__isnull=False)
                .values("customer_id").distinct().count(),
            "unmatched": visits.filter(customer__isnull=True).count(),
            "avg_duration_min": avg_minutes,
            "follow_ups_due": visits.filter(
                next_follow_up__isnull=False,
                next_follow_up__lte=timezone.localdate()).count(),
        }


@method_decorator(login_required, name="dispatch")
class VisitLinkAPI(View):
    """Repair tool: link unmatched visits to a CRM customer (or unlink)."""

    def post(self, request):
        body = _body(request)
        customer = None
        if body.get("customer_id"):
            try:
                customer = Customer.objects.get(pk=body["customer_id"])
            except (Customer.DoesNotExist, ValueError, TypeError):
                return JsonResponse({"error": "Customer not found."}, status=404)

        visits = EmployeeCustomerVisit.objects.all()
        if body.get("visit_ids"):
            visits = visits.filter(pk__in=body["visit_ids"])
        elif body.get("external_customer_name"):
            # Bulk repair: every unmatched visit reported under this vendor name.
            visits = visits.filter(
                customer__isnull=True,
                external_customer_name__iexact=str(body["external_customer_name"]).strip(),
            )
        else:
            return JsonResponse(
                {"error": "Provide visit_ids or external_customer_name."}, status=400
            )

        updated = visits.update(customer=customer)
        _audit(
            request, "mapping_changed",
            f"{'Linked' if customer else 'Unlinked'} {updated} visit(s) "
            f"{'to ' + customer.name if customer else ''}".strip() + ".",
        )
        return JsonResponse({"ok": True, "updated": updated})


# --------------------------------------------------------------- attendance

@method_decorator(login_required, name="dispatch")
class GpsAttendanceAPI(View):
    """GPS attendance records for a day: map, verification and approval data."""

    def get(self, request):
        try:
            day = timezone.datetime.strptime(
                request.GET.get("date", ""), "%Y-%m-%d").date()
        except ValueError:
            day = timezone.localdate()

        records = (
            EmployeeGpsAttendance.objects.filter(date=day)
            .select_related("employee", "employee__designation",
                            "employee__warehouse", "geofence", "attendance")
            .order_by("employee__full_name")
        )
        status_filter = request.GET.get("status")
        if status_filter in ("pending", "approved", "rejected"):
            records = records.filter(status=status_filter)
        if request.GET.get("late") == "1":
            records = records.filter(is_late=True)
        q = (request.GET.get("q") or "").strip()
        if q:
            records = records.filter(employee__full_name__icontains=q)

        rows = [self._row(record) for record in records]
        return JsonResponse({
            "date": day.isoformat(),
            "tiles": self._tiles(day),
            "records": rows,
        })

    @staticmethod
    def _row(record):
        def _duration_minutes(value):
            return int(value.total_seconds() // 60) if value else None

        return {
            "id": record.pk,
            "employee_id": record.employee_id,
            "name": record.employee.full_name or "",
            "employee_code": record.employee.employee_id,
            "designation": record.employee.designation.title if record.employee.designation else "",
            "warehouse": record.employee.warehouse.name if record.employee.warehouse else "",
            "photo": record.employee.image.url if record.employee.image else "",
            "check_in_at": record.check_in_at.isoformat() if record.check_in_at else None,
            "check_out_at": record.check_out_at.isoformat() if record.check_out_at else None,
            "check_in_latitude": float(record.check_in_latitude) if record.check_in_latitude is not None else None,
            "check_in_longitude": float(record.check_in_longitude) if record.check_in_longitude is not None else None,
            "check_out_latitude": float(record.check_out_latitude) if record.check_out_latitude is not None else None,
            "check_out_longitude": float(record.check_out_longitude) if record.check_out_longitude is not None else None,
            "check_in_address": record.check_in_address,
            "check_out_address": record.check_out_address,
            "check_in_photo_url": record.check_in_photo_url,
            "check_out_photo_url": record.check_out_photo_url,
            "geofence": record.geofence.name if record.geofence else "",
            "check_in_inside_fence": record.check_in_inside_fence,
            "check_out_inside_fence": record.check_out_inside_fence,
            "is_late": record.is_late,
            "late_by_minutes": _duration_minutes(record.late_by),
            "is_early_exit": record.is_early_exit,
            "early_by_minutes": _duration_minutes(record.early_by),
            "status": record.status,
            "rejection_reason": record.rejection_reason,
            "hr_mirrored": record.attendance_id is not None,
        }

    @staticmethod
    def _tiles(day):
        records = EmployeeGpsAttendance.objects.filter(date=day)
        return {
            "total": records.count(),
            "checked_in": records.filter(check_in_at__isnull=False).count(),
            "checked_out": records.filter(check_out_at__isnull=False).count(),
            "late": records.filter(is_late=True).count(),
            "early_exits": records.filter(is_early_exit=True).count(),
            "outside_fence": records.filter(check_in_inside_fence=False).count(),
            "pending": records.filter(status="pending").count(),
            "approved": records.filter(status="approved").count(),
            "rejected": records.filter(status="rejected").count(),
        }


@method_decorator(login_required, name="dispatch")
class GpsAttendanceApprovalAPI(View):
    """Approve/reject GPS attendance records (mirrors into hr.Attendance)."""

    def post(self, request):
        body = _body(request)
        action = body.get("action")
        ids = body.get("ids") or []
        if action not in ("approve", "reject") or not isinstance(ids, list) or not ids:
            return JsonResponse(
                {"error": "Provide action ('approve'/'reject') and a list of ids."},
                status=400,
            )
        service = AttendanceIntegrationService()
        records = EmployeeGpsAttendance.objects.filter(pk__in=ids)
        processed = []
        for record in records:
            if action == "approve":
                service.approve(record, user=request.user)
            else:
                service.reject(record, user=request.user,
                               reason=str(body.get("reason") or ""))
            processed.append(record.pk)
        _audit(request, "attendance_approval",
               f"GPS attendance {action} applied to {len(processed)} record(s).")
        return JsonResponse({"ok": True, "action": action, "processed": processed})


# ---------------------------------------------------------------- geofences

@method_decorator(login_required, name="dispatch")
class GeofenceAPI(View):
    """Geofence master CRUD (local fences; vendor-synced ones stay read-only)."""

    _FIELDS = ("name", "geofence_type", "radius_m", "address",
               "alert_on_entry", "alert_on_exit", "is_active")

    def get(self, request):
        fences = (
            EmployeeGeofence.objects
            .select_related("warehouse", "customer", "provider")
            .order_by("geofence_type", "name")
        )
        return JsonResponse({"geofences": [{
            "id": fence.pk,
            "name": fence.name,
            "geofence_type": fence.geofence_type,
            "center_latitude": float(fence.center_latitude),
            "center_longitude": float(fence.center_longitude),
            "radius_m": fence.radius_m,
            "address": fence.address,
            "warehouse_id": fence.warehouse_id,
            "warehouse": fence.warehouse.name if fence.warehouse else "",
            "customer_id": fence.customer_id,
            "customer": fence.customer.name if fence.customer else "",
            "alert_on_entry": fence.alert_on_entry,
            "alert_on_exit": fence.alert_on_exit,
            "working_start": str(fence.working_start or ""),
            "working_end": str(fence.working_end or ""),
            "is_active": fence.is_active,
            "provider": fence.provider.name if fence.provider else "",
            "vendor_synced": bool(fence.external_id),
        } for fence in fences]})

    def post(self, request):
        body = _body(request)
        if body.get("id"):
            try:
                fence = EmployeeGeofence.objects.get(pk=body["id"])
            except EmployeeGeofence.DoesNotExist:
                return JsonResponse({"error": "Geofence not found."}, status=404)
        else:
            fence = EmployeeGeofence(created_by=request.user)

        for field in self._FIELDS:
            if field in body:
                setattr(fence, field, body[field])
        for field in ("center_latitude", "center_longitude"):
            if body.get(field) in (None, ""):
                continue
            setattr(fence, field, body[field])
        for field in ("working_start", "working_end"):
            if field in body:
                setattr(fence, field, body[field] or None)
        for field, model in (("warehouse_id", Warehouse), ("customer_id", Customer)):
            if field in body:
                value = body[field]
                if value and not model.objects.filter(pk=value).exists():
                    return JsonResponse(
                        {"error": f"{field.replace('_id', '').title()} not found."},
                        status=404)
                setattr(fence, field, value or None)

        fence.modified_by = request.user
        try:
            fence.full_clean(exclude=["created_by", "modified_by", "provider"])
        except Exception as exc:  # noqa: BLE001
            return JsonResponse({"error": str(exc)}, status=400)
        fence.save()
        _audit(request, "geofence_changed", f"Geofence '{fence.name}' saved.")
        return JsonResponse({"ok": True, "id": fence.pk})

    def delete(self, request):
        try:
            fence = EmployeeGeofence.objects.get(pk=request.GET.get("id"))
        except (EmployeeGeofence.DoesNotExist, ValueError, TypeError):
            return JsonResponse({"error": "Geofence not found."}, status=404)
        fence.is_active = False
        fence.modified_by = request.user
        fence.save(update_fields=["is_active", "modified_by", "updated_at"])
        _audit(request, "geofence_changed", f"Geofence '{fence.name}' deactivated.")
        return JsonResponse({"ok": True})


# ------------------------------------------------------------------- alerts

@method_decorator(login_required, name="dispatch")
class AlertsAPI(View):
    """Alert inbox: list, filter, and mark-read."""

    MAX_PAGE_SIZE = 200

    def get(self, request):
        alerts = (
            TrackingLog.objects.filter(log_type="alert")
            .select_related("employee", "geofence")
            .order_by("-created_at")
        )
        if request.GET.get("unread") == "1":
            alerts = alerts.filter(is_read=False)
        event = request.GET.get("event")
        if event:
            alerts = alerts.filter(event=event)
        severity = request.GET.get("severity")
        if severity:
            alerts = alerts.filter(severity=severity)
        employee = request.GET.get("employee")
        if employee and employee.isdigit():
            alerts = alerts.filter(employee_id=int(employee))

        try:
            page_size = min(int(request.GET.get("page_size", 50)), self.MAX_PAGE_SIZE)
            page = max(int(request.GET.get("page", 1)), 1)
        except ValueError:
            page_size, page = 50, 1
        total = alerts.count()

        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        base = TrackingLog.objects.filter(log_type="alert")
        tiles = {
            "unread": base.filter(is_read=False).count(),
            "today": base.filter(created_at__gte=today_start).count(),
            "warnings": base.filter(is_read=False, severity="warning").count(),
            "errors": base.filter(is_read=False,
                                  severity__in=("error", "critical")).count(),
        }
        rows = [{
            "id": alert.pk,
            "when": alert.created_at.isoformat(),
            "event": alert.event,
            "event_label": alert.get_event_display(),
            "severity": alert.severity,
            "message": alert.message,
            "employee": alert.employee.full_name if alert.employee else "",
            "geofence": alert.geofence.name if alert.geofence else "",
            "is_read": alert.is_read,
        } for alert in alerts[(page - 1) * page_size: page * page_size]]
        return JsonResponse({"tiles": tiles, "alerts": rows,
                             "page": page, "page_size": page_size, "total": total})

    def post(self, request):
        body = _body(request)
        action = body.get("action")
        queryset = TrackingLog.objects.filter(log_type="alert", is_read=False)
        if action == "mark_read":
            ids = body.get("ids") or []
            if not isinstance(ids, list) or not ids:
                return JsonResponse({"error": "Provide ids to mark read."}, status=400)
            queryset = queryset.filter(pk__in=ids)
        elif action != "mark_all_read":
            return JsonResponse(
                {"error": "action must be 'mark_read' or 'mark_all_read'."}, status=400)
        updated = queryset.update(
            is_read=True, read_by=request.user, read_at=timezone.now())
        return JsonResponse({"ok": True, "updated": updated})


# ------------------------------------------------------------------ webhook

@method_decorator(csrf_exempt, name="dispatch")
class WebhookAPI(View):
    """Inbound vendor webhook: authenticated by the provider's shared secret.

    Unauthenticated by session (vendors have no ERP login); instead every
    request must carry the per-provider webhook secret. The payload itself is
    only audit-logged — the single source of truth stays the pull sync, which
    a webhook receipt merely triggers early for its provider. That gives
    webhook-driven freshness without trusting or parsing an unverified
    payload schema.
    """

    MAX_BODY_BYTES = 100_000

    def post(self, request, provider_id):
        try:
            provider = TrackingProvider.objects.get(pk=provider_id, is_active=True)
        except TrackingProvider.DoesNotExist:
            return JsonResponse({"error": "Unknown provider."}, status=404)
        secret = provider.webhook_secret
        supplied = (request.headers.get("X-Webhook-Secret")
                    or request.headers.get("api-key") or "")
        if not secret or not constant_time_compare(supplied, secret):
            TrackingLog.objects.create(
                log_type="webhook", event="webhook_rejected", severity="warning",
                message="Webhook rejected: missing or invalid secret.",
                provider=provider, ip_address=_client_ip(request),
            )
            return JsonResponse({"error": "Invalid webhook secret."}, status=403)
        if len(request.body) > self.MAX_BODY_BYTES:
            return JsonResponse({"error": "Payload too large."}, status=413)

        payload = _body(request)
        TrackingLog.objects.create(
            log_type="webhook", event="webhook_received", severity="info",
            message=f"Webhook received for {provider.name}.",
            payload={"keys": sorted(payload)[:50]} if payload else None,
            provider=provider, ip_address=_client_ip(request),
        )

        synced = False
        if TrackingSettings.get_solo().enabled and SyncNowAPI._acquire_lock():
            try:
                SyncService().sync_provider(
                    provider, kinds=["live"], trigger="webhook")
                synced = True
            except Exception:  # noqa: BLE001 — webhook must never 500 on sync issues
                logger.exception("Webhook-triggered sync failed for %s", provider.name)
            finally:
                SyncLock.objects.filter(pk=1).update(is_running=False)
        return JsonResponse({"ok": True, "synced": synced})


# ----------------------------------------------------------------- sync now

@method_decorator(login_required, name="dispatch")
class SyncNowAPI(View):
    """Manual sync trigger from the UI — same engine, same lock as the CLI."""

    def post(self, request):
        settings_row = TrackingSettings.get_solo()
        if not settings_row.enabled:
            return JsonResponse(
                {"error": "Employee tracking is disabled in Tracking Settings."},
                status=400,
            )
        body = _body(request)
        kinds = body.get("kinds")
        if kinds:
            invalid = [kind for kind in kinds if kind not in DEFAULT_KINDS]
            if invalid:
                return JsonResponse(
                    {"error": f"Unknown kind(s): {', '.join(invalid)}."}, status=400
                )

        if not self._acquire_lock():
            return JsonResponse(
                {"error": "A sync is already running; try again shortly."}, status=409
            )
        try:
            runs = SyncService().sync_all(
                kinds=kinds, trigger="manual",
                provider_filter=body.get("provider_id"),
            )
        finally:
            SyncLock.objects.filter(pk=1).update(is_running=False)

        return JsonResponse({"runs": [{
            "provider": run.provider.name,
            "sync_type": run.sync_type,
            "status": run.status,
            "fetched": run.records_fetched,
            "created": run.records_created,
            "updated": run.records_updated,
            "skipped": run.records_skipped,
            "error": run.error_message,
        } for run in runs]})

    @staticmethod
    def _acquire_lock() -> bool:
        with transaction.atomic():
            lock, _created = SyncLock.objects.select_for_update().get_or_create(pk=1)
            stale = lock.started_at is None or (
                timezone.now() - lock.started_at > timedelta(minutes=10)
            )
            if lock.is_running and not stale:
                return False
            lock.is_running = True
            lock.started_at = timezone.now()
            lock.save(update_fields=["is_running", "started_at"])
            return True
