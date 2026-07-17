# pylint: disable=no-member
"""End-to-end tests of the background sync engine against the mock adapter."""

from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from hr.models import Employee
from sales.models import Customer

from tracking.dtos import ConnectionTestResult
from tracking.exceptions import TrackingAuthError, TrackingTransientError
from tracking.models import (
    EmployeeCustomerVisit,
    EmployeeGeofence,
    EmployeeLiveLocation,
    EmployeeLocationHistory,
    EmployeeProviderMapping,
    EmployeeRoute,
    SyncLock,
    TrackingLog,
    TrackingProvider,
    TrackingSettings,
    TrackingSync,
)
from tracking.providers.mock import MockProviderAdapter
from tracking.services.sync_service import SyncService


def make_mock_provider(**kwargs):
    defaults = {
        "name": "Mock GPS",
        "provider_type": "mock",
        "api_url": "https://mock.invalid",
    }
    defaults.update(kwargs)
    return TrackingProvider.objects.create(**defaults)


class SyncEngineTests(TestCase):
    """Full cycle over the mock adapter's deterministic dataset."""

    def setUp(self):
        self.provider = make_mock_provider()
        # Phone matches mock EXT-1; EXT-2 matches by exact name.
        self.employee_one = Employee.objects.create(
            full_name="Anyone", personal_contact=9000000001
        )
        self.employee_two = Employee.objects.create(full_name="Mock Employee Two")
        self.service = SyncService(sleep=lambda seconds: None)

    def test_directory_sync_auto_matches_by_phone_and_name(self):
        runs = self.service.sync_provider(self.provider, kinds=["employees"])
        self.assertEqual(runs[0].status, "success")
        mappings = {
            m.external_id: m.employee_id
            for m in EmployeeProviderMapping.objects.filter(provider=self.provider)
        }
        self.assertEqual(mappings["EXT-1"], self.employee_one.pk)
        self.assertEqual(mappings["EXT-2"], self.employee_two.pk)

    def test_unmatched_provider_employee_logged_not_crashed(self):
        self.employee_two.delete()
        runs = self.service.sync_provider(self.provider, kinds=["employees"])
        self.assertEqual(runs[0].records_skipped, 1)
        warning = TrackingLog.objects.get(event="mapping_changed")
        self.assertIn("EXT-2", warning.message)

    def test_full_cycle_populates_all_tables(self):
        runs = self.service.sync_provider(self.provider)
        self.assertEqual({run.status for run in runs}, {"success"})

        self.assertEqual(EmployeeLiveLocation.objects.count(), 2)
        self.assertGreater(EmployeeLocationHistory.objects.count(), 0)
        self.assertEqual(EmployeeGeofence.objects.count(), 1)
        self.assertEqual(EmployeeCustomerVisit.objects.count(), 1)

        # Route summaries were rebuilt from the ingested pings.
        route = EmployeeRoute.objects.get(employee=self.employee_one)
        self.assertGreater(route.total_distance_km, 0)
        self.assertGreater(route.points.count(), 0)

        self.provider.refresh_from_db()
        self.assertEqual(self.provider.last_sync_status, "ok")

    def test_second_run_is_idempotent(self):
        self.service.sync_provider(self.provider)
        history_count = EmployeeLocationHistory.objects.count()
        visit_count = EmployeeCustomerVisit.objects.count()

        second_runs = self.service.sync_provider(self.provider)
        self.assertNotIn("failed", {run.status for run in second_runs})
        self.assertEqual(EmployeeCustomerVisit.objects.count(), visit_count)
        # The re-fetched overlap window is deduplicated, not re-inserted:
        # the table grew by exactly what the runs report as created (history
        # pings + attendance events, which also land in this table).
        created = sum(r.records_created for r in second_runs
                      if r.sync_type in ("history", "attendance"))
        self.assertEqual(
            EmployeeLocationHistory.objects.count(), history_count + created,
        )

    def test_incremental_window_resumes_from_cursor(self):
        self.service.sync_provider(self.provider, kinds=["history"])
        first = TrackingSync.objects.get(sync_type="history")
        second_service = SyncService(sleep=lambda seconds: None)
        second_service.sync_provider(self.provider, kinds=["history"])
        # By pk, not started_at: two runs can share a timestamp within one
        # Windows clock tick, making latest("started_at") ambiguous.
        second = TrackingSync.objects.filter(sync_type="history").exclude(pk=first.pk).get()
        self.assertEqual(
            second.window_start, first.window_end - timedelta(minutes=5)
        )

    def test_visit_customer_matched_by_exact_name(self):
        Customer.objects.create(name="Mock Customer")
        self.service.sync_provider(self.provider, kinds=["employees", "visits"])
        visit = EmployeeCustomerVisit.objects.get()
        self.assertIsNotNone(visit.customer)
        self.assertEqual(visit.external_customer_name, "Mock Customer")

    def test_visit_without_crm_match_kept_with_name(self):
        self.service.sync_provider(self.provider, kinds=["employees", "visits"])
        visit = EmployeeCustomerVisit.objects.get()
        self.assertIsNone(visit.customer)
        self.assertEqual(visit.external_customer_name, "Mock Customer")


class SyncFailureTests(TestCase):
    def setUp(self):
        self.provider = make_mock_provider()
        Employee.objects.create(full_name="Mock Employee One",
                                personal_contact=9000000001)

    def test_transient_error_retries_then_succeeds(self):
        calls = {"count": 0}

        class FlakyAdapter(MockProviderAdapter):
            def fetch_employees(self):
                calls["count"] += 1
                if calls["count"] == 1:
                    raise TrackingTransientError("blip")
                return super().fetch_employees()

        service = SyncService(adapter_factory=lambda p: FlakyAdapter(p),
                              sleep=lambda seconds: None)
        runs = service.sync_provider(self.provider, kinds=["employees"])
        self.assertEqual(runs[0].status, "success")
        self.assertEqual(runs[0].retry_count, 1)

    def test_auth_error_on_directory_aborts_provider(self):
        class RejectedAdapter(MockProviderAdapter):
            def fetch_employees(self):
                raise TrackingAuthError("bad key")

        service = SyncService(adapter_factory=lambda p: RejectedAdapter(p),
                              sleep=lambda seconds: None)
        runs = service.sync_provider(self.provider)  # all kinds requested
        self.assertEqual(len(runs), 0)  # aborted before any later kind ran
        self.assertEqual(TrackingSync.objects.count(), 1)  # only the failed run
        self.provider.refresh_from_db()
        self.assertEqual(self.provider.last_sync_status, "error")
        self.assertIn("bad key", self.provider.last_error)

    def test_auth_error_on_other_kind_is_a_module_gap_not_an_abort(self):
        """Per-module licence rejections must not poison the provider."""
        class UnlicensedVisitsAdapter(MockProviderAdapter):
            def fetch_visits(self, window_start, window_end):
                raise TrackingAuthError("You are not authorized to perform this!")

        service = SyncService(adapter_factory=lambda p: UnlicensedVisitsAdapter(p),
                              sleep=lambda seconds: None)
        runs = service.sync_provider(self.provider)
        by_kind = {run.sync_type: run.status for run in runs}
        self.assertEqual(by_kind["visits"], "failed")
        self.assertEqual(by_kind["live"], "success")
        self.assertEqual(by_kind["geofences"], "success")  # ran after visits
        self.provider.refresh_from_db()
        self.assertEqual(self.provider.last_sync_status, "ok")
        self.assertIn("visits", self.provider.last_error)  # gap noted, not fatal

    def test_permanent_error_fails_run_but_continues_other_kinds(self):
        class BrokenVisitsAdapter(MockProviderAdapter):
            def fetch_visits(self, window_start, window_end):
                raise TrackingTransientError("still down")

        service = SyncService(adapter_factory=lambda p: BrokenVisitsAdapter(p),
                              sleep=lambda seconds: None)
        runs = service.sync_provider(self.provider)
        by_kind = {run.sync_type: run.status for run in runs}
        self.assertEqual(by_kind["visits"], "failed")
        self.assertEqual(by_kind["live"], "success")
        self.assertTrue(TrackingLog.objects.filter(event="sync_failed").exists())


class SyncCommandTests(TestCase):
    def setUp(self):
        make_mock_provider()
        Employee.objects.create(full_name="Mock Employee One",
                                personal_contact=9000000001)

    def _call(self, *args):
        out = StringIO()
        call_command("sync_tracking", *args, stdout=out)
        return out.getvalue()

    def test_disabled_module_is_a_noop(self):
        output = self._call()
        self.assertIn("disabled", output)
        self.assertEqual(TrackingSync.objects.count(), 0)

    def test_enabled_module_runs_and_reports(self):
        settings_row = TrackingSettings.get_solo()
        settings_row.enabled = True
        settings_row.save()
        output = self._call("--kinds", "employees,live", "--trigger", "manual")
        self.assertIn("Completed 2 sync run(s), 0 failed.", output)
        self.assertEqual(
            set(TrackingSync.objects.values_list("triggered_by", flat=True)),
            {"manual"},
        )

    def test_lock_prevents_overlapping_runs(self):
        settings_row = TrackingSettings.get_solo()
        settings_row.enabled = True
        settings_row.save()
        SyncLock.objects.create(pk=1, is_running=True, started_at=timezone.now())
        output = self._call()
        self.assertIn("already in progress", output)
        self.assertEqual(TrackingSync.objects.count(), 0)

    def test_stale_lock_is_taken_over(self):
        settings_row = TrackingSettings.get_solo()
        settings_row.enabled = True
        settings_row.save()
        SyncLock.objects.create(
            pk=1, is_running=True,
            started_at=timezone.now() - timedelta(minutes=30),
        )
        output = self._call("--kinds", "employees")
        self.assertIn("Completed", output)
        lock = SyncLock.objects.get(pk=1)
        self.assertFalse(lock.is_running)
