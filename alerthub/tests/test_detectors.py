"""Every detector actually runs.

These do not assert that a detector finds the right thing — that needs a fixture
per business rule and belongs with each module's own tests. What they assert is
that each one *executes*: the model exists, the fields are spelled correctly,
the related names resolve and the query is valid SQL.

That is the failure mode this module is most exposed to. A detector references
half a dozen fields across another app's models, is only ever called from a
scheduled command, and a rename in that app breaks it silently — the scan
catches the exception, logs it, and the alert simply never arrives. Running all
forty against an empty database turns that into a test failure.
"""
from __future__ import annotations

from django.contrib.auth.models import Group, User
from django.test import TestCase

from alerthub import detectors
from alerthub.catalog import BY_KEY, CATALOG
from alerthub.models import AlertRule, Notification
from alerthub.services import scan


class DetectorSmokeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.group = Group.objects.create(name="Everyone")
        cls.user = User.objects.create_user("scanner", password="x")
        cls.user.groups.add(cls.group)

        # One enabled rule per supported catalogue entry, at its own defaults.
        for spec in CATALOG:
            if not spec.supported:
                continue
            rule = AlertRule.objects.create(
                name=f"{spec.label} — smoke",
                rule_key=spec.key,
                priority=spec.priority,
                threshold=spec.threshold.default if spec.threshold else None,
                operator=spec.threshold.operator if spec.threshold else "gte",
                is_active=True,
            )
            rule.notify_groups.set([cls.group])

    def test_every_supported_detector_runs_without_error(self):
        result = scan()
        self.assertEqual(
            result.failed, [],
            f"These detectors raised while scanning an empty database: "
            f"{sorted(set(result.failed))}. See the test log for tracebacks.",
        )

    def test_scan_runs_every_configured_rule(self):
        supported = sum(1 for spec in CATALOG if spec.supported)
        result = scan()
        self.assertEqual(result.rules_run, supported)
        self.assertEqual(result.skipped_no_detector, [])

    def test_an_empty_database_raises_nothing(self):
        """No data means no alerts — not a crash, and not a false positive.

        A detector that reports a breach against zero rows (0% mortality read
        as "below target", an empty flock read as 100% loss) would fill the feed
        on a fresh install.
        """
        scan()
        self.assertEqual(Notification.objects.count(), 0)

    def test_unsupported_rules_are_skipped_not_run(self):
        spec = next(s for s in CATALOG if not s.supported)
        rule = AlertRule.objects.create(
            name="Unsupported", rule_key=spec.key, is_active=True,
        )
        rule.notify_groups.set([self.group])

        result = scan(rule_key=spec.key)
        self.assertIn(spec.key, result.skipped_unsupported)
        self.assertEqual(result.rules_run, 0)

    def test_disabled_rules_are_not_evaluated(self):
        AlertRule.objects.update(is_active=False)
        self.assertEqual(scan().rules_run, 0)

    def test_scan_can_be_narrowed_to_one_rule_key(self):
        result = scan(rule_key="inventory.negative_stock")
        self.assertEqual(result.rules_run, 1)


class ScanReportingTests(TestCase):
    def test_unknown_rule_key_is_reported_not_crashed(self):
        """A rule whose key left the catalogue must not stop the scan."""
        AlertRule.objects.create(name="Stale", rule_key="gone.away",
                                 is_active=True)
        result = scan()
        self.assertIn("gone.away", result.skipped_no_detector)

    def test_summary_is_human_readable(self):
        self.assertIn("alert(s)", scan().summary())
