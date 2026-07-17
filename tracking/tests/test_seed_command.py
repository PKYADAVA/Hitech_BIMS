# pylint: disable=no-member
"""Tests for seed_employees_from_provider (production HR commissioning helper)."""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from hr.models import Employee
from tracking.models import TrackingProvider


def make_mock_provider(**kwargs):
    defaults = {"name": "Mock GPS", "provider_type": "mock", "api_url": "https://mock.invalid"}
    defaults.update(kwargs)
    return TrackingProvider.objects.create(**defaults)


class SeedEmployeesCommandTests(TestCase):
    def setUp(self):
        make_mock_provider()

    def _call(self, *args):
        out = StringIO()
        call_command("seed_employees_from_provider", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_creates_nothing(self):
        output = self._call()
        self.assertIn("Would create 2 employee(s)", output)
        self.assertIn("Mock Employee One", output)
        self.assertIn("Preview only", output)
        self.assertEqual(Employee.objects.count(), 0)

    def test_apply_creates_employees(self):
        output = self._call("--apply")
        self.assertIn("Creating 2 employee(s)", output)
        self.assertEqual(Employee.objects.count(), 2)
        self.assertIn("Employee Mapping", output)

    def test_existing_employee_by_name_is_skipped_not_duplicated(self):
        Employee.objects.create(full_name="Mock Employee One")
        output = self._call("--apply")
        self.assertIn("exists : Mock Employee One", output)
        self.assertEqual(Employee.objects.filter(full_name="Mock Employee One").count(), 1)
        self.assertEqual(Employee.objects.count(), 2)  # the existing one + the new one

    def test_all_already_present_creates_nothing(self):
        Employee.objects.create(full_name="Mock Employee One")
        Employee.objects.create(full_name="Mock Employee Two")
        output = self._call("--apply")
        self.assertIn("Nothing to create", output)
        self.assertEqual(Employee.objects.count(), 2)

    def test_running_twice_is_idempotent(self):
        self._call("--apply")
        self._call("--apply")
        self.assertEqual(Employee.objects.count(), 2)
