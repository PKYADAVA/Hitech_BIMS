"""Tests for the in-app SMS template management views."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from notification.models import SmsTemplate


class SmsTemplateViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("mgr", password="pw12345!")
        self.client.force_login(self.user)

    def test_page_renders_with_nav_and_table(self):
        response = self.client.get(reverse("sms_templates"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SMS Templates")
        self.assertContains(response, "sms-template-table")

    def test_page_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("sms_templates"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_list_returns_json(self):
        SmsTemplate.objects.create(key="user.otp", module="user", name="OTP", body="{otp}")
        response = self.client.get(reverse("sms_template_list"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["placeholders"], ["otp"])

    def test_create_template(self):
        response = self.client.post(reverse("sms_template_create"), {
            "key": "sales.custom", "module": "sales",
            "name": "Custom", "body": "Hi {name}", "description": "",
        })
        self.assertEqual(response.status_code, 201)
        self.assertTrue(SmsTemplate.objects.filter(key="sales.custom").exists())

    def test_create_rejects_duplicate_key(self):
        SmsTemplate.objects.create(key="user.otp", module="user", name="OTP", body="{otp}")
        response = self.client.post(reverse("sms_template_create"), {
            "key": "user.otp", "module": "user", "name": "Dup", "body": "x",
        })
        self.assertEqual(response.status_code, 400)

    def test_create_rejects_invalid_module(self):
        response = self.client.post(reverse("sms_template_create"), {
            "key": "x.y", "module": "nope", "name": "N", "body": "b",
        })
        self.assertEqual(response.status_code, 400)

    def test_update_template_keeps_key(self):
        tpl = SmsTemplate.objects.create(key="user.otp", module="user", name="OTP", body="{otp}")
        response = self.client.put(
            reverse("sms_template_edit", args=[tpl.id]),
            data='{"module": "user", "name": "Renamed", "body": "New {otp}", "description": "d"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        tpl.refresh_from_db()
        self.assertEqual(tpl.key, "user.otp")
        self.assertEqual(tpl.name, "Renamed")

    def test_toggle_active(self):
        tpl = SmsTemplate.objects.create(
            key="user.otp", module="user", name="OTP", body="{otp}", is_active=True,
        )
        response = self.client.post(reverse("sms_template_toggle_active", args=[tpl.id]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["is_active"])

    def test_delete_template(self):
        tpl = SmsTemplate.objects.create(key="user.otp", module="user", name="OTP", body="{otp}")
        response = self.client.delete(reverse("sms_template_delete", args=[tpl.id]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(SmsTemplate.objects.filter(id=tpl.id).exists())

    def test_send_template_mock_mode(self):
        tpl = SmsTemplate.objects.create(
            key="user.otp", module="user", name="OTP",
            body="Your OTP is {otp}", is_active=True,
        )
        with self.settings(SMS_ENABLED=True, SMS_MOCK=True):
            response = self.client.post(
                reverse("sms_template_send", args=[tpl.id]),
                {"phone": "9876543210", "var_otp": "123456"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])

    def test_send_template_requires_phone(self):
        tpl = SmsTemplate.objects.create(key="user.otp", module="user", name="OTP", body="{otp}")
        response = self.client.post(reverse("sms_template_send", args=[tpl.id]), {"var_otp": "1"})
        self.assertEqual(response.status_code, 400)

    def test_send_template_rejects_get(self):
        tpl = SmsTemplate.objects.create(key="user.otp", module="user", name="OTP", body="{otp}")
        response = self.client.get(reverse("sms_template_send", args=[tpl.id]))
        self.assertEqual(response.status_code, 400)
