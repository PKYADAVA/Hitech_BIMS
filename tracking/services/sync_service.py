# pylint: disable=no-member
"""The background sync engine: provider API → ERP database.

Orchestrates every data kind for every active provider, in priority order:

    TrackingProvider rows ──> adapter (tracking.providers) ──> writers here
                                                      │
                                 TrackingSync run rows ┴ TrackingLog events

Guarantees:

* **Incremental** — windowed kinds (history/visits/attendance) resume from
  the last successful run's ``window_end`` (minus a small overlap), capped
  at :data:`MAX_WINDOW` per run so a long outage catches up in slices.
* **Duplicate-safe** — writers upsert by natural keys; the raw-ping insert
  additionally relies on the table's unique constraints, so replaying any
  window is harmless.
* **Retry** — transient fetch failures retry with exponential backoff
  (:mod:`tracking.services.retry`); permanent failures fail the run once.
  A credential rejection aborts the provider's whole cycle and flags the row.
* **Observable** — every run is a TrackingSync row with counters; failures
  and unmatched-identity conditions land in TrackingLog.

The UI never talks to a vendor: this engine is invoked by the
``sync_tracking`` management command (OS-scheduled) or a manual trigger.
"""

import logging
import time as time_module
from datetime import timedelta

from django.db import models
from django.utils import timezone

from hr.models import Employee
from sales.models import Customer

from ..exceptions import (
    TrackingAuthError,
    TrackingConfigurationError,
    TrackingProviderError,
)
from ..models import (
    EmployeeGeofence,
    EmployeeLiveLocation,
    EmployeeLocationHistory,
    EmployeeCustomerVisit,
    EmployeeProviderMapping,
    TrackingLog,
    TrackingProvider,
    TrackingSettings,
    TrackingSync,
)
from ..providers import get_adapter
from .attendance_service import AttendanceIntegrationService
from .retry import call_with_retry
from .route_service import RouteBuilder

logger = logging.getLogger("tracking.sync")

#: Sync order: identity mapping first, then data kinds that depend on it.
DEFAULT_KINDS = ("employees", "live", "history", "visits", "attendance", "geofences")
#: Kinds fetched with a from/to window and a stored cursor.
WINDOWED_KINDS = frozenset({"history", "visits", "attendance"})
#: First-ever sync looks back this far.
DEFAULT_LOOKBACK = timedelta(hours=24)
#: Re-fetch this much of the previous window; dedup absorbs the overlap.
WINDOW_OVERLAP = timedelta(minutes=5)
#: Upper bound per run; long gaps catch up over successive runs.
MAX_WINDOW = timedelta(days=7)

_GEOFENCE_TYPES = {choice for choice, _ in EmployeeGeofence.TYPE_CHOICES}


class _AbortProvider(Exception):
    """Internal: stop all remaining kinds for this provider (auth failure)."""


class SyncService:
    """One sync cycle over the configured providers."""

    def __init__(self, adapter_factory=get_adapter, lookback: timedelta = None,
                 sleep=time_module.sleep):
        self._adapter_factory = adapter_factory
        self._lookback = lookback or DEFAULT_LOOKBACK
        self._sleep = sleep
        self._settings = TrackingSettings.get_solo()
        self._route_builder = RouteBuilder(self._settings)

    # ---------------------------------------------------------- entrypoints

    def sync_all(self, kinds=None, trigger="scheduler", provider_filter=None):
        """Sync every active provider; returns the list of TrackingSync runs."""
        providers = TrackingProvider.objects.filter(is_active=True).order_by("priority", "id")
        if provider_filter:
            if str(provider_filter).isdigit():
                providers = providers.filter(pk=int(provider_filter))
            else:
                providers = providers.filter(name__iexact=str(provider_filter))
        runs = []
        for provider in providers:
            runs.extend(self.sync_provider(provider, kinds=kinds, trigger=trigger))
        return runs

    def sync_provider(self, provider, kinds=None, trigger="scheduler"):
        """Sync one provider across the requested kinds, in dependency order."""
        try:
            adapter = self._adapter_factory(provider)
        except TrackingConfigurationError as exc:
            self._mark_provider(provider, ok=False, error=str(exc))
            self._log(provider, None, "sync_failed", "error", str(exc))
            return []

        runs, aborted = [], False
        for kind in (kinds or DEFAULT_KINDS):
            if kind not in DEFAULT_KINDS or not adapter.supports(kind):
                continue
            try:
                run = self._sync_kind(provider, adapter, kind, trigger)
            except _AbortProvider:
                aborted = True
                break
            runs.append(run)

        if aborted:
            return runs  # provider already flagged by the aborting kind

        # Vendors gate endpoints per licensed module, so one kind failing
        # (even with "not authorized") must not poison the provider: the row
        # is OK if anything succeeded, with the failing kinds noted.
        failed_runs = [run for run in runs if run.status == "failed"]
        succeeded = any(run.status in ("success", "partial") for run in runs)
        if runs and not succeeded:
            self._mark_provider(provider, ok=False,
                                error=failed_runs[0].error_message[:500])
        else:
            summary = "; ".join(
                f"{run.sync_type}: {run.error_message[:80]}" for run in failed_runs
            )
            self._mark_provider(provider, ok=True, error=summary[:500])
        return runs

    # ------------------------------------------------------------- one run

    def _sync_kind(self, provider, adapter, kind, trigger) -> TrackingSync:
        run = TrackingSync.objects.create(
            provider=provider, sync_type=kind, triggered_by=trigger,
        )
        if kind in WINDOWED_KINDS:
            run.window_start, run.window_end = self._window(provider, run.sync_type)
            run.save(update_fields=["window_start", "window_end"])

        try:
            fetched, retries = call_with_retry(
                lambda: self._fetch(adapter, kind, run), sleep=self._sleep
            )
            run.retry_count = retries
            counters = self._write(provider, kind, fetched)
            run.records_fetched = len(fetched)
            run.records_created = counters.get("created", 0)
            run.records_updated = counters.get("updated", 0)
            run.records_skipped = counters.get("skipped", 0)
            # "partial": the vendor sent rows but none could be attributed
            # (typically every employee unmapped) — worth surfacing.
            all_skipped = bool(fetched) and not (
                run.records_created or run.records_updated
            ) and run.records_skipped
            run.status = "partial" if all_skipped else "success"
        except TrackingAuthError as exc:
            self._fail_run(run, provider, exc)
            # Only a directory-sync rejection means the credentials themselves
            # are bad; on any other kind it's a per-module permission gap
            # (e.g. Tasks not licensed) and the cycle continues.
            if kind == "employees":
                self._mark_provider(provider, ok=False, error=str(exc))
                run.finished_at = timezone.now()
                run.save()
                raise _AbortProvider() from exc
        except (TrackingProviderError, TrackingConfigurationError) as exc:
            self._fail_run(run, provider, exc)
        except Exception as exc:  # noqa: BLE001 — a writer bug must not kill the cycle
            logger.exception("Unhandled error during %s sync of %s", kind, provider.name)
            self._fail_run(run, provider, exc)

        run.finished_at = timezone.now()
        run.save()
        return run

    def _window(self, provider, sync_type):
        """[cursor − overlap, min(cursor + MAX_WINDOW, now)] for a windowed kind."""
        now = timezone.now()
        last = (
            TrackingSync.objects
            .filter(provider=provider, sync_type=sync_type,
                    status__in=("success", "partial"), window_end__isnull=False)
            .order_by("-window_end").first()
        )
        start = (last.window_end - WINDOW_OVERLAP) if last else (now - self._lookback)
        end = min(start + MAX_WINDOW, now)
        return start, end

    def _fetch(self, adapter, kind, run):
        if kind == "employees":
            return adapter.fetch_employees()
        if kind == "live":
            return adapter.fetch_live_locations()
        if kind == "history":
            return adapter.fetch_location_history(run.window_start, run.window_end)
        if kind == "visits":
            return adapter.fetch_visits(run.window_start, run.window_end)
        if kind == "attendance":
            return adapter.fetch_attendance_events(run.window_start, run.window_end)
        return adapter.fetch_geofences()

    def _write(self, provider, kind, fetched):
        writer = {
            "employees": self._write_employees,
            "live": self._write_live,
            "history": self._write_history,
            "visits": self._write_visits,
            "attendance": self._write_attendance,
            "geofences": self._write_geofences,
        }[kind]
        return writer(provider, fetched)

    def _fail_run(self, run, provider, exc):
        run.status = "failed"
        run.error_message = str(exc)
        self._log(provider, run, "sync_failed", "error",
                  f"{run.sync_type} sync failed: {exc}")

    # -------------------------------------------------------------- writers

    def _mappings(self, provider):
        """external_id -> employee_id for the provider's active mappings."""
        return dict(
            EmployeeProviderMapping.objects
            .filter(provider=provider, is_active=True)
            .values_list("external_id", "employee_id")
        )

    def _write_employees(self, provider, employees):
        """Refresh identity mappings; auto-match new ones by phone, then name."""
        existing = {
            m.external_id: m
            for m in EmployeeProviderMapping.objects.filter(provider=provider)
        }
        created = updated = skipped = 0
        unmatched = []
        now = timezone.now()

        for person in employees:
            mapping = existing.get(person.external_id)
            if mapping:
                mapping.external_name = person.name or mapping.external_name
                mapping.is_active = person.is_active
                mapping.last_seen_at = now
                mapping.save(update_fields=["external_name", "is_active",
                                            "last_seen_at", "updated_at"])
                updated += 1
                continue
            employee = self._match_employee(person)
            if employee is None:
                unmatched.append(f"{person.name or '?'} (id {person.external_id})")
                skipped += 1
                continue
            EmployeeProviderMapping.objects.create(
                provider=provider, employee=employee,
                external_id=person.external_id, external_name=person.name,
                is_active=person.is_active, last_seen_at=now,
            )
            created += 1

        if unmatched:
            self._log(
                provider, None, "mapping_changed", "warning",
                f"{len(unmatched)} provider employee(s) have no ERP match and need "
                f"manual mapping: {', '.join(unmatched[:20])}"
                + ("…" if len(unmatched) > 20 else ""),
            )
        return {"created": created, "updated": updated, "skipped": skipped}

    @staticmethod
    def _match_employee(person):
        """Unambiguous auto-match: phone (last 10 digits) first, then exact name.

        ``personal_contact`` is an integer column, so a 10-digit number is
        matched exactly (an Indian mobile stored without country code); the
        name fallback requires exactly one non-relieved hit. Ambiguity means
        no match — a wrong attribution is worse than a manual mapping.
        """
        digits = "".join(ch for ch in person.phone if ch.isdigit())[-10:]
        active = Employee.objects.exclude(relieve=True)
        if len(digits) == 10:
            matches = list(active.filter(personal_contact=int(digits))[:2])
            if len(matches) == 1:
                return matches[0]
        if person.name:
            matches = list(active.filter(full_name__iexact=person.name.strip())[:2])
            if len(matches) == 1:
                return matches[0]
        return None

    def _write_live(self, provider, positions):
        mappings = self._mappings(provider)
        offline_after = timedelta(minutes=self._settings.offline_after_minutes)
        now = timezone.now()
        created = updated = skipped = 0

        # Previous state per employee, for transition alerts (offline, GPS
        # off, geofence entry/exit). Loaded before any row is overwritten.
        previous = {
            row["employee_id"]: row
            for row in EmployeeLiveLocation.objects
            .filter(employee_id__in=mappings.values())
            .values("employee_id", "latitude", "longitude", "status", "gps_enabled",
                     "address", "speed_kmh", "battery_pct", "network")
        }
        alert_fences = list(EmployeeGeofence.objects.filter(
            is_active=True).filter(
            models.Q(alert_on_entry=True) | models.Q(alert_on_exit=True)))

        for position in positions:
            employee_id = mappings.get(position.external_employee_id)
            if employee_id is None:
                skipped += 1
                continue
            # Online-ness is judged by the freshest signal: vendors update
            # the GPS fix only on movement, but heartbeats keep flowing from
            # a stationary-yet-connected device.
            last_seen = max(
                value for value in (position.recorded_at, position.heartbeat_at)
                if value is not None
            )
            status = position.status
            if now - last_seen > offline_after:
                status = "offline"
            elif status == "unknown":
                # Fresh signal without an explicit vendor state: online.
                status = "online"
            prior = previous.get(employee_id)
            if self._settings.alerts_enabled:
                self._live_transition_alerts(
                    provider, employee_id, prior,
                    position, status, alert_fences,
                )
            _obj, was_created = EmployeeLiveLocation.objects.update_or_create(
                employee_id=employee_id,
                defaults={
                    "provider": provider,
                    "latitude": position.latitude,
                    "longitude": position.longitude,
                    "accuracy_m": position.accuracy_m,
                    "speed_kmh": self._carry_forward(position.speed_kmh, prior, "speed_kmh"),
                    "heading": position.heading,
                    "altitude_m": position.altitude_m,
                    "address": self._carry_forward(position.address, prior, "address"),
                    "battery_pct": self._carry_forward(position.battery_pct, prior, "battery_pct"),
                    "network": self._carry_forward(position.network, prior, "network"),
                    "gps_enabled": position.gps_enabled,
                    "status": status,
                    "recorded_at": position.recorded_at,
                    "heartbeat_at": position.heartbeat_at,
                },
            )
            created += 1 if was_created else 0
            updated += 0 if was_created else 1
        return {"created": created, "updated": updated, "skipped": skipped}

    @staticmethod
    def _carry_forward(new_value, prior, field):
        """Keep the last known value when this ping's vendor payload omits it.

        Not every device reports address/speed/battery/network on every fix
        (e.g. a stationary device may send a heartbeat with no reverse-geocoded
        address); overwriting with a blank would erase a value we already know.
        """
        if new_value not in (None, ""):
            return new_value
        return prior[field] if prior else new_value

    def _live_transition_alerts(self, provider, employee_id, previous,
                                position, new_status, alert_fences):
        """Emit alerts only on state *transitions*, never on steady state.

        A first sighting (no previous row) raises nothing — commissioning a
        provider must not flood the alert inbox.
        """
        if previous is None:
            return
        from .geo import haversine_km  # local import: avoids cycle at module load

        def alert(event, severity, message, geofence=None):
            TrackingLog.objects.create(
                log_type="alert", event=event, severity=severity,
                message=message, employee_id=employee_id, provider=provider,
                geofence=geofence,
            )

        name = Employee.objects.filter(pk=employee_id).values_list(
            "full_name", flat=True).first() or f"Employee {employee_id}"

        if new_status == "offline" and previous["status"] != "offline":
            alert("employee_offline", "warning", f"{name} went offline.")
        if previous["gps_enabled"] and not position.gps_enabled:
            alert("gps_disabled", "warning", f"{name} disabled GPS on the device.")
        if (position.network or "").lower() in ("none", "no_network", "offline") :
            if previous["status"] != "offline":
                alert("no_internet", "info", f"{name} has no internet connectivity.")

        for fence in alert_fences:
            was_inside = haversine_km(
                previous["latitude"], previous["longitude"],
                fence.center_latitude, fence.center_longitude,
            ) * 1000 <= fence.radius_m
            is_inside = haversine_km(
                position.latitude, position.longitude,
                fence.center_latitude, fence.center_longitude,
            ) * 1000 <= fence.radius_m
            if is_inside and not was_inside and fence.alert_on_entry:
                alert("geofence_entry", "info",
                      f"{name} entered geofence '{fence.name}'.", geofence=fence)
            elif was_inside and not is_inside and fence.alert_on_exit:
                alert("geofence_exit", "warning",
                      f"{name} exited geofence '{fence.name}'.", geofence=fence)

    def _write_history(self, provider, points):
        mappings = self._mappings(provider)
        created = skipped = 0
        touched_days = set()  # (employee_id, local_date) needing route rebuild

        by_employee = {}
        for point in points:
            employee_id = mappings.get(point.external_employee_id)
            if employee_id is None:
                skipped += 1
                continue
            by_employee.setdefault(employee_id, []).append(point)

        # Provider point-IDs already stored: same ID = same point, even if the
        # vendor reports it with a shifted timestamp. Checked alongside the
        # (employee, recorded_at) key so the created/skipped counters stay
        # truthful instead of relying on ignore_conflicts to silently drop rows.
        batch_external_ids = [p.external_id for p in points if p.external_id]
        existing_external_ids = set(
            EmployeeLocationHistory.objects
            .filter(provider=provider, external_id__in=batch_external_ids)
            .values_list("external_id", flat=True)
        ) if batch_external_ids else set()

        for employee_id, employee_points in by_employee.items():
            times = [p.recorded_at for p in employee_points]
            existing = set(
                EmployeeLocationHistory.objects
                .filter(employee_id=employee_id,
                        recorded_at__gte=min(times), recorded_at__lte=max(times))
                .values_list("recorded_at", flat=True)
            )
            rows, seen = [], set()
            for point in employee_points:
                if (
                    point.recorded_at in existing
                    or point.recorded_at in seen
                    or (point.external_id and point.external_id in existing_external_ids)
                ):
                    skipped += 1
                    continue
                seen.add(point.recorded_at)
                rows.append(EmployeeLocationHistory(
                    employee_id=employee_id, provider=provider,
                    latitude=point.latitude, longitude=point.longitude,
                    accuracy_m=point.accuracy_m, speed_kmh=point.speed_kmh,
                    heading=point.heading, altitude_m=point.altitude_m,
                    battery_pct=point.battery_pct, event_type=point.event_type,
                    address=point.address, external_id=point.external_id,
                    recorded_at=point.recorded_at,
                ))
                touched_days.add(
                    (employee_id, timezone.localtime(point.recorded_at).date())
                )
            EmployeeLocationHistory.objects.bulk_create(
                rows, ignore_conflicts=True, batch_size=1000
            )
            created += len(rows)

        for employee_id, day in sorted(touched_days):
            self._route_builder.rebuild(
                Employee.objects.get(pk=employee_id), day, provider=provider
            )
        return {"created": created, "updated": 0, "skipped": skipped}

    def _write_visits(self, provider, visits):
        mappings = self._mappings(provider)
        created = updated = skipped = 0
        for visit in visits:
            employee_id = mappings.get(visit.external_employee_id)
            if employee_id is None or not visit.external_id:
                skipped += 1
                continue
            reference = visit.check_in_at or visit.check_out_at
            if reference is None:
                skipped += 1
                continue
            duration = None
            if visit.check_in_at and visit.check_out_at:
                duration = visit.check_out_at - visit.check_in_at
            _obj, was_created = EmployeeCustomerVisit.objects.update_or_create(
                provider=provider, external_id=visit.external_id,
                defaults={
                    "employee_id": employee_id,
                    "customer": self._match_customer(visit.customer_name),
                    "external_customer_name": visit.customer_name,
                    "visit_date": timezone.localtime(reference).date(),
                    "status": "completed" if visit.check_out_at else "in_progress",
                    "check_in_at": visit.check_in_at,
                    "check_out_at": visit.check_out_at,
                    "duration": duration,
                    "check_in_latitude": visit.check_in_latitude,
                    "check_in_longitude": visit.check_in_longitude,
                    "check_out_latitude": visit.check_out_latitude,
                    "check_out_longitude": visit.check_out_longitude,
                    "address": visit.address,
                    "remarks": visit.remarks,
                    "photo_url": visit.photo_url[:500],
                    "next_follow_up": (
                        timezone.localtime(visit.next_follow_up).date()
                        if visit.next_follow_up else None
                    ),
                },
            )
            created += 1 if was_created else 0
            updated += 0 if was_created else 1
        return {"created": created, "updated": updated, "skipped": skipped}

    @staticmethod
    def _match_customer(customer_name):
        """Exact-name CRM match; ambiguity or no match leaves the FK empty."""
        name = (customer_name or "").strip()
        if not name:
            return None
        matches = list(Customer.objects.filter(name__iexact=name)[:2])
        return matches[0] if len(matches) == 1 else None

    def _write_attendance(self, provider, events):
        """Store GPS check-in/out events, then fold them into GPS attendance.

        The typed history rows keep the raw evidence; the attendance service
        (idempotent per employee/day) maintains ``EmployeeGpsAttendance`` and
        — per the approval policy — ``hr.Attendance``.
        """
        mappings = self._mappings(provider)
        attendance_service = (
            AttendanceIntegrationService(self._settings)
            if self._settings.attendance_sync_enabled else None
        )
        employees_by_id = {}
        created = skipped = updated = 0

        for event in events:
            employee_id = mappings.get(event.external_employee_id)
            if employee_id is None or event.latitude is None or event.longitude is None:
                skipped += 1
                continue
            _obj, was_created = EmployeeLocationHistory.objects.get_or_create(
                employee_id=employee_id, recorded_at=event.occurred_at,
                defaults={
                    "provider": provider,
                    "latitude": event.latitude, "longitude": event.longitude,
                    "event_type": event.event, "address": event.address,
                },
            )
            created += 1 if was_created else 0
            skipped += 0 if was_created else 1

            if attendance_service is not None:
                employee = employees_by_id.get(employee_id)
                if employee is None:
                    employee = Employee.objects.get(pk=employee_id)
                    employees_by_id[employee_id] = employee
                attendance_service.apply_event(employee, provider, event)
                updated += 1
        return {"created": created, "updated": updated, "skipped": skipped}

    def _write_geofences(self, provider, fences):
        created = updated = 0
        for fence in fences:
            geofence_type = fence.geofence_type if fence.geofence_type in _GEOFENCE_TYPES else "other"
            _obj, was_created = EmployeeGeofence.objects.update_or_create(
                provider=provider, external_id=fence.external_id,
                defaults={
                    "name": fence.name,
                    "geofence_type": geofence_type,
                    "center_latitude": fence.latitude,
                    "center_longitude": fence.longitude,
                    "radius_m": fence.radius_m,
                    "address": fence.address,
                },
            )
            created += 1 if was_created else 0
            updated += 0 if was_created else 1
        return {"created": created, "updated": updated, "skipped": 0}

    # -------------------------------------------------------------- helpers

    @staticmethod
    def _mark_provider(provider, ok, error=""):
        provider.last_sync_status = "ok" if ok else "error"
        provider.last_error = error
        if ok:
            provider.last_synced_at = timezone.now()
        provider.save(update_fields=["last_sync_status", "last_error", "last_synced_at"])

    @staticmethod
    def _log(provider, run, event, severity, message):
        TrackingLog.objects.create(
            log_type="sync", event=event, severity=severity,
            message=message, provider=provider, sync_run=run,
        )
