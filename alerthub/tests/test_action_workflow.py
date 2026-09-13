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


class SpreadTests(TestCase):
    """One rule must not take the whole card.

    Sorting strictly by severity is a true answer to "what is most urgent" and
    a useless answer to "what needs my attention": on real data every visible
    row was Negative Stock, and the three High alerts behind them were
    invisible. The cap trades a little ordering purity for a card that shows
    more than one problem.
    """

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="spreader", password="x", email="s@example.com")
        self.client.force_login(self.user)

    def rows(self):
        return self.client.get(API).json()["results"]

    def test_a_flood_of_one_rule_does_not_fill_the_card(self):
        """The case from production: eighteen of one rule, all critical, and
        three High alerts that never got a row.

        Enough other rules here to fill the card without help, which is the
        situation the cap is actually for.
        """
        for index in range(8):
            an_alert(to=self.user, rule_key="inventory.negative_stock",
                     priority=Priority.CRITICAL, title="Negative Stock %d" % index)
        for key in ("health.vaccination_due", "finance.payment_due",
                    "production.daily_entry_missing"):
            an_alert(to=self.user, rule_key=key, priority=Priority.HIGH, title=key)

        keys = [row["rule_key"] for row in self.rows()]
        self.assertEqual(keys.count("inventory.negative_stock"), 2)
        for key in ("health.vaccination_due", "finance.payment_due",
                    "production.daily_entry_missing"):
            self.assertIn(key, keys)

    def test_the_cap_gives_way_rather_than_leave_the_card_short(self):
        """What the cap does *not* promise.

        With nothing else open, holding a flooding rule to two rows would show
        two problems out of nine and waste three slots. The cap exists to let
        other rules in ahead of a third row from this one, not to keep the
        card empty when there are no other rules to let in.
        """
        for index in range(8):
            an_alert(to=self.user, rule_key="inventory.negative_stock",
                     priority=Priority.CRITICAL, title="Negative Stock %d" % index)
        an_alert(to=self.user, rule_key="health.vaccination_due",
                 priority=Priority.HIGH, title="Vaccination Due")

        keys = [row["rule_key"] for row in self.rows()]
        self.assertEqual(len(keys), 5)
        # The other rule still got its row before the flood took the rest.
        self.assertIn("health.vaccination_due", keys)

    def test_the_card_is_still_filled_when_one_rule_is_all_there_is(self):
        """A farm whose only problem really is eight negative stock lines
        should get a full card, not two rows and a lot of white space. The cap
        is there to make room for other rules, not to leave the room empty."""
        for index in range(8):
            an_alert(to=self.user, rule_key="inventory.negative_stock",
                     title="Negative Stock %d" % index)
        self.assertEqual(len(self.rows()), 5)

    def test_the_rows_are_still_shown_most_urgent_first(self):
        """Filling the spare slots appends rows that may outrank ones already
        picked. A Critical sitting below a High reads as a sorting bug even
        when the selection above it was right."""
        for index in range(4):
            an_alert(to=self.user, rule_key="inventory.negative_stock",
                     priority=Priority.CRITICAL, title="Critical %d" % index)
        an_alert(to=self.user, rule_key="health.vaccination_due",
                 priority=Priority.LOW, title="Information one")
        ranks = [row["priority"] for row in self.rows()]
        self.assertEqual(ranks, sorted(ranks, key=["critical", "high", "medium",
                                                   "low"].index))

    def test_a_capped_row_says_how_many_it_stands_for(self):
        """Without it a capped row looks like the only one of its kind, which
        is a worse lie than the flood the cap was put there to stop."""
        for index in range(8):
            an_alert(to=self.user, rule_key="inventory.negative_stock",
                     priority=Priority.CRITICAL, title="Negative Stock %d" % index)
        for key in ("health.vaccination_due", "finance.payment_due",
                    "production.daily_entry_missing"):
            an_alert(to=self.user, rule_key=key, priority=Priority.HIGH, title=key)

        shown = [row for row in self.rows()
                 if row["rule_key"] == "inventory.negative_stock"]
        self.assertEqual(len(shown), 2)
        # Eight open, two of them on the card - and said once, on the last of
        # the pair. Both rows stand in for the same six, so saying it twice
        # would read as twelve.
        self.assertEqual([row["more_like_this"] for row in shown], [0, 6])

    def test_a_rule_with_nothing_held_back_says_nothing(self):
        an_alert(to=self.user, rule_key="health.vaccination_due")
        self.assertEqual(self.rows()[0]["more_like_this"], 0)


class CentreLinkTests(TestCase):
    """The links the cards point at have to mean what they say.

    The dashboard has always linked to the centre with ?priority=critical and
    the centre has always ignored it, landing every one of those clicks on the
    unfiltered feed. Nothing failed; the filter was simply dropped, and the
    reader had no way to tell.
    """

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="linker", password="x", email="lk@example.com")
        self.client.force_login(self.user)

    def test_the_centre_can_name_a_rule_in_words(self):
        """The chip that shows a rule filter must not print a rule key at
        somebody who never sees one anywhere else in the product."""
        response = self.client.get("/notifications/?rule_key=feed.stock_coverage_days")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Feed Stock Coverage Low")

    def test_the_feed_can_be_narrowed_to_one_rule(self):
        """What the "+16 more like this" link is for."""
        an_alert(to=self.user, rule_key="inventory.negative_stock",
                 title="Negative Stock")
        an_alert(to=self.user, rule_key="health.vaccination_due",
                 title="Vaccination Due")
        data = self.client.get(
            "/api/alerthub/notifications/?rule_key=inventory.negative_stock").json()
        self.assertEqual([row["title"] for row in data["results"]], ["Negative Stock"])


class OneProblemOneRowTests(TestCase):
    """A problem nobody has answered must not become a row a day.

    Found on the real database: twenty-nine open alerts that were ten actual
    problems, each re-raised on three consecutive mornings. The cooldown asks
    "was this raised in the last day", which a nightly scan answers "no" every
    morning, so nothing stopped the pile growing.
    """

    def setUp(self):
        from alerthub.models import AlertRule

        self.user = get_user_model().objects.create_superuser(
            username="scanner", password="x", email="sc@example.com")
        self.rule = AlertRule.objects.create(
            name="Negative Stock", rule_key="inventory.negative_stock",
            module=Module.INVENTORY, priority=Priority.CRITICAL,
            is_active=True, cooldown_hours=24,
        )

    def raise_once(self):
        from alerthub.engine import raise_alert

        return raise_alert(
            self.rule, title="Negative Stock", message="Starter Feed is -60.",
            dedupe_key="24:negative:warehouse:18:15",
        )

    def test_a_problem_already_on_the_list_is_not_raised_again(self):
        """Not even long after the cooldown has run out. A second row changes
        nothing for anybody — the first is still there, still says the same
        thing, and now has to be resolved twice."""
        first = self.raise_once()
        self.assertIsNotNone(first)

        Notification.objects.filter(pk=first.pk).update(
            created_at=timezone.now() - datetime.timedelta(days=30))
        self.assertIsNone(self.raise_once())
        self.assertEqual(Notification.objects.count(), 1)

    def test_an_alert_being_worked_on_also_suppresses_it(self):
        """Picked up is still on somebody's list."""
        first = self.raise_once()
        workflow.start(first, user=self.user)
        Notification.objects.filter(pk=first.pk).update(
            created_at=timezone.now() - datetime.timedelta(days=30))
        self.assertIsNone(self.raise_once())

    def test_it_comes_back_once_it_has_been_dealt_with_and_is_still_true(self):
        """The point of resolving rather than suppressing. A problem somebody
        fixed that the scanner can still see is news."""
        first = self.raise_once()
        workflow.resolve(first, user=self.user)
        Notification.objects.filter(pk=first.pk).update(
            created_at=timezone.now() - datetime.timedelta(days=30))

        second = self.raise_once()
        self.assertIsNotNone(second)
        self.assertNotEqual(second.pk, first.pk)

    def test_the_cooldown_still_governs_how_soon(self):
        """Resolved five minutes ago and still true is not worth saying again
        straight away; that is what the cooldown is for."""
        first = self.raise_once()
        workflow.resolve(first, user=self.user)
        self.assertIsNone(self.raise_once())

    def test_an_alert_with_no_key_is_never_held_back_by_this_rule(self):
        """A keyless alert has no subject to be a second copy *of*, so the
        open-alert check has nothing to say about it and must not guess.

        Tested against the check itself rather than through ``raise_alert``,
        because the cooldown sitting behind it keys off the same empty string
        and would answer first — which is a separate question, and not one
        this change touches.
        """
        from alerthub.engine import _still_unanswered

        an_alert(to=self.user, dedupe_key="")
        self.assertFalse(_still_unanswered(self.rule, ""))

    def test_a_rule_that_opted_out_of_dedupe_is_left_alone(self):
        """A cooldown of zero means every occurrence is its own event — a
        duplicate invoice, a bounced cheque. The second is a second thing that
        happened, not another sighting of the first, and this check must not
        quietly overrule that."""
        from alerthub.engine import _still_unanswered

        self.rule.cooldown_hours = 0
        an_alert(to=self.user, dedupe_key="24:negative:warehouse:18:15")
        self.assertFalse(
            _still_unanswered(self.rule, "24:negative:warehouse:18:15"))


class SettleTheProblemTests(TestCase):
    """One press settles the problem, not the row.

    The rows raised before the engine learned the rule above are still there,
    three to a problem. Marking one resolved and leaving its twins on the list
    is the worst of both: the work was done and the dashboard still says it
    was not.
    """

    KEY = "24:negative:warehouse:18:15"

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="settler", password="x", email="st@example.com")
        self.rows = [an_alert(to=self.user, dedupe_key=self.KEY,
                              title="Negative Stock %d" % n) for n in range(3)]

    def statuses(self):
        return sorted(Notification.objects.filter(dedupe_key=self.KEY)
                      .values_list("status", flat=True))

    def test_resolving_one_resolves_every_copy_of_it(self):
        workflow.resolve(self.rows[0], user=self.user)
        self.assertEqual(self.statuses(), ["resolved"] * 3)

    def test_dismissing_carries_the_reason_to_every_copy(self):
        workflow.dismiss(self.rows[0], user=self.user, reason="Stock arrived.")
        reasons = set(Notification.objects.filter(dedupe_key=self.KEY)
                      .values_list("dismiss_reason", flat=True))
        self.assertEqual(reasons, {"Stock arrived."})

    def test_every_copy_gets_its_own_log_entry(self):
        """Each row's history has to explain that row. "Resolved elsewhere,
        see another notification" is not something a log should ever say."""
        workflow.resolve(self.rows[0], user=self.user)
        for row in self.rows:
            self.assertTrue(
                AlertAction.objects.filter(notification=row,
                                           action=AlertAction.RESOLVED).exists())

    def test_a_different_problem_is_left_alone(self):
        other = an_alert(to=self.user, dedupe_key="24:negative:farm:1:14",
                         title="Somewhere else")
        workflow.resolve(self.rows[0], user=self.user)
        other.refresh_from_db()
        self.assertEqual(other.status, AlertStatus.OPEN)

    def test_a_copy_further_along_does_not_fail_the_press(self):
        """A twin may sit at a point this move is not legal from.

        It cannot happen through the widget any more — a press moves them
        together — but it is exactly the state the rows raised before that
        existed in, and a press on one of those must not fail because of what
        another row says. So the twin is set directly, which is how those rows
        got out of step in the first place.
        """
        Notification.objects.filter(pk=self.rows[1].pk).update(
            status=AlertStatus.ACKNOWLEDGED)

        entry = workflow.acknowledge(self.rows[0], user=self.user)

        self.assertIsNotNone(entry)
        self.rows[0].refresh_from_db()
        self.assertEqual(self.rows[0].status, AlertStatus.ACKNOWLEDGED)
        # The awkward one was left exactly as it was, not forced.
        self.rows[1].refresh_from_db()
        self.assertEqual(self.rows[1].status, AlertStatus.ACKNOWLEDGED)

    def test_it_never_reaches_past_what_the_user_could_reach_one_at_a_time(self):
        """The grouped move is scoped exactly as a single move is. Otherwise
        one press on a visible row would quietly close rows this person is not
        allowed to see."""
        from alerthub.models import NotificationRecipient

        theirs = an_alert(dedupe_key=self.KEY, title="Somebody else's copy")
        stranger = get_user_model().objects.create_user(username="elsewhere",
                                                        password="x")
        NotificationRecipient.objects.create(notification=theirs, user=stranger)

        workflow.resolve(self.rows[0], user=self.user)
        theirs.refresh_from_db()
        self.assertEqual(theirs.status, AlertStatus.OPEN)

    def test_the_widget_is_emptied_by_one_press(self):
        """What the person actually sees: one row standing for three, one
        press, and the card clear.

        The card collapses the copies, so the press has to reach the two it is
        not showing — otherwise the row would vanish and come straight back on
        the next refresh, standing for the twins nobody had settled.
        """
        self.client.force_login(self.user)
        self.assertEqual(len(self.client.get(API).json()["results"]), 1)

        self.client.post("%s%s/resolve/" % (API, self.rows[0].pk),
                         {}, content_type="application/json")

        self.assertEqual(self.client.get(API).json()["results"], [])
        self.assertEqual(self.statuses(), ["resolved"] * 3)


class CountProblemsNotRowsTests(TestCase):
    """The card counts problems. Three sightings of one thing is one thing."""

    KEY = "24:negative:warehouse:18:15"

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="counter", password="x", email="ct@example.com")
        self.client.force_login(self.user)

    def summary(self):
        return self.client.get(API).json()["summary"]

    def test_repeated_sightings_count_once(self):
        for n in range(3):
            an_alert(to=self.user, dedupe_key=self.KEY, title="Negative %d" % n)
        self.assertEqual(self.summary()["total"], 1)

    def test_and_are_listed_once(self):
        """Showing the same problem three times was never useful, whenever the
        rows happened to be written."""
        for n in range(3):
            an_alert(to=self.user, dedupe_key=self.KEY, title="Negative %d" % n)
        self.assertEqual(len(self.client.get(API).json()["results"]), 1)

    def test_the_severity_split_counts_problems_too(self):
        """Otherwise the chips add up to more than the total beside them."""
        for n in range(3):
            an_alert(to=self.user, dedupe_key=self.KEY,
                     priority=Priority.CRITICAL, title="Negative %d" % n)
        summary = self.summary()
        self.assertEqual(summary["critical"], 1)
        self.assertEqual(summary["total"], 1)

    def test_distinct_problems_still_count_separately(self):
        an_alert(to=self.user, dedupe_key="24:negative:warehouse:18:15")
        an_alert(to=self.user, dedupe_key="24:negative:farm:1:14")
        self.assertEqual(self.summary()["total"], 2)

    def test_rows_with_no_key_each_stand_for_themselves(self):
        """A hand-written message is not a sighting of anything."""
        an_alert(to=self.user, dedupe_key="", title="Notice one")
        an_alert(to=self.user, dedupe_key="", title="Notice two")
        self.assertEqual(self.summary()["total"], 2)

    def test_settling_a_problem_counts_once_in_the_footer(self):
        """One problem got through, not three."""
        rows = [an_alert(to=self.user, dedupe_key=self.KEY, title="N%d" % n)
                for n in range(3)]
        workflow.resolve(rows[0], user=self.user)
        self.assertEqual(self.summary()["resolved_today"], 1)
