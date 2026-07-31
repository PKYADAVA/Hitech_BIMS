"""Deduplication, delivery honesty and failure isolation."""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.utils import timezone

from alerthub.constants import Channel, Priority
from alerthub.engine import raise_alert
from alerthub.models import AlertRule, Notification


class EngineTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.group = Group.objects.create(name="Ops")
        cls.user = User.objects.create_user("ops", password="x")
        cls.user.groups.add(cls.group)

    def make_rule(self, **kwargs):
        defaults = dict(
            name="Test rule", rule_key="inventory.negative_stock",
            module="inventory", priority=Priority.CRITICAL, cooldown_hours=24,
        )
        defaults.update(kwargs)
        rule = AlertRule.objects.create(**defaults)
        rule.notify_groups.set([self.group])
        return rule


class DedupeTests(EngineTestCase):
    def test_same_subject_inside_cooldown_is_suppressed(self):
        rule = self.make_rule()
        first = raise_alert(rule, title="Negative", dedupe_key="item:1:wh:2")
        second = raise_alert(rule, title="Negative", dedupe_key="item:1:wh:2")

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(Notification.objects.count(), 1)

    def test_different_subjects_both_raise(self):
        rule = self.make_rule()
        raise_alert(rule, title="A", dedupe_key="item:1:wh:2")
        raise_alert(rule, title="B", dedupe_key="item:9:wh:2")
        self.assertEqual(Notification.objects.count(), 2)

    def test_zero_cooldown_raises_every_time(self):
        """Rules watching genuinely distinct events opt out of suppression."""
        rule = self.make_rule(cooldown_hours=0)
        raise_alert(rule, title="A", dedupe_key="same")
        raise_alert(rule, title="A", dedupe_key="same")
        self.assertEqual(Notification.objects.count(), 2)

    def test_cooldown_expires(self):
        rule = self.make_rule(cooldown_hours=1)
        first = raise_alert(rule, title="A", dedupe_key="same")

        # Age the first alert past the window rather than sleeping.
        Notification.objects.filter(pk=first.pk).update(
            created_at=timezone.now() - timedelta(hours=2)
        )
        self.assertIsNotNone(raise_alert(rule, title="A", dedupe_key="same"))
        self.assertEqual(Notification.objects.count(), 2)


class DeliveryTests(EngineTestCase):
    def test_unwired_channels_are_not_claimed_as_delivered(self):
        """A rule may ask for SMS; the record must not say it was sent."""
        rule = self.make_rule(via_in_app=True, via_sms=True, via_whatsapp=True)
        notification = raise_alert(rule, title="A", dedupe_key="a")

        delivered = notification.recipients.first().delivered_channels
        self.assertEqual(delivered, [Channel.IN_APP])
        self.assertNotIn(Channel.SMS, delivered)

    def test_alert_with_no_audience_is_not_written(self):
        empty_group = Group.objects.create(name="Nobody")
        rule = self.make_rule()
        rule.notify_groups.set([empty_group])

        self.assertIsNone(raise_alert(rule, title="A", dedupe_key="a"))
        self.assertEqual(Notification.objects.count(), 0)


class FailureIsolationTests(EngineTestCase):
    def test_a_broken_alert_returns_none_rather_than_raising(self):
        """Alerting is a side effect and must never break its caller.

        A title of the wrong type would blow up inside ``raise_alert``; the
        caller gets None and carries on.
        """
        rule = self.make_rule()
        self.assertIsNone(
            raise_alert(rule, title=None, dedupe_key="a")
        )
        self.assertEqual(Notification.objects.count(), 0)


class OrderingTests(EngineTestCase):
    def test_urgency_ordering_is_not_alphabetical(self):
        """critical < high < medium < low, which sorting the strings gets wrong.

        Alphabetically "low" precedes "medium", so a naive order_by would rank
        a Low alert above a Medium one.
        """
        rule = self.make_rule(cooldown_hours=0)
        for priority in (Priority.LOW, Priority.MEDIUM, Priority.CRITICAL,
                         Priority.HIGH):
            rule.priority = priority
            rule.save()
            raise_alert(rule, title=priority, dedupe_key=f"k-{priority}")

        ordered = list(
            Notification.objects.by_urgency().values_list("priority", flat=True)
        )
        self.assertEqual(
            ordered,
            [Priority.CRITICAL, Priority.HIGH, Priority.MEDIUM, Priority.LOW],
        )
