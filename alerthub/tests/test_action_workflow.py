"""What may be done about an alert, and what is written down when it is.

The Action Required card exists because a list of problems nobody can answer
for is just a list of problems. So the things worth pinning here are not that
a button changes a column — they are the promises the card makes to the person
reading it:

* a move it offers is a move the API will accept, and the two lists come from
  one place;
* an alert that has been picked up says so, and says by whom;
* dismissing — the one way to close an alert with nothing done about it —
  cannot happen silently;
* telling a supervisor does not quietly mark the problem as handled;
* and every one of those leaves a row behind that cannot be edited away.

The state machine is tested through :mod:`alerthub.workflow` and the card's
promises through the API, because those are the two surfaces anything else
depends on.
"""
import datetime

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from alerthub.constants import (MODULE_ICON, PRIORITY_COLOR, SEVERITY_LABEL,
                                AlertStatus, Module, Priority)
from alerthub.models import AlertAction, Notification, NotificationRecipient
from alerthub import workflow

API = "/api/alerthub/action-required/"


def an_alert(to=None, **fields):
    """One raised alert, addressed to somebody.

    ``to`` is not optional in spirit. Visibility in this module means *being a
    recipient* — ``raise_alert`` writes those rows as it fans an alert out, and
    an alert with none is one nobody was told about, which no amount of scope
    will make visible. A helper that left them out would build a fixture that
    cannot occur and then test the wrong thing with it.
    """
    defaults = {
        "rule_key": "feed.stock_coverage_days",
        "module": Module.FEED,
        "priority": Priority.HIGH,
        "title": "Feed Stock Coverage Low",
        "message": "Sunrise Farm has 1.8 days of cover.",
        "measured_value": "1.8",
        "threshold_value": "3",
        "object_label": "broiler.BroilerBatch",
        "object_display": "BR-26031",
        "action_url": "/daily-entry/single/?batch=7",
    }
    defaults.update(fields)
    alert = Notification.objects.create(**defaults)
    if to is not None:
        NotificationRecipient.objects.create(notification=alert, user=to)
    return alert


class StateMachineTests(TestCase):
    """Which move follows which, and who may make it."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="manager", password="x", email="m@example.com")
        self.alert = an_alert(to=self.user)

    def test_an_untouched_alert_can_be_picked_up(self):
        workflow.acknowledge(self.alert, user=self.user)
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, AlertStatus.ACKNOWLEDGED)

    def test_picking_it_up_records_who(self):
        """The status chip is only useful next to a name. "Acknowledged" with
        nobody against it tells the next person nothing about whether to go
        and look themselves."""
        workflow.acknowledge(self.alert, user=self.user)
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status_changed_by, self.user)
        self.assertIsNotNone(self.alert.status_changed_at)

    def test_work_cannot_go_backwards(self):
        """Nobody can un-know that an alert was picked up."""
        workflow.start(self.alert, user=self.user)
        with self.assertRaises(ValidationError):
            workflow.acknowledge(self.alert, user=self.user)

    def test_a_resolved_alert_can_be_reopened(self):
        """A fix that did not hold. Re-raising it by hand is not something a
        supervisor can do, so resolving must not be a one-way door."""
        workflow.resolve(self.alert, user=self.user)
        workflow.reopen(self.alert, user=self.user)
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, AlertStatus.OPEN)

    def test_an_alert_can_be_resolved_without_being_picked_up_first(self):
        """Most alerts are dealt with by somebody who saw it, went and fixed
        it, and came back. Forcing an Acknowledge press in between would be
        ceremony, and ceremony is what stops a widget being used."""
        workflow.resolve(self.alert, user=self.user)
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, AlertStatus.RESOLVED)

    def test_an_alert_nobody_addressed_to_you_is_not_yours_to_action(self):
        """Visibility already decides who sees what. The point here is that the
        same answer governs who may change it — an id in a request body is not
        permission to close somebody else's alert, and a widget that trusted
        the id would let anyone with a login clear the whole company's list."""
        outsider = get_user_model().objects.create_user(
            username="not_told", password="x")
        with self.assertRaises(PermissionDenied):
            workflow.acknowledge(self.alert, user=outsider)


class DismissalTests(TestCase):
    """The one transition that closes an alert with nothing done about it."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="manager2", password="x", email="m2@example.com")
        self.alert = an_alert(to=self.user)

    def test_it_cannot_be_dismissed_without_a_reason(self):
        with self.assertRaises(ValidationError):
            workflow.dismiss(self.alert, user=self.user, reason="")

    def test_whitespace_is_not_a_reason(self):
        with self.assertRaises(ValidationError):
            workflow.dismiss(self.alert, user=self.user, reason="   ")

    def test_a_refused_dismissal_changes_nothing(self):
        """Half a transition is worse than none: an alert left dismissed with
        no reason against it is exactly what the check exists to prevent."""
        try:
            workflow.dismiss(self.alert, user=self.user, reason="")
        except ValidationError:
            pass
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, AlertStatus.OPEN)
        self.assertEqual(AlertAction.objects.count(), 0)

    def test_the_reason_is_kept_against_the_alert(self):
        workflow.dismiss(self.alert, user=self.user,
                         reason="Stock arrived this morning.")
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.dismiss_reason, "Stock arrived this morning.")

    def test_reopening_clears_the_old_reason(self):
        """Left in place it would read as the reason the alert is open, which
        is the opposite of what it says."""
        workflow.dismiss(self.alert, user=self.user, reason="Sorted.")
        workflow.reopen(self.alert, user=self.user)
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.dismiss_reason, "")

    def test_the_reason_survives_in_the_log_after_reopening(self):
        """Clearing the column must not clear the history — the decision was
        made, and whether it was a good one is the question the log answers."""
        workflow.dismiss(self.alert, user=self.user, reason="Sorted.")
        workflow.reopen(self.alert, user=self.user)
        entry = AlertAction.objects.get(action=AlertAction.DISMISSED)
        self.assertEqual(entry.note, "Sorted.")


class AuditTrailTests(TestCase):
    """Every move leaves a row. That is the whole contract."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="manager3", password="x", email="m3@example.com")
        self.alert = an_alert(to=self.user)

    def test_each_move_is_written_down(self):
        workflow.acknowledge(self.alert, user=self.user)
        workflow.start(self.alert, user=self.user)
        workflow.resolve(self.alert, user=self.user)
        self.assertEqual(
            list(AlertAction.objects.filter(notification=self.alert)
                 .order_by("created_at").values_list("action", flat=True)),
            [AlertAction.ACKNOWLEDGED, AlertAction.STARTED, AlertAction.RESOLVED])

    def test_an_entry_remembers_where_the_alert_came_from(self):
        """"Resolved" on its own does not say what it was resolved from, and
        an alert that went straight from open to resolved is a different story
        from one that somebody worked on for two days."""
        workflow.resolve(self.alert, user=self.user)
        entry = AlertAction.objects.get()
        self.assertEqual(entry.from_status, AlertStatus.OPEN)
        self.assertEqual(entry.to_status, AlertStatus.RESOLVED)


class NotifySupervisorTests(TestCase):

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_superuser(
            username="manager4", password="x", email="m4@example.com")
        self.supervisor_user = User.objects.create_user(
            username="ravi", password="x", first_name="Ravi", last_name="Kumar")
        self.alert = an_alert(to=self.user)

    def test_it_reaches_the_person_as_an_ordinary_notification(self):
        """Not a channel built for this dialog: the escalated alert has to
        turn up in the supervisor's own bell, where they already look."""
        workflow.notify_supervisor(self.alert, user=self.user,
                                   user_ids=[self.supervisor_user.pk])
        self.assertTrue(NotificationRecipient.objects.filter(
            notification=self.alert, user=self.supervisor_user).exists())

    def test_it_does_not_mark_the_alert_as_handled(self):
        """The failure this guards against is the worst one available to this
        widget: forwarding a problem and having it disappear off the list, so
        that nobody is looking at it and the dashboard says everything is
        fine."""
        workflow.notify_supervisor(self.alert, user=self.user,
                                   user_ids=[self.supervisor_user.pk])
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, AlertStatus.OPEN)

    def test_telling_the_same_person_twice_is_not_an_error(self):
        """They may already have been a recipient of the rule that raised it.
        A unique constraint turning a deliberate escalation into an error page
        is not a useful answer to that."""
        NotificationRecipient.objects.create(
            notification=self.alert, user=self.supervisor_user)
        workflow.notify_supervisor(self.alert, user=self.user,
                                   user_ids=[self.supervisor_user.pk])
        self.assertEqual(NotificationRecipient.objects.filter(
            notification=self.alert, user=self.supervisor_user).count(), 1)

    def test_it_records_who_was_told_by_name(self):
        """Ids would decay: the log is read months later, sometimes after the
        person has left."""
        entry = workflow.notify_supervisor(
            self.alert, user=self.user, user_ids=[self.supervisor_user.pk],
            note="Please check the shed today.")
        self.assertEqual(entry.notified, ["Ravi Kumar"])
        self.assertEqual(entry.note, "Please check the shed today.")

    def test_nobody_chosen_is_refused(self):
        with self.assertRaises(ValidationError):
            workflow.notify_supervisor(self.alert, user=self.user, user_ids=[])


class WidgetApiTests(TestCase):
    """What the card is handed, and what it is allowed to offer."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="viewer", password="x", email="v@example.com")
        self.client.force_login(self.user)

    def get(self):
        return self.client.get(API).json()

    def test_an_empty_list_is_all_caught_up_rather_than_an_error(self):
        data = self.get()
        self.assertEqual(data["results"], [])
        self.assertEqual(data["summary"]["total"], 0)

    def test_resolved_alerts_leave_the_list(self):
        """Taking an alert off the worklist is what resolving means."""
        alert = an_alert(to=self.user)
        self.assertEqual(len(self.get()["results"]), 1)
        workflow.resolve(alert, user=self.user)
        self.assertEqual(self.get()["results"], [])

    def test_dismissed_alerts_leave_the_list_too(self):
        alert = an_alert(to=self.user)
        workflow.dismiss(alert, user=self.user, reason="Not a real shortage.")
        self.assertEqual(self.get()["results"], [])

    def test_an_alert_being_worked_on_stays_on_the_list(self):
        """Picked up is not the same as done. An alert that vanished the
        moment somebody acknowledged it would let a problem be forgotten by
        the one action that was supposed to guarantee it was not."""
        alert = an_alert(to=self.user)
        workflow.start(alert, user=self.user)
        self.assertEqual(len(self.get()["results"]), 1)

    def test_the_most_urgent_come_first(self):
        an_alert(to=self.user, priority=Priority.LOW, title="Low one")
        an_alert(to=self.user, priority=Priority.CRITICAL, title="Critical one")
        an_alert(to=self.user, priority=Priority.MEDIUM, title="Medium one")
        titles = [row["title"] for row in self.get()["results"]]
        self.assertEqual(titles[0], "Critical one")

    def test_only_five_are_shown_and_the_rest_are_counted(self):
        """A card that showed five and said nothing about the other ninety
        would be read as "five problems", which is how a dashboard starts
        being ignored."""
        for index in range(8):
            an_alert(to=self.user, title="Alert %d" % index)
        data = self.get()
        self.assertEqual(len(data["results"]), 5)
        self.assertEqual(data["summary"]["total"], 8)
        self.assertEqual(data["summary"]["shown"], 5)

    def test_the_reading_is_shown_in_the_rules_own_unit(self):
        """1.8 against 3 means nothing without "days" beside it, and the unit
        comes from the rule rather than from a guess per module."""
        an_alert(to=self.user)
        row = self.get()["results"][0]
        self.assertEqual(row["reading"], "1.8 / 3 days")

    def test_a_large_reading_is_grouped_the_way_the_message_groups_it(self):
        """The alert's own sentence says "2,45,000". A figure beside it
        reading "245,000" or "245000" looks like a different number."""
        an_alert(to=self.user, rule_key="finance.payment_due",
                 module=Module.FINANCE, measured_value="245000",
                 threshold_value="50000")
        readings = [row["reading"] for row in self.get()["results"]]
        self.assertIn("2,45,000 / 50,000", readings[0])

    def test_a_whole_number_keeps_no_decimal_point(self):
        """"1,700.00 g" is a weight written by a machine. The breed standard
        is 1,700 g."""
        an_alert(to=self.user, measured_value="1450", threshold_value="1700")
        self.assertTrue(self.get()["results"][0]["reading"].startswith("1,450 / 1,700"))

    def test_a_row_offers_only_moves_the_api_would_accept(self):
        alert = an_alert(to=self.user)
        workflow.start(alert, user=self.user)
        keys = {move["key"] for move in self.get()["results"][0]["available_actions"]}
        self.assertEqual(keys, {"resolve", "dismiss"})
        self.assertNotIn("acknowledge", keys)

    def test_dismissal_is_marked_as_needing_a_reason(self):
        """The card opens a dialog for it rather than posting on the press,
        and it learns that from the server rather than from a hard-coded name."""
        an_alert(to=self.user)
        moves = {m["key"]: m for m in self.get()["results"][0]["available_actions"]}
        self.assertTrue(moves["dismiss"]["needs_reason"])
        self.assertFalse(moves["acknowledge"]["needs_reason"])

    def test_the_deep_link_survives_to_the_card(self):
        """"Do not send the user to a generic module page when a specific
        record is available" — the link the detector built is the one the
        button uses."""
        an_alert(to=self.user)
        self.assertEqual(self.get()["results"][0]["action_url"],
                         "/daily-entry/single/?batch=7")

    def test_what_was_closed_today_is_counted_for_the_footer(self):
        alert = an_alert(to=self.user)
        workflow.resolve(alert, user=self.user)
        self.assertEqual(self.get()["summary"]["resolved_today"], 1)

    def test_yesterdays_resolutions_are_not_counted_as_todays(self):
        alert = an_alert(to=self.user)
        workflow.resolve(alert, user=self.user)
        Notification.objects.filter(pk=alert.pk).update(
            status_changed_at=timezone.now() - datetime.timedelta(days=1))
        self.assertEqual(self.get()["summary"]["resolved_today"], 0)


class WidgetApiMoveTests(TestCase):
    """Pressing the buttons, over HTTP."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="presser", password="x", email="p@example.com")
        self.client.force_login(self.user)
        self.alert = an_alert(to=self.user)

    def post(self, move, **body):
        return self.client.post(
            "%s%s/%s/" % (API, self.alert.pk, move), body,
            content_type="application/json")

    def test_acknowledge(self):
        response = self.post("acknowledge")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["alert"]["status"], "acknowledged")

    def test_a_dismissal_with_no_reason_is_refused_with_a_sentence(self):
        """The dialog puts the answer in front of the person, so it has to be
        a sentence they can read rather than a field-keyed error blob."""
        response = self.post("dismiss", reason="")
        self.assertEqual(response.status_code, 400)
        self.assertIn("why", response.json()["error"].lower())
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, AlertStatus.OPEN)

    def test_a_move_the_state_machine_refuses_says_why(self):
        self.post("start")
        response = self.post("acknowledge")
        self.assertEqual(response.status_code, 400)
        self.assertIn("cannot be marked", response.json()["error"])

    def test_an_alert_that_does_not_exist_is_a_404_not_a_500(self):
        response = self.client.post("%s99999/acknowledge/" % API,
                                    {}, content_type="application/json")
        self.assertEqual(response.status_code, 404)

    def test_the_history_reads_oldest_first(self):
        self.post("acknowledge")
        self.post("start")
        rows = self.client.get("%s%s/history/" % (API, self.alert.pk)).json()["results"]
        self.assertEqual([r["action"] for r in rows],
                         [AlertAction.ACKNOWLEDGED, AlertAction.STARTED])

    def test_signing_out_closes_the_whole_thing(self):
        self.client.logout()
        self.assertIn(self.client.get(API).status_code, (302, 401, 403))


class SeverityVocabularyTests(TestCase):
    """One word per severity, and green kept out of it."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="reader", password="x", email="r@example.com")
        self.client.force_login(self.user)

    def test_every_priority_has_a_card_word(self):
        """A missing entry falls back to the configuration master's wording,
        so the card would silently say "Medium" beside a chip saying
        "Warning" — two names for one thing, which is the exact confusion
        this map exists to remove."""
        for priority in Priority:
            self.assertIn(priority, SEVERITY_LABEL)

    def test_the_card_word_is_the_one_the_api_sends(self):
        an_alert(to=self.user, priority=Priority.MEDIUM)
        row = self.client.get(API).json()["results"][0]
        self.assertEqual(row["severity_label"], "Warning")

    def test_no_severity_is_green(self):
        """Green means resolved, everywhere. A severity wearing it would teach
        people that green on this dashboard means nothing in particular."""
        self.assertNotIn("#16a34a", PRIORITY_COLOR.values())

    def test_every_module_has_an_icon(self):
        """A module missing from the map renders a generic bell; a module
        present with a name Font Awesome does not ship renders nothing at all,
        and neither is reported by anyone. The second is what happened to Feed.
        """
        for module in Module:
            self.assertIn(module, MODULE_ICON)
