"""Saving a row that creates a condition raises its alert there and then.

The scan runs on a clock, so an alert about something a person just recorded
arrived at the next sweep — two minutes locally, and in production whenever a
scheduler got round to it. For the conditions a save actually creates, that
wait is avoidable.

What these hold onto is the *manner* of it, because the failure modes are
worse than the feature: a rule evaluated before commit reads rows that may
roll back, a detector that throws would take the daily entry down with it, and
a rule evaluated per row would run a thousand times on an import.
"""
from __future__ import annotations

from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.db import transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from alerthub import live
from alerthub.models import AlertRule
from broiler.models import (Branch, BroilerBatch, BroilerFarm, DailyEntry, Farmer,
                            Region, Supervisor)
from inventory.models import Item, ItemCategory, StockTransfer


def _farm_fixture():
    region = Region.objects.create(description="East")
    branch = Branch.objects.create(branch_name="Akbarpur", region=region, prefix="AKB")
    supervisor = Supervisor.objects.create(branch=branch, name="R. Verma")
    farmer = Farmer.objects.create(farmer_name="S. Yadav")
    farm = BroilerFarm.objects.create(
        branch=branch, supervisor=supervisor, farmer=farmer, region=region,
        line="Line A", farm_name="Yadav Farm", farm_capacity=5000)
    batch = BroilerBatch.objects.create(
        broiler_farm=farm, batch_name="AKB-1", start_date=timezone.localdate())
    return farm, supervisor, batch


class LiveRuleWiringTests(TestCase):
    def setUp(self):
        cache.clear()
        self.farm, self.supervisor, self.batch = _farm_fixture()

    def test_saving_a_daily_entry_evaluates_its_rules(self):
        # captureOnCommitCallbacks because TestCase wraps each test in a
        # transaction it never commits, so on_commit work would never run.
        with mock.patch("alerthub.live._run") as run,                 self.captureOnCommitCallbacks(execute=True):
            DailyEntry.objects.create(
                batch=self.batch, farm=self.farm, supervisor=self.supervisor,
                date=timezone.localdate(), mortality=50, culls=2)
        evaluated = {c.args[0] for c in run.call_args_list}
        self.assertIn("production.high_mortality", evaluated)
        self.assertIn("production.cumulative_mortality", evaluated)

    def test_a_model_with_no_live_rules_evaluates_nothing(self):
        with mock.patch("alerthub.live._run") as run,                 self.captureOnCommitCallbacks(execute=True):
            Farmer.objects.create(farmer_name="Nobody")
        run.assert_not_called()

    def test_one_import_evaluates_a_rule_once_not_once_per_row(self):
        """The throttle exists for the work, not just the duplicate alert."""
        with mock.patch("alerthub.live._run") as run,                 self.captureOnCommitCallbacks(execute=True):
            for day in range(8):
                DailyEntry.objects.create(
                    batch=self.batch, farm=self.farm, supervisor=self.supervisor,
                    date=timezone.localdate() - timedelta(days=day),
                    mortality=10, culls=1)
        high = [c for c in run.call_args_list if c.args[0] == "production.high_mortality"]
        self.assertEqual(len(high), 1, "eight rows should not mean eight scans")

    def test_a_broken_detector_does_not_take_the_save_down(self):
        """Alerting is a side effect of business work, never a condition of it."""
        with mock.patch("alerthub.services.scan",
                        side_effect=RuntimeError("boom")),                 self.captureOnCommitCallbacks(execute=True):
            DailyEntry.objects.create(
                batch=self.batch, farm=self.farm, supervisor=self.supervisor,
                date=timezone.localdate(), mortality=5, culls=0)
        self.assertEqual(DailyEntry.objects.count(), 1)

    def test_every_live_rule_names_a_real_catalogue_key(self):
        from alerthub.catalog import BY_KEY

        for label, keys in live.LIVE_RULES.items():
            for key in keys:
                self.assertIn(key, BY_KEY, f"{label} names unknown rule {key}")

    def test_every_live_rule_names_a_real_model(self):
        from django.apps import apps

        for label in live.LIVE_RULES:
            apps.get_model(label)          # raises LookupError if it is wrong


class LiveRuleCommitTests(TransactionTestCase):
    """The evaluation has to happen after commit, not during the save."""

    def setUp(self):
        cache.clear()
        self.farm, self.supervisor, self.batch = _farm_fixture()

    def test_a_rolled_back_entry_never_reaches_a_rule(self):
        with mock.patch("alerthub.live._run") as run:
            try:
                with transaction.atomic():
                    DailyEntry.objects.create(
                        batch=self.batch, farm=self.farm, supervisor=self.supervisor,
                        date=timezone.localdate(), mortality=99, culls=0)
                    raise RuntimeError("rolled back")
            except RuntimeError:
                pass
        run.assert_not_called()

    def test_a_committed_entry_does_reach_its_rules(self):
        with mock.patch("alerthub.live._run") as run:
            with transaction.atomic():
                DailyEntry.objects.create(
                    batch=self.batch, farm=self.farm, supervisor=self.supervisor,
                    date=timezone.localdate(), mortality=99, culls=0)
        self.assertTrue(run.called)


class LiveRuleRaisesTests(TransactionTestCase):
    """End to end: a save, and an alert in the bell without a scan."""

    def setUp(self):
        cache.clear()
        self.farm, self.supervisor, self.batch = _farm_fixture()
        self.group = Group.objects.create(name="Everyone")
        self.user = User.objects.create_user("watcher", password="x")
        self.user.groups.add(self.group)
        rule = AlertRule.objects.create(
            name="High mortality", rule_key="production.high_mortality",
            priority="critical", threshold="0.001", operator="gte",
            is_active=True, cooldown_hours=24)
        rule.notify_groups.set([self.group])

        # A mortality *rate* needs a flock to be a share of.
        chick = Item.objects.create(
            description="Day Old Chicks",
            category=ItemCategory.objects.create(name="Chicks"),
            valuation_method="Weighted Average", standard_cost_per_unit=40,
            usage="Produced", source="Purchased", type="Raw Material",
            item_account="Expense")
        StockTransfer.objects.create(
            item=chick, to_batch=self.batch, quantity=5000,
            date=timezone.localdate() - timedelta(days=1))

    def test_a_save_can_raise_without_the_scheduled_scan(self):
        from alerthub.models import Notification

        with transaction.atomic():
            DailyEntry.objects.create(
                batch=self.batch, farm=self.farm, supervisor=self.supervisor,
                date=timezone.localdate(), mortality=400, culls=10)

        self.assertTrue(
            Notification.objects.filter(rule_key="production.high_mortality").exists(),
            "the entry that created the breach did not raise it")
