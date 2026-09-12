"""The widget's priority split has to add up to the bell beside it.

The summary counts a queryset that ``visible_notifications`` has made
distinct() — the join to recipients duplicates rows — and a distinct() queryset
carries its ordering column into the SELECT, from where it reaches the GROUP
BY. Grouped by (priority, created_at) that is a row per notification rather
than per priority, and collecting them into a dict keyed by priority keeps only
the last: six unread criticals were reported as one while the bell counted all
nine.

It needs more than one unread notification of the same priority to show, which
is why an alert scan on a quiet database never did.
"""
from __future__ import annotations

from django.contrib.auth.models import Group, User
from django.test import TestCase

from alerthub.models import Notification


class SummaryPriorityCountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.group = Group.objects.create(name="Everyone")
        cls.user = User.objects.create_user("watcher", password="x")
        cls.user.groups.add(cls.group)

        # Three criticals and two lows, unread, addressed to this user.
        plan = [("critical", 3), ("low", 2), ("high", 1)]
        for priority, count in plan:
            for i in range(count):
                n = Notification.objects.create(
                    rule_key=f"test.{priority}", module="inventory",
                    priority=priority, title=f"{priority} {i}", message="x")
                n.recipients.create(user=cls.user, is_read=False)

    def setUp(self):
        self.client.force_login(self.user)

    def body(self):
        response = self.client.get("/api/alerthub/notifications/summary/")
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_each_priority_counts_every_notification(self):
        data = self.body()
        self.assertEqual(data["critical"], 3)
        self.assertEqual(data["low"], 2)
        self.assertEqual(data["high"], 1)
        self.assertEqual(data["medium"], 0)

    def test_the_split_adds_up_to_the_unread_total(self):
        """The number on the bell and the numbers on the tiles are one fact."""
        data = self.body()
        split = data["critical"] + data["high"] + data["medium"] + data["low"]
        self.assertEqual(split, data["unread"])

    def test_a_read_notification_leaves_the_split(self):
        Notification.objects.filter(priority="critical").first() \
            .recipients.filter(user=self.user).update(is_read=True)
        data = self.body()
        self.assertEqual(data["critical"], 2)
        self.assertEqual(data["critical"] + data["high"] + data["medium"]
                         + data["low"], data["unread"])
