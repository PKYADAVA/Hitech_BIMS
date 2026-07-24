"""Tests for the mobile API v1: auth, envelope, pagination, filtering, health.

The response *envelope* is applied by the renderer at content-render time, so
assertions read ``resp.json()`` (the final body) rather than ``resp.data`` (the
pre-render serializer/exception payload). Auth-flow tests use real JWT login so
the issue/refresh/blacklist path is genuinely exercised.
"""
from __future__ import annotations

from django.contrib.auth.models import User
from rest_framework.test import APITestCase


class HealthTests(APITestCase):
    def test_health_is_public_and_enveloped(self):
        resp = self.client.get("/api/v1/health")
        body = resp.json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(body["success"])
        self.assertEqual(body["data"]["status"], "ok")

    def test_ready_checks_database(self):
        resp = self.client.get("/api/v1/ready")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["database"], "up")


class AuthFlowTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="mobile", password="Str0ngPass!", email="m@x.com"
        )

    def _login(self):
        return self.client.post(
            "/api/v1/auth/login", {"username": "mobile", "password": "Str0ngPass!"}
        ).json()["data"]

    def test_login_returns_tokens_and_user(self):
        resp = self.client.post(
            "/api/v1/auth/login", {"username": "mobile", "password": "Str0ngPass!"}
        )
        body = resp.json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(body["success"])
        self.assertIn("access", body["data"])
        self.assertIn("refresh", body["data"])
        self.assertEqual(body["data"]["user"]["username"], "mobile")

    def test_login_bad_credentials_is_enveloped_error(self):
        resp = self.client.post(
            "/api/v1/auth/login", {"username": "mobile", "password": "wrong"}
        )
        body = resp.json()
        self.assertEqual(resp.status_code, 401)
        self.assertFalse(body["success"])
        self.assertEqual(body["error"]["code"], "not_authenticated")

    def test_refresh_and_logout(self):
        tokens = self._login()
        r = self.client.post("/api/v1/auth/refresh", {"refresh": tokens["refresh"]})
        self.assertEqual(r.status_code, 200)
        self.assertIn("access", r.json()["data"])

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        out = self.client.post("/api/v1/auth/logout", {"refresh": tokens["refresh"]})
        self.assertEqual(out.status_code, 200)

    def test_me(self):
        tokens = self._login()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        resp = self.client.get("/api/v1/auth/me")
        self.assertEqual(resp.json()["data"]["username"], "mobile")


class ResourceTests(APITestCase):
    """Domain-resource behaviour via a JWT-authenticated client."""

    def setUp(self):
        self.user = User.objects.create_user(username="u", password="Str0ngPass!")
        self.client.force_authenticate(self.user)

    def test_list_requires_auth(self):
        self.client.force_authenticate(None)
        resp = self.client.get("/api/v1/broiler/farmer-groups/")
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"]["code"], "not_authenticated")

    def test_list_is_enveloped_and_paginated(self):
        resp = self.client.get("/api/v1/broiler/farmer-groups/")
        body = resp.json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(body["success"])
        self.assertIsInstance(body["data"], list)
        self.assertEqual(body["meta"]["pagination"]["type"], "page")

    def test_transaction_feed_uses_cursor_pagination(self):
        resp = self.client.get("/api/v1/broiler/daily-entries/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["meta"]["pagination"]["type"], "cursor")

    def test_readonly_master_rejects_write(self):
        resp = self.client.post("/api/v1/broiler/farmer-groups/", {})
        self.assertEqual(resp.status_code, 405)
        self.assertEqual(resp.json()["error"]["code"], "method_not_allowed")

    def test_validation_error_is_field_mapped(self):
        resp = self.client.post("/api/v1/hatchery/egg-purchase-items/", {})
        body = resp.json()
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(body["success"])
        self.assertEqual(body["error"]["code"], "validation_error")
        self.assertIsInstance(body["error"]["fields"], dict)

    def test_generic_field_filter(self):
        from broiler.models import Region

        Region.objects.create(description="North")
        Region.objects.create(description="South")
        resp = self.client.get("/api/v1/broiler/regions/?description=North")
        names = [row["description"] for row in resp.json()["data"]]
        self.assertEqual(names, ["North"])
