"""Tests for template resolution and rendering (catalogue + DB overrides)."""

from django.test import TestCase

from notification.exceptions import SmsValidationError
from notification.models import SmsTemplate
from notification.services.sms_service import SmsService
from notification.services.template_service import SmsTemplateService, extract_placeholders
from notification.templates_catalog import DEFAULT_TEMPLATES
from notification.tests.factories import make_config


class TemplateRenderingTests(TestCase):
    def test_renders_catalogue_default(self):
        message = SmsTemplateService().render(
            "user.otp", {"otp": "123456", "validity": "10"}
        )
        self.assertIn("123456", message)
        self.assertIn("10 minutes", message)

    def test_missing_placeholder_raises(self):
        with self.assertRaises(SmsValidationError):
            SmsTemplateService().render("user.otp", {"otp": "123456"})

    def test_unknown_key_raises(self):
        with self.assertRaises(SmsValidationError):
            SmsTemplateService().render("does.not.exist", {})

    def test_every_catalogue_template_renders_with_its_placeholders(self):
        service = SmsTemplateService()
        for template in DEFAULT_TEMPLATES:
            context = {name: "x" for name in extract_placeholders(template.body)}
            rendered = service.render(template.key, context)
            self.assertTrue(rendered)


class TemplateDatabaseOverrideTests(TestCase):
    def test_active_db_template_overrides_catalogue(self):
        SmsTemplate.objects.create(
            key="user.otp", module="user", name="OTP",
            body="Override {otp}", is_active=True,
        )
        message = SmsTemplateService().render("user.otp", {"otp": "999"})
        self.assertEqual(message, "Override 999")

    def test_inactive_db_template_falls_back_to_catalogue(self):
        SmsTemplate.objects.create(
            key="user.otp", module="user", name="OTP",
            body="Override {otp}", is_active=False,
        )
        message = SmsTemplateService().render(
            "user.otp", {"otp": "999", "validity": "5"}
        )
        self.assertIn("Your Hi Tech Farms OTP is 999", message)

    def test_send_template_end_to_end_in_mock_mode(self):
        service = SmsService(config=make_config(mock=True))
        result = service.send_template(
            "user.otp", "9876543210", {"otp": "123456", "validity": "10"}
        )
        self.assertTrue(result.success)

    def test_send_template_missing_placeholder_returns_invalid(self):
        service = SmsService(config=make_config(mock=True))
        result = service.send_template("user.otp", "9876543210", {"otp": "1"})
        self.assertFalse(result.success)
        self.assertEqual(result.status, "invalid")

    def test_send_template_passes_dlt_id_to_provider(self):
        SmsTemplate.objects.create(
            key="broiler.dispatch", module="broiler", name="Dispatch",
            body="Dispatched to {place}", dlt_template_id="99887766", is_active=True,
        )
        service = SmsService(config=make_config(mock=True))
        result = service.send_template("broiler.dispatch", "9876543210", {"place": "X"})
        self.assertTrue(result.success)
        self.assertEqual(service._provider.outbox[-1]["options"]["dlt_template_id"], "99887766")
