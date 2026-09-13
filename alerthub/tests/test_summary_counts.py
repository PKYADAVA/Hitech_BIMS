"""The widget's priority split has to add up to its own total.

The summary counts a queryset that ``visible_notifications`` has made
distinct() — the join to recipients duplicates rows — and a distinct() queryset
carries its ordering column into the SELECT, from where it reaches the GROUP
BY. Grouped by (priority, created_at) that is a row per notification rather
than per priority, and collecting them into a dict keyed by priority keeps only
the last: six criticals were reported as one while the bell counted all nine.

It needs more than one notification of the same priority to show, which is
why an alert scan on a quiet database never did.

The split counts **open** alerts, not unread ones. It used to count unread,
under an empty state reading "No open alerts - you're all caught up" - so a
farm with eighteen unresolved criticals that somebody had glanced at showed
four zeroes and a tick, beside a card reporting twenty-seven. Reading an alert
is not answering it. The bell's badge is still unread, which is a different
and honest question: the bell is a reading list.
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

    def split(self, data):
        return data["critical"] + data["high"] + data["medium"] + data["low"]

    def test_the_split_adds_up_to_the_total_beside_it(self):
        """The tiles and the number above them are one fact.

        Counted two ways on purpose - the split grouped in SQL, the total
        summed from it - so the GROUP BY bug this file is named for shows up
        as a disagreement rather than as a quietly wrong tile.
        """
        data = self.body()
        self.assertEqual(self.split(data), data["open"])

    def test_reading_an_alert_does_not_take_it_off_the_split(self):
        """The change this file records. Somebody glancing at a critical alert
        on Monday has not dealt with it, and a card that dropped it from the
        count said the farm was clear when it was not."""
        self.mark_one_read()
        data = self.body()
        self.assertEqual(data["critical"], 3)
        self.assertEqual(self.split(data), data["open"])

    def test_answering_an_alert_does_take_it_off(self):
        """What does clear it: somebody deciding about it."""
        from alerthub import workflow

        alert = Notification.objects.filter(priority="critical").first()
        workflow.resolve(alert, user=self.user)
        data = self.body()
        self.assertEqual(data["critical"], 2)
        self.assertEqual(self.split(data), data["open"])

    def test_the_bell_still_counts_what_has_not_been_read(self):
        """Two questions, two numbers, and the bell keeps the honest one."""
        self.mark_one_read()
        data = self.body()
        self.assertEqual(data["unread"], 5)
        self.assertEqual(data["open"], 6)

    def mark_one_read(self):
        alert = Notification.objects.filter(priority="critical").first()
        alert.recipients.filter(user=self.user).update(is_read=True)
