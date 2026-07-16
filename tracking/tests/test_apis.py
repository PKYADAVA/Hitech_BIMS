# pylint: disable=no-member
"""Tests for the tracking JSON APIs and page views."""

import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from hr.models import Employee
from inventory.models import Warehouse

from tracking.models import (
    EmployeeLiveLocation,
    EmployeeProviderMapping,
    SyncLock,
    TrackingLog,
    TrackingProvider,
    TrackingSettings,
)


class ApiTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("tester", password="pass12345")
        self.client.login(username="tester", password="pass12345")

    def get_json(self, url, **params):
        response = self.client.get(url, params)
        return response, json.loads(response.content)

    def post_json(self, url, payload):
        response = self.client.post(
            url, json.dumps(payload), content_type="application/json"
        )
        return response, json.loads(response.content)


class AuthTests(ApiTestCase):
    def test_login_required_everywhere(self):
        self.client.logout()
        for name in ("tracking_dashboard", "tracking_settings", "api_tracking_live",
                     "api_tracking_settings", "api_tracking_providers"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302, name)
            self.assertIn("/login", response.url)


class LiveDashboardAPITests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.warehouse = Warehouse.objects.create(name="Main Branch")
        self.fresh_employee = Employee.objects.create(
            full_name="Fresh Fielder", warehouse=self.warehouse
        )
        self.stale_employee = Employee.objects.create(full_name="Stale Fielder")
        now = timezone.now()
        EmployeeLiveLocation.objects.create(
            employee=self.fresh_employee, latitude="26.85", longitude="80.95",
            status="moving", recorded_at=now,
        )
        EmployeeLiveLocation.objects.create(
            employee=self.stale_employee, latitude="26.90", longitude="80.90",
            status="online", recorded_at=now - timedelta(hours=3),
        )

    def test_effective_status_and_tiles(self):
        _response, data = self.get_json(reverse("api_tracking_live"))
        by_name = {e["name"]: e for e in data["employees"]}
        self.assertEqual(by_name["Fresh Fielder"]["status"], "moving")
        # Stale row is reported offline regardless of its stored status.
        self.assertEqual(by_name["Stale Fielder"]["status"], "offline")
        tiles = data["tiles"]
        self.assertEqual(tiles["moving"], 1)
        self.assertEqual(tiles["offline"], 1)
        self.assertEqual(tiles["total_employees"], 2)
        self.assertEqual(tiles["not_tracked"], 0)

    def test_filters(self):
        _response, data = self.get_json(
            reverse("api_tracking_live"), warehouse=self.warehouse.pk
        )
        self.assertEqual(len(data["employees"]), 1)
        _response, data = self.get_json(reverse("api_tracking_live"), q="Stale")
        self.assertEqual(len(data["employees"]), 1)
        _response, data = self.get_json(reverse("api_tracking_live"), status="offline")
        self.assertEqual(len(data["employees"]), 1)
        self.assertEqual(data["employees"][0]["name"], "Stale Fielder")


class SettingsAPITests(ApiTestCase):
    def test_round_trip_and_secret_handling(self):
        url = reverse("api_tracking_settings")
        _response, data = self.get_json(url)
        self.assertFalse(data["enabled"])

        response, data = self.post_json(url, {
            "enabled": True, "dashboard_refresh_seconds": 45,
            "google_maps_api_key": "g-key-123",
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data["enabled"])
        self.assertEqual(data["dashboard_refresh_seconds"], 45)
        self.assertTrue(data["has_google_maps_api_key"])
        self.assertNotIn("g-key-123", json.dumps(data))

        # Blank key on a later save keeps the stored one.
        _response, data = self.post_json(url, {"google_maps_api_key": ""})
        self.assertTrue(data["has_google_maps_api_key"])
        self.assertEqual(TrackingSettings.get_solo().google_maps_api_key, "g-key-123")
        self.assertTrue(TrackingLog.objects.filter(event="settings_changed").exists())


class ProviderAPITests(ApiTestCase):
    def _create_provider(self):
        return self.post_json(reverse("api_tracking_providers"), {
            "name": "TrackWick", "provider_type": "trackolap",
            "api_url": "https://api.trackwick.com/v1",
            "customer_id": "CID-1", "api_key": "secret-key-9",
        })

    def test_create_returns_no_secrets(self):
        response, data = self._create_provider()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data["has_api_key"])
        self.assertNotIn("secret-key-9", json.dumps(data))
        self.assertEqual(data["customer_id"], "CID-1")
        # Stored encrypted at rest.
        with connection.cursor() as cursor:
            cursor.execute("SELECT api_key FROM employee_tracking_provider WHERE id=%s",
                           [data["id"]])
            self.assertTrue(cursor.fetchone()[0].startswith("fernet:"))

    def test_blank_secret_keeps_stored_value(self):
        _response, created = self._create_provider()
        _response, updated = self.post_json(reverse("api_tracking_providers"), {
            "id": created["id"], "api_key": "", "priority": 3,
        })
        self.assertEqual(updated["priority"], 3)
        provider = TrackingProvider.objects.get(pk=created["id"])
        self.assertEqual(provider.api_key, "secret-key-9")

    def test_deactivate(self):
        _response, created = self._create_provider()
        response = self.client.delete(
            reverse("api_tracking_providers") + f"?id={created['id']}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(TrackingProvider.objects.get(pk=created["id"]).is_active)

    def test_connection_test_endpoint(self):
        provider = TrackingProvider.objects.create(
            name="Mock", provider_type="mock", api_url="https://mock.invalid"
        )
        _response, data = self.post_json(
            reverse("api_tracking_provider_test"), {"id": provider.pk}
        )
        self.assertTrue(data["success"])


class MappingAPITests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.provider = TrackingProvider.objects.create(
            name="Mock", provider_type="mock", api_url="https://mock.invalid"
        )
        self.employee = Employee.objects.create(full_name="Mappable One")

    def test_directory_listing_with_match_state(self):
        EmployeeProviderMapping.objects.create(
            provider=self.provider, employee=self.employee, external_id="EXT-1"
        )
        _response, data = self.get_json(
            reverse("api_tracking_mappings"), provider=self.provider.pk
        )
        people = {p["external_id"]: p for p in data["people"]}
        self.assertEqual(people["EXT-1"]["employee_id"], self.employee.pk)
        self.assertIsNone(people["EXT-2"]["employee_id"])

    def test_map_unmap_and_conflict(self):
        url = reverse("api_tracking_mappings")
        response, _data = self.post_json(url, {
            "provider": self.provider.pk, "external_id": "EXT-1",
            "employee_id": self.employee.pk,
        })
        self.assertEqual(response.status_code, 200)

        # Same employee to a second identity → clear 400.
        response, data = self.post_json(url, {
            "provider": self.provider.pk, "external_id": "EXT-2",
            "employee_id": self.employee.pk,
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("already mapped", data["error"])

        # Unmap.
        response, data = self.post_json(url, {
            "provider": self.provider.pk, "external_id": "EXT-1", "employee_id": None,
        })
        self.assertFalse(data["mapped"])
        self.assertFalse(EmployeeProviderMapping.objects.exists())


class SyncNowAPITests(ApiTestCase):
    def setUp(self):
        super().setUp()
        TrackingProvider.objects.create(
            name="Mock", provider_type="mock", api_url="https://mock.invalid"
        )
        Employee.objects.create(full_name="Mock Employee One",
                                personal_contact=9000000001)

    def test_disabled_module_rejected(self):
        response, data = self.post_json(reverse("api_tracking_sync_now"), {})
        self.assertEqual(response.status_code, 400)
        self.assertIn("disabled", data["error"])

    def test_manual_sync_runs(self):
        settings_row = TrackingSettings.get_solo()
        settings_row.enabled = True
        settings_row.save()
        response, data = self.post_json(
            reverse("api_tracking_sync_now"), {"kinds": ["employees", "live"]}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(data["runs"]), 2)
        self.assertEqual({run["status"] for run in data["runs"]}, {"success"})
        self.assertFalse(SyncLock.objects.get(pk=1).is_running)

    def test_locked_returns_409(self):
        settings_row = TrackingSettings.get_solo()
        settings_row.enabled = True
        settings_row.save()
        SyncLock.objects.create(pk=1, is_running=True, started_at=timezone.now())
        response, data = self.post_json(reverse("api_tracking_sync_now"), {})
        self.assertEqual(response.status_code, 409)
        self.assertIn("already running", data["error"])


class PageViewTests(ApiTestCase):
    def test_dashboard_renders(self):
        response = self.client.get(reverse("tracking_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Live Tracking Dashboard")
        self.assertContains(response, "api/tracking/live/")

    def test_settings_page_renders(self):
        response = self.client.get(reverse("tracking_settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "GPS Providers")
        self.assertContains(response, "Employee Mapping")
