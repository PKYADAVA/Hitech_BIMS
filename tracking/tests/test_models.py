# pylint: disable=no-member
"""Tests for the Employee Tracking schema and credential encryption."""

from datetime import timedelta

from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.utils import timezone

from hr.models import Employee

from tracking.crypto import CIPHERTEXT_PREFIX, decrypt, encrypt
from tracking.models import (
    EmployeeLocationHistory,
    EmployeeProviderMapping,
    TrackingProvider,
    TrackingSettings,
)


class CryptoTests(TestCase):
    """encrypt()/decrypt() round-trips and edge cases."""

    def test_round_trip(self):
        secret = "tlp-api-key-12345"
        stored = encrypt(secret)
        self.assertTrue(stored.startswith(CIPHERTEXT_PREFIX))
        self.assertNotIn(secret, stored)
        self.assertEqual(decrypt(stored), secret)

    def test_empty_values_pass_through(self):
        self.assertEqual(encrypt(""), "")
        self.assertEqual(decrypt(""), "")

    def test_legacy_plaintext_passes_through(self):
        # Values without the prefix (manually inserted rows) must not crash.
        self.assertEqual(decrypt("plain-value"), "plain-value")


class ProviderModelTests(TestCase):
    """Credential fields must be encrypted at rest and transparent in Python."""

    def _make_provider(self, **kwargs):
        defaults = {
            "name": "TrackWick Test",
            "provider_type": "trackolap",
            "api_url": "https://api.trackwick.com",
            "api_key": "super-secret-key",
            "extra_config": {"customer_id": "CID-1"},
        }
        defaults.update(kwargs)
        return TrackingProvider.objects.create(**defaults)

    def test_api_key_encrypted_at_rest(self):
        provider = self._make_provider()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT api_key FROM employee_tracking_provider WHERE id = %s",
                [provider.id],
            )
            raw = cursor.fetchone()[0]
        self.assertTrue(raw.startswith(CIPHERTEXT_PREFIX))
        self.assertNotIn("super-secret-key", raw)

    def test_api_key_transparent_on_read(self):
        provider = self._make_provider()
        reloaded = TrackingProvider.objects.get(pk=provider.pk)
        self.assertEqual(reloaded.api_key, "super-secret-key")

    def test_blank_credentials_stay_blank(self):
        provider = self._make_provider(name="No creds", api_key="")
        reloaded = TrackingProvider.objects.get(pk=provider.pk)
        self.assertEqual(reloaded.api_key, "")


class LocationHistoryDedupTests(TestCase):
    """Structural duplicate prevention on the high-volume pings table."""

    def setUp(self):
        self.employee = Employee.objects.create(full_name="Test Employee")
        self.when = timezone.now().replace(microsecond=0)

    def _ping(self, **kwargs):
        defaults = {
            "employee": self.employee,
            "latitude": "26.850000",
            "longitude": "80.949997",
            "recorded_at": self.when,
        }
        defaults.update(kwargs)
        return EmployeeLocationHistory.objects.create(**defaults)

    def test_duplicate_timestamp_rejected(self):
        self._ping()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._ping()

    def test_different_timestamp_allowed(self):
        self._ping()
        self._ping(recorded_at=self.when + timedelta(seconds=30))
        self.assertEqual(self.employee.location_history.count(), 2)

    def test_duplicate_external_id_rejected_per_provider(self):
        provider = TrackingProvider.objects.create(
            name="P1", api_url="https://api.example.com"
        )
        self._ping(provider=provider, external_id="ext-1")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._ping(
                provider=provider,
                external_id="ext-1",
                recorded_at=self.when + timedelta(minutes=1),
            )

    def test_blank_external_ids_do_not_collide(self):
        self._ping()
        self._ping(recorded_at=self.when + timedelta(minutes=1))  # both external_id=""


class MappingAndSettingsTests(TestCase):
    def test_mapping_unique_per_provider(self):
        provider = TrackingProvider.objects.create(
            name="P1", api_url="https://api.example.com"
        )
        employee = Employee.objects.create(full_name="Mapped Employee")
        EmployeeProviderMapping.objects.create(
            provider=provider, employee=employee, external_id="42"
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            EmployeeProviderMapping.objects.create(
                provider=provider, employee=employee, external_id="43"
            )

    def test_settings_singleton(self):
        first = TrackingSettings.get_solo()
        second = TrackingSettings.get_solo()
        self.assertEqual(first.pk, 1)
        self.assertEqual(second.pk, 1)
        self.assertEqual(TrackingSettings.objects.count(), 1)
        # Saving a "new" instance must still land on pk=1.
        rogue = TrackingSettings(enabled=True)
        rogue.save()
        self.assertEqual(TrackingSettings.objects.count(), 1)
        self.assertTrue(TrackingSettings.get_solo().enabled)
