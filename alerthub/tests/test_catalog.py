"""Catalogue integrity.

The catalogue is a promise: an entry with no ``requires`` claims something will
fire. These tests keep that promise honest, so the UI's "Ready" badge cannot
become a lie through a rename or a forgotten registration.
"""
from __future__ import annotations

from django.test import TestCase

from alerthub import detectors
from alerthub.catalog import BY_KEY, CATALOG, supported_keys
from alerthub.constants import Module, Priority


class CatalogTests(TestCase):
    def test_every_supported_rule_has_a_detector(self):
        missing = detectors.missing_detectors()
        self.assertEqual(
            missing, [],
            f"Catalogue marks these as ready but nothing implements them: {missing}",
        )

    def test_no_detector_without_a_supported_catalogue_entry(self):
        """The reverse: a detector for a key nobody can configure is dead code."""
        detectors.autodiscover()
        orphans = sorted(set(detectors.REGISTRY) - supported_keys())
        self.assertEqual(orphans, [])

    def test_keys_are_unique(self):
        keys = [spec.key for spec in CATALOG]
        self.assertEqual(len(keys), len(set(keys)))

    def test_every_spec_has_an_explanation(self):
        """A rule either describes what it watches, or says what it is missing.

        A blank on both sides leaves an operator with a name and no way to
        judge whether to enable it.
        """
        for spec in CATALOG:
            with self.subTest(key=spec.key):
                self.assertTrue(
                    spec.description or spec.requires,
                    f"{spec.key} explains neither what it does nor what it needs",
                )

    def test_modules_and_priorities_are_valid_choices(self):
        modules = {value for value, _ in Module.choices}
        priorities = {value for value, _ in Priority.choices}
        for spec in CATALOG:
            with self.subTest(key=spec.key):
                self.assertIn(spec.module, modules)
                self.assertIn(spec.priority, priorities)

    def test_key_is_prefixed_with_its_module(self):
        """``production.high_mortality`` — the prefix is how dedupe keys and
        the summary tiles group rules without a second lookup."""
        for spec in CATALOG:
            with self.subTest(key=spec.key):
                self.assertIn(".", spec.key)

    def test_catalogue_covers_the_specified_alert_set(self):
        """A spot-check that the headline alerts from the specification exist.

        Not exhaustive — it guards the ones most likely to be quietly dropped
        in a refactor, one per module.
        """
        expected = [
            "production.high_mortality", "production.harvest_due",
            "feed.low_feed_stock", "hatchery.poor_hatchability",
            "health.vaccination_due", "health.medicine_expired",
            "inventory.negative_stock", "inventory.reorder_level",
            "purchase.duplicate_invoice", "sales.credit_limit_exceeded",
            "finance.cheque_bounce", "hr.attendance_missing",
            "system.backup_failed", "system.login_failed",
        ]
        for key in expected:
            with self.subTest(key=key):
                self.assertIn(key, BY_KEY)

    def test_unsupported_rules_name_the_missing_data(self):
        for spec in CATALOG:
            if spec.supported:
                continue
            with self.subTest(key=spec.key):
                self.assertGreater(
                    len(spec.requires), 20,
                    f"{spec.key} should say what data it needs, not just that "
                    f"it is unsupported",
                )
