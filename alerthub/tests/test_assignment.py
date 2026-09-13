"""Whose job an alert is.

Assignment is deliberately not a status. "Who owns this" and "how far along
is it" are different questions, and the widget was showing the second with no
way to answer the first: a farm with nine open alerts said nine problems and
nothing about who was dealing with which.

The rules this file pins down:

* assigning does not move the alert along — an alert handed to somebody is
  still open until *they* say they have picked it up;
* the person it is handed to can see it afterwards, because an alert assigned
  to somebody who cannot find it has been assigned nowhere;
* every hand-off is in the trail, including the one that takes a name back
  off, so "who was this with in March" has an answer.
"""
from __future__ import annotations

from django.contrib.auth.models import Group, User
from django.test import TestCase
from rest_framework.test import APIClient

from alerthub import workflow
from alerthub.constants import AlertStatus, Module, Priority
from alerthub.models import AlertAction, Notification, NotificationRecipient


def an_alert(to=None, **fields):
    defaults = {
        "rule_key": "feed.stock_coverage_days",
        "module": Module.FEED,
        "priority": Priority.HIGH,
        "title": "Feed Stock Coverage Low",
        "message": "Sunrise Farm has 1.8 days of cover.",
        "measured_value": "1.8",
        "threshold_value": "3",
    }
    defaults.update(fields)
    alert = Notification.objects.create(**defaults)
    if to is not None:
        NotificationRecipient.objects.create(notification=alert, user=to)
    return alert


class AssignmentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.group = Group.objects.create(name="Everyone")
        cls.manager = User.objects.create_user(
            "manager", password="x", first_name="Rita", last_name="Shah")
        cls.supervisor = User.objects.create_user(
            "supervisor", password="x", first_name="Amit", last_name="Kumar")
        for person in (cls.manager, cls.supervisor):
            person.groups.add(cls.group)

    def setUp(self):
        self.alert = an_alert(to=self.manager)

    # -- the move itself ---------------------------------------------------

    def test_assigning_names_an_owner_without_moving_the_alert_along(self):
        """The distinction the whole feature rests on.

        A dashboard that marked an alert acknowledged the moment it was handed
        over would report that a problem had been picked up by the one person
        who has not yet looked at it.
        """
        workflow.assign(self.alert, user=self.manager,
                        assignee_id=self.supervisor.pk)
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.assigned_to, self.supervisor)
        self.assertIsNotNone(self.alert.assigned_at)
        self.assertEqual(self.alert.assigned_by, self.manager)
        self.assertEqual(self.alert.status, AlertStatus.OPEN)

    def test_the_person_it_lands_on_can_see_it(self):
        """An alert assigned to somebody who cannot find it on their own
        dashboard has been assigned nowhere."""
        self.assertFalse(
            Notification.objects.for_user(self.supervisor)
            .filter(pk=self.alert.pk).exists()
        )
        workflow.assign(self.alert, user=self.manager,
                        assignee_id=self.supervisor.pk)
        self.assertTrue(
            Notification.objects.for_user(self.supervisor)
            .filter(pk=self.alert.pk).exists()
        )

    def test_every_hand_off_is_written_down_with_the_name(self):
        workflow.assign(self.alert, user=self.manager,
                        assignee_id=self.supervisor.pk)
        entry = self.alert.actions.first()
        self.assertEqual(entry.action, AlertAction.ASSIGNED)
        self.assertEqual(entry.actor, self.manager)
        self.assertEqual(entry.notified, ["Amit Kumar"])
        # Nothing moved, so nothing is claimed to have moved.
        self.assertEqual(entry.to_status, "")

    def test_taking_the_name_back_off_is_its_own_entry(self):
        """Unassigning is not assigning to nobody — it is undoing a
        hand-off, and the trail has to be able to say which happened."""
        workflow.assign(self.alert, user=self.manager,
                        assignee_id=self.supervisor.pk)
        workflow.assign(self.alert, user=self.manager, assignee_id=None)
        self.alert.refresh_from_db()
        self.assertIsNone(self.alert.assigned_to)
        self.assertIsNone(self.alert.assigned_at)
        actions = list(self.alert.actions.values_list("action", flat=True))
        self.assertEqual(actions, [AlertAction.UNASSIGNED, AlertAction.ASSIGNED])

    def test_reassigning_is_one_move_and_the_old_name_stays_in_the_trail(self):
        other = User.objects.create_user("other", password="x",
                                         first_name="Sunil")
        other.groups.add(self.group)
        workflow.assign(self.alert, user=self.manager,
                        assignee_id=self.supervisor.pk)
        workflow.assign(self.alert, user=self.manager, assignee_id=other.pk)
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.assigned_to, other)
        names = [entry.notified for entry in self.alert.actions.all()]
        self.assertEqual(names, [["Sunil"], ["Amit Kumar"]])

    # -- what it refuses ---------------------------------------------------

    def test_assigning_it_to_whoever_already_has_it_is_refused(self):
        """Not an error worth a trail entry — it is a second press of the
        same button, and writing it down would put a hand-off in the log
        that nobody made."""
        workflow.assign(self.alert, user=self.manager,
                        assignee_id=self.supervisor.pk)
        with self.assertRaises(Exception):
            workflow.assign(self.alert, user=self.manager,
                            assignee_id=self.supervisor.pk)
        self.assertEqual(self.alert.actions.count(), 1)

    def test_clearing_an_unassigned_alert_is_refused(self):
        with self.assertRaises(Exception):
            workflow.assign(self.alert, user=self.manager, assignee_id=None)
        self.assertEqual(self.alert.actions.count(), 0)

    def test_somebody_who_cannot_see_the_alert_cannot_hand_it_out(self):
        stranger = User.objects.create_user("stranger", password="x")
        with self.assertRaises(Exception):
            workflow.assign(self.alert, user=stranger,
                            assignee_id=self.supervisor.pk)

    def test_a_deactivated_account_cannot_be_given_work(self):
        self.supervisor.is_active = False
        self.supervisor.save(update_fields=["is_active"])
        with self.assertRaises(Exception):
            workflow.assign(self.alert, user=self.manager,
                            assignee_id=self.supervisor.pk)


class AssignmentApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.group = Group.objects.create(name="Everyone")
        cls.manager = User.objects.create_user("manager", password="x")
        cls.supervisor = User.objects.create_user(
            "supervisor", password="x", first_name="Amit", last_name="Kumar")
        for person in (cls.manager, cls.supervisor):
            person.groups.add(cls.group)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.manager)
        self.alert = an_alert(to=self.manager)

    def url(self):
        return "/api/alerthub/action-required/%s/assign/" % self.alert.pk

    def test_the_endpoint_hands_it_over_and_says_so_in_the_row_it_returns(self):
        """The card redraws from this response, so the name has to come back
        in it — a row that only shows its new owner after the next poll looks
        like the button did nothing."""
        response = self.client.post(
            self.url(), {"user_id": self.supervisor.pk}, format="json")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["alert"]["assigned_to_name"], "Amit Kumar")
        self.assertEqual(body["alert"]["assigned_to"], self.supervisor.pk)
        self.assertEqual(body["entry"]["action"], "assigned")

    def test_an_empty_user_id_clears_it(self):
        self.client.post(self.url(), {"user_id": self.supervisor.pk},
                         format="json")
        response = self.client.post(self.url(), {"user_id": None},
                                    format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["alert"]["assigned_to_name"], "")

    def test_a_refusal_comes_back_as_a_sentence_the_card_can_show(self):
        """400 with the state machine explaining itself, which is what the
        widget puts in the toast."""
        response = self.client.post(self.url(), {"user_id": 999999},
                                    format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("account", response.json()["error"].lower())
