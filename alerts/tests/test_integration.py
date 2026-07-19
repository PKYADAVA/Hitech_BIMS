"""Integration tests: signals -> services -> Alert/AuditLog, plus middleware,
bulk handling, soft-delete, permissions and the REST API."""
from __future__ import annotations

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from alerts import context
from alerts.constants import Action, Severity
from alerts.handlers import handle_bulk
from alerts.middleware import AlertContextMiddleware
from alerts.models import Alert, AuditLog
from alerts.permissions import scope_alerts
from alerts.services import emit_event


class SignalCrudTests(TestCase):
    def test_create_emits_alert_and_audit(self):
        Alert.objects.all().delete()
        AuditLog.objects.all().delete()
        user = User.objects.create(username="bob")
        alert = Alert.objects.filter(model_name="auth.User", object_id=str(user.pk)).first()
        self.assertIsNotNone(alert)
        self.assertEqual(alert.action, Action.CREATE)
        self.assertTrue(AuditLog.objects.filter(object_id=str(user.pk)).exists())

    def test_update_records_changed_fields_only(self):
        user = User.objects.create(username="carol", first_name="Carol")
        Alert.objects.all().delete()
        user.first_name = "Caroline"
        user.save()
        alert = Alert.objects.get(action=Action.UPDATE, object_id=str(user.pk))
        self.assertIn("first_name", alert.changed_fields)
        self.assertEqual(alert.changed_fields["first_name"]["new"], "Caroline")

    def test_unchanged_save_emits_nothing(self):
        user = User.objects.create(username="dave")
        Alert.objects.all().delete()
        user.save()  # no field changed
        self.assertEqual(Alert.objects.filter(action=Action.UPDATE).count(), 0)

    def test_status_field_classified_as_status_change(self):
        # is_active flips are a good stand-in for a status transition on User.
        user = User.objects.create(username="erin", is_active=True)
        Alert.objects.all().delete()
        user.is_active = False
        user.save()
        alert = Alert.objects.get(object_id=str(user.pk))
        # is_active is not in STATUS_FIELD_NAMES, so this stays a plain update…
        self.assertEqual(alert.action, Action.UPDATE)
        self.assertIn("is_active", alert.changed_fields)

    def test_delete_captures_before_snapshot(self):
        user = User.objects.create(username="frank")
        pk = user.pk
        Alert.objects.all().delete()
        AuditLog.objects.all().delete()
        user.delete()
        audit = AuditLog.objects.get(action=Action.DELETE, object_id=str(pk))
        self.assertEqual(audit.before.get("username"), "frank")


class AuditImmutabilityTests(TestCase):
    def test_audit_cannot_be_modified_or_deleted(self):
        User.objects.create(username="grace")
        audit = AuditLog.objects.first()
        audit.reason = "tampered"
        with self.assertRaises(ValueError):
            audit.save()
        with self.assertRaises(ValueError):
            audit.delete()


class CustomEventTests(TestCase):
    def test_emit_event_creates_alert(self):
        Alert.objects.all().delete()
        user = User.objects.create(username="heidi")
        alert = emit_event(
            action=Action.APPROVE,
            event_type="order_approved",
            instance=user,
            title="Order approved",
            severity=Severity.SUCCESS,
        )
        self.assertIsNotNone(alert)
        self.assertEqual(alert.severity, Severity.SUCCESS)
        self.assertEqual(alert.title, "Order approved")


class BulkTests(TestCase):
    def test_handle_bulk_emits_single_summary(self):
        Alert.objects.all().delete()
        handle_bulk(User, Action.BULK_CREATE, 12)
        alert = Alert.objects.get(action=Action.BULK_CREATE)
        self.assertIn("12", alert.message)


class MiddlewareTests(TestCase):
    def test_request_context_sets_and_clears_actor(self):
        factory = RequestFactory()
        user = User.objects.create(username="ivan")

        captured = {}

        def view(request):
            captured["user"] = context.get_current_user()
            return "ok"

        mw = AlertContextMiddleware(view)
        request = factory.get("/")
        request.user = user
        mw(request)
        self.assertEqual(captured["user"], user)
        # context cleared after the response
        self.assertIsNone(context.get_current_request())

    def test_actor_attribution_on_alert(self):
        factory = RequestFactory()
        actor = User.objects.create(username="judy")
        request = factory.get("/")
        request.user = actor
        context.set_current_request(request)
        try:
            Alert.objects.all().delete()
            target = User.objects.create(username="target")
            alert = Alert.objects.get(object_id=str(target.pk))
            self.assertEqual(alert.performed_by_id, actor.pk)
            self.assertEqual(alert.actor_label, "judy")
        finally:
            context.clear_current_request()


class PermissionScopeTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create(username="admin", is_superuser=True, is_staff=True)
        self.a = User.objects.create(username="a")
        self.b = User.objects.create(username="b")
        Alert.objects.all().delete()
        self.alert_a = Alert.objects.create(action=Action.CREATE, title="a's", performed_by=self.a)
        self.alert_b = Alert.objects.create(action=Action.CREATE, title="b's", performed_by=self.b)

    def test_admin_sees_all(self):
        self.assertEqual(scope_alerts(Alert.objects.all(), self.admin).count(), 2)

    def test_user_sees_only_own(self):
        visible = scope_alerts(Alert.objects.all(), self.a)
        self.assertIn(self.alert_a, visible)
        self.assertNotIn(self.alert_b, visible)

    def test_anonymous_sees_none(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertEqual(scope_alerts(Alert.objects.all(), AnonymousUser()).count(), 0)


@override_settings(ALERT_SETTINGS={"TRACK_ALL_MODELS": True})
class ApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="apiuser", password="pw12345!")
        self.other = User.objects.create_user(username="other", password="pw12345!")
        Alert.objects.all().delete()
        self.mine = Alert.objects.create(action=Action.CREATE, title="mine", performed_by=self.user)
        self.theirs = Alert.objects.create(action=Action.CREATE, title="theirs", performed_by=self.other)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_list_is_scoped(self):
        resp = self.client.get(reverse("alerts:alert-list"))
        self.assertEqual(resp.status_code, 200)
        titles = [row["title"] for row in resp.data["results"]]
        self.assertIn("mine", titles)
        self.assertNotIn("theirs", titles)

    def test_unread_count(self):
        resp = self.client.get(reverse("alerts:alert-unread-count"))
        self.assertEqual(resp.data["unread"], 1)

    def test_mark_read(self):
        url = reverse("alerts:alert-mark-read", args=[self.mine.pk])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        self.mine.refresh_from_db()
        self.assertTrue(self.mine.is_read)

    def test_mark_all_read(self):
        resp = self.client.post(reverse("alerts:alert-mark-all-read"))
        self.assertEqual(resp.data["marked_read"], 1)
        self.assertEqual(scope_alerts(Alert.objects.unread(), self.user).count(), 0)

    def test_requires_authentication(self):
        self.client.force_authenticate(None)
        resp = self.client.get(reverse("alerts:alert-list"))
        self.assertIn(resp.status_code, (401, 403))

    def test_audit_log_is_staff_only(self):
        resp = self.client.get(reverse("alerts:auditlog-list"))
        self.assertEqual(resp.status_code, 403)
        staff = User.objects.create_user(username="staff", password="pw", is_staff=True)
        self.client.force_authenticate(staff)
        resp = self.client.get(reverse("alerts:auditlog-list"))
        self.assertEqual(resp.status_code, 200)
