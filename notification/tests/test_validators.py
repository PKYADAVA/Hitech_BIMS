"""Tests for phone/message validation and masking."""

from django.test import SimpleTestCase

from notification.exceptions import SmsValidationError
from notification.validators import mask_phone, normalize_phone, validate_message


class NormalizePhoneTests(SimpleTestCase):
    def test_prepends_country_code_to_national_number(self):
        self.assertEqual(normalize_phone("9876543210", "91"), "919876543210")

    def test_keeps_existing_country_code_with_plus(self):
        self.assertEqual(normalize_phone("+91 98765 43210", "91"), "919876543210")

    def test_strips_formatting_characters(self):
        self.assertEqual(normalize_phone("(987)-654-3210", "91"), "919876543210")

    def test_handles_double_zero_international_prefix(self):
        self.assertEqual(normalize_phone("00919876543210", "91"), "919876543210")

    def test_rejects_empty(self):
        with self.assertRaises(SmsValidationError):
            normalize_phone("", "91")

    def test_rejects_non_numeric(self):
        with self.assertRaises(SmsValidationError):
            normalize_phone("98abc43210", "91")

    def test_rejects_too_long(self):
        with self.assertRaises(SmsValidationError):
            normalize_phone("+1234567890123456", "91")


class ValidateMessageTests(SimpleTestCase):
    def test_strips_and_returns(self):
        self.assertEqual(validate_message("  hello  ", 100), "hello")

    def test_rejects_empty(self):
        with self.assertRaises(SmsValidationError):
            validate_message("   ", 100)

    def test_rejects_too_long(self):
        with self.assertRaises(SmsValidationError):
            validate_message("x" * 11, 10)


class MaskPhoneTests(SimpleTestCase):
    def test_masks_all_but_last_four(self):
        self.assertEqual(mask_phone("919876543210"), "********3210")

    def test_empty_returns_empty(self):
        self.assertEqual(mask_phone(""), "")
