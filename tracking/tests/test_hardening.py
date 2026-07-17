# pylint: disable=no-member
"""Phase 9 hardening: permission enforcement, webhook auth, transition alerts,
geofence and alert-inbox APIs."""

import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group as AuthGroup, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from hr.models import Employee
from user.models import GroupTabPermission

from tracking.dtos import LivePosition
from tracking.models import (  # noqa: F401 — EmployeeLiveLocation used in tests
    EmployeeGeofence,
    EmployeeLiveLocation,
    EmployeeProviderMapping,
    TrackingLog,
    TrackingProvider,
    TrackingSettings,
)
from tracking.services.sync_service import SyncService


class WebAccessEnforcementTests(TestCase):
    """The permission matrix must guard every tracking page and API."""

    def setUp(self):
        self.group = AuthGroup.objects.create(name="Restricted Staff")
        self.user = User.objects.create_user("restricted", password="pass12345")
        self.user.groups.add(self.group)
        # Any configured row activates the matrix for the user's groups;
        # granting only an unrelated tab means tracking stays denied.
        GroupTabPermission.objects.create(
            group=self.group, tab_code="employee_list", can_view=True)
        self.client.login(username="restricted", password="pass12345")

    def test_pages_redirect_home_without_permission(self):
        for name in ("tracking_dashboard", "tracking_attendance", "tracking_visits",
                     "tracking_routes", "tracking_reports", "tracking_geofences",
                     "tracking_alerts", "tracking_settings"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302, name)
            self.assertEqual(response.url, reverse("home"), name)

    def test_apis_denied_without_permission(self):
        # Non-GET and AJAX get a clean 403 from the middleware.
        response = self.client.post(
            reverse("api_tracking_sync_now"), "{}",
            content_type="application/json")
        self.assertEqual(response.status_code, 403)
        response = self.client.get(
            reverse("api_tracking_live"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 403)

    def test_granting_the_tab_opens_page_and_apis(self):
        GroupTabPermission.objects.create(
            group=self.group, tab_code="tracking_dashboard", can_view=True)
        self.assertEqual(
            self.client.get(reverse("tracking_dashboard")).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("api_tracking_live"),
                            HTTP_X_REQUESTED_WITH="XMLHttpRequest").status_code, 200)
        # Other tracking tabs stay locked.
        self.assertEqual(
            self.client.get(reverse("tracking_settings")).status_code, 302)


class WebhookTests(TestCase):
    def setUp(self):
        self.provider = TrackingProvider.objects.create(
            name="Mock", provider_type="mock", api_url="https://mock.invalid",
            webhook_secret="hook-secret-1",
        )
        self.url = reverse("api_tracking_webhook", args=[self.provider.pk])

    def _post(self, secret=None, body="{}"):
        headers = {"HTTP_X_WEBHOOK_SECRET": secret} if secret else {}
        return self.client.post(self.url, body,
                                content_type="application/json", **headers)

    def test_missing_or_wrong_secret_rejected_and_logged(self):
        self.assertEqual(self._post().status_code, 403)
        self.assertEqual(self._post(secret="wrong").status_code, 403)
        self.assertEqual(
            TrackingLog.objects.filter(event="webhook_rejected").count(), 2)

    def test_provider_without_configured_secret_always_rejects(self):
        self.provider.webhook_secret = ""
        self.provider.save()
        self.assertEqual(self._post(secret="").status_code, 403)

    def test_valid_secret_logs_and_triggers_live_sync(self):
        settings_row = TrackingSettings.get_solo()
        settings_row.enabled = True
        settings_row.save()
        Employee.objects.create(full_name="Mock Employee One",
                                personal_contact=9000000001)
        # Mapping exists so the triggered live sync writes a row.
        SyncService(sleep=lambda seconds: None).sync_provider(
            self.provider, kinds=["employees"])

        response = self._post(secret="hook-secret-1",
                              body=json.dumps({"event": "location_update"}))
        data = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data["synced"])
        self.assertTrue(TrackingLog.objects.filter(event="webhook_received").exists())
        # Only EXT-1 is mapped in this test; EXT-2's live position is skipped.
        self.assertEqual(EmployeeLiveLocation.objects.count(), 1)

    def test_disabled_module_receives_but_does_not_sync(self):
        response = self._post(secret="hook-secret-1")
        data = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(data["synced"])

    def test_oversized_payload_rejected(self):
        response = self._post(secret="hook-secret-1", body="x" * 150_000)
        self.assertEqual(response.status_code, 413)


class LiveTransitionAlertTests(TestCase):
    """Offline / GPS-off / geofence entry-exit alerts fire on transitions only."""

    def setUp(self):
        self.provider = TrackingProvider.objects.create(
            name="Mock", provider_type="mock", api_url="https://mock.invalid")
        self.employee = Employee.objects.create(full_name="Transition Tester")
        EmployeeProviderMapping.objects.create(
            provider=self.provider, employee=self.employee, external_id="EXT-1")
        self.fence = EmployeeGeofence.objects.create(
            name="Depot", geofence_type="office",
            center_latitude=Decimal("26.850000"),
            center_longitude=Decimal("80.950000"),
            radius_m=200, alert_on_entry=True, alert_on_exit=True,
        )
        self.service = SyncService(sleep=lambda seconds: None)

    def _position(self, lat, lng, status="online", gps=True):
        return LivePosition(
            external_employee_id="EXT-1", latitude=Decimal(lat),
            longitude=Decimal(lng), recorded_at=timezone.now(),
            status=status, gps_enabled=gps,
        )

    def test_first_sighting_never_alerts(self):
        self.service._write_live(self.provider, [self._position("26.85", "80.95")])
        self.assertEqual(TrackingLog.objects.filter(log_type="alert").count(), 0)

    def test_entry_and_exit_alerts(self):
        far, inside = ("26.90", "80.90"), ("26.8501", "80.9501")
        self.service._write_live(self.provider, [self._position(*far)])
        self.service._write_live(self.provider, [self._position(*inside)])
        self.assertEqual(TrackingLog.objects.filter(event="geofence_entry").count(), 1)
        self.service._write_live(self.provider, [self._position(*far)])
        self.assertEqual(TrackingLog.objects.filter(event="geofence_exit").count(), 1)
        # Staying outside raises nothing further.
        self.service._write_live(self.provider, [self._position("26.91", "80.89")])
        self.assertEqual(TrackingLog.objects.filter(event="geofence_exit").count(), 1)

    def test_offline_and_gps_disabled_transitions(self):
        self.service._write_live(self.provider, [self._position("26.90", "80.90")])
        self.service._write_live(self.provider,
                                 [self._position("26.90", "80.90", status="offline")])
        self.assertEqual(TrackingLog.objects.filter(event="employee_offline").count(), 1)
        self.service._write_live(self.provider,
                                 [self._position("26.90", "80.90", status="offline",
                                                 gps=False)])
        self.assertEqual(TrackingLog.objects.filter(event="gps_disabled").count(), 1)

    def test_fresh_heartbeat_keeps_stationary_employee_online(self):
        """Vendors refresh the GPS fix only on movement: an old fix with a
        current heartbeat (device connected, person stationary) is online."""
        stale_fix = timezone.now() - timedelta(hours=2)
        position = LivePosition(
            external_employee_id="EXT-1", latitude=Decimal("26.85"),
            longitude=Decimal("80.95"), recorded_at=stale_fix,
            heartbeat_at=timezone.now(), status="unknown",
        )
        self.service._write_live(self.provider, [position])
        row = EmployeeLiveLocation.objects.get(employee=self.employee)
        self.assertEqual(row.status, "online")
        self.assertIsNotNone(row.heartbeat_at)

        # Without the heartbeat the same fix is offline.
        stale_only = LivePosition(
            external_employee_id="EXT-1", latitude=Decimal("26.85"),
            longitude=Decimal("80.95"), recorded_at=stale_fix, status="unknown",
        )
        self.service._write_live(self.provider, [stale_only])
        row.refresh_from_db()
        self.assertEqual(row.status, "offline")

    def test_alerts_disabled_suppresses_everything(self):
        settings_row = TrackingSettings.get_solo()
        settings_row.alerts_enabled = False
        settings_row.save()
        service = SyncService(sleep=lambda seconds: None)
        service._write_live(self.provider, [self._position("26.90", "80.90")])
        service._write_live(self.provider,
                            [self._position("26.90", "80.90", status="offline")])
        self.assertEqual(TrackingLog.objects.filter(log_type="alert").count(), 0)


class GeofenceApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("tester", password="pass12345")
        self.client.login(username="tester", password="pass12345")

    def _post(self, payload):
        response = self.client.post(
            reverse("api_tracking_geofences"), json.dumps(payload),
            content_type="application/json")
        return response, json.loads(response.content)

    def test_create_update_deactivate(self):
        response, data = self._post({
            "name": "Head Office", "geofence_type": "office",
            "center_latitude": "26.85", "center_longitude": "80.95",
            "radius_m": 250, "alert_on_exit": True,
        })
        self.assertEqual(response.status_code, 200)
        fence_id = data["id"]

        _response, _data = self._post({"id": fence_id, "radius_m": 400})
        fence = EmployeeGeofence.objects.get(pk=fence_id)
        self.assertEqual(fence.radius_m, 400)
        self.assertTrue(fence.alert_on_exit)

        response = self.client.delete(
            reverse("api_tracking_geofences") + f"?id={fence_id}")
        self.assertEqual(response.status_code, 200)
        fence.refresh_from_db()
        self.assertFalse(fence.is_active)
        self.assertEqual(
            TrackingLog.objects.filter(event="geofence_changed").count(), 3)

    def test_invalid_latitude_rejected(self):
        response, data = self._post({
            "name": "Broken", "geofence_type": "office",
            "center_latitude": "126.85", "center_longitude": "80.95",
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", data)

    def test_page_renders(self):
        response = self.client.get(reverse("tracking_geofences"))
        self.assertContains(response, "Geofences")


class AlertsApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("tester", password="pass12345")
        self.client.login(username="tester", password="pass12345")
        self.employee = Employee.objects.create(full_name="Alerted One")
        for index in range(3):
            TrackingLog.objects.create(
                log_type="alert", event="employee_offline", severity="warning",
                message=f"offline {index}", employee=self.employee)
        TrackingLog.objects.create(  # non-alert rows never appear in the inbox
            log_type="sync", event="sync_failed", severity="error", message="x")

    def test_inbox_lists_only_alerts(self):
        response = self.client.get(reverse("api_tracking_alerts"))
        data = json.loads(response.content)
        self.assertEqual(data["total"], 3)
        self.assertEqual(data["tiles"]["unread"], 3)

    def test_mark_read_and_mark_all(self):
        first = TrackingLog.objects.filter(log_type="alert").first()
        response = self.client.post(
            reverse("api_tracking_alerts"),
            json.dumps({"action": "mark_read", "ids": [first.pk]}),
            content_type="application/json")
        self.assertEqual(json.loads(response.content)["updated"], 1)
        first.refresh_from_db()
        self.assertTrue(first.is_read)
        self.assertEqual(first.read_by, self.user)

        response = self.client.post(
            reverse("api_tracking_alerts"),
            json.dumps({"action": "mark_all_read"}),
            content_type="application/json")
        self.assertEqual(json.loads(response.content)["updated"], 2)
        self.assertEqual(TrackingLog.objects.filter(
            log_type="alert", is_read=False).count(), 0)

    def test_unread_filter(self):
        TrackingLog.objects.filter(log_type="alert").update(is_read=True)
        response = self.client.get(reverse("api_tracking_alerts"), {"unread": "1"})
        self.assertEqual(json.loads(response.content)["total"], 0)

    def test_page_renders(self):
        response = self.client.get(reverse("tracking_alerts"))
        self.assertContains(response, "Alert Inbox")
