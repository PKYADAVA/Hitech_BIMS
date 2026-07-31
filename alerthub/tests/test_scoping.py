"""The security boundary: who can see which notification.

These are the tests that matter most in this module. A bug in a detector shows
up as a missing or noisy alert; a bug here shows one branch's data to another
branch, which is the thing the specification is most explicit about.
"""
from __future__ import annotations

from django.contrib.auth.models import Group, User
from django.test import TestCase

from alerthub.constants import Priority
from alerthub.engine import raise_alert, unread_count
from alerthub.models import AlertRule, Notification, NotificationRecipient
from alerthub.scoping import audience_for, visible_notifications
from broiler.models import Branch, BroilerFarm, Farmer, Region, Supervisor
from user.models import GroupAccessProfile


def make_farm(name, branch):
    """A minimal BroilerFarm.

    The farm master requires a supervisor and a farmer, so the fixture builds
    the whole chain. None of it matters to scoping beyond the branch link —
    it exists only to satisfy the not-null constraints.
    """
    supervisor = Supervisor.objects.create(branch=branch, name=f"{name} sup")
    farmer = Farmer.objects.create(farmer_name=f"{name} farmer")
    return BroilerFarm.objects.create(
        branch=branch, supervisor=supervisor, farmer=farmer,
        region=branch.region.description, line="L1",
        farm_name=name, farm_capacity=1000,
    )


class ScopeTestCase(TestCase):
    """Two branches, each with a farm and a user scoped to it."""

    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(description="East")
        cls.branch_a = Branch.objects.create(
            branch_name="Akbarpur", region=region, prefix="AKB"
        )
        cls.branch_b = Branch.objects.create(
            branch_name="Basti", region=region, prefix="BST"
        )
        cls.farm_a = make_farm("Akbarpur Farm", cls.branch_a)
        cls.farm_b = make_farm("Basti Farm", cls.branch_b)

        cls.group_a = Group.objects.create(name="Branch A team")
        cls.group_b = Group.objects.create(name="Branch B team")
        cls.group_all = Group.objects.create(name="Head office")

        # Scoped to branch A only.
        profile_a = GroupAccessProfile.objects.create(
            group=cls.group_a, all_branches=False, all_farms=False,
        )
        profile_a.branches.set([cls.branch_a])
        profile_a.farms.set([cls.farm_a])

        profile_b = GroupAccessProfile.objects.create(
            group=cls.group_b, all_branches=False, all_farms=False,
        )
        profile_b.branches.set([cls.branch_b])
        profile_b.farms.set([cls.farm_b])

        # Explicitly unrestricted on every dimension.
        GroupAccessProfile.objects.create(group=cls.group_all)

        cls.user_a = User.objects.create_user("ann", password="x")
        cls.user_a.groups.add(cls.group_a)
        cls.user_b = User.objects.create_user("bob", password="x")
        cls.user_b.groups.add(cls.group_b)
        cls.user_all = User.objects.create_user("hq", password="x")
        cls.user_all.groups.add(cls.group_all)

    def make_rule(self, **kwargs):
        defaults = dict(
            name="High mortality", rule_key="production.high_mortality",
            module="production", priority=Priority.CRITICAL, threshold=1,
            cooldown_hours=0,
        )
        defaults.update(kwargs)
        return AlertRule.objects.create(**defaults)


class VisibilityTests(ScopeTestCase):
    def test_branch_scoped_user_never_sees_another_branch(self):
        rule = self.make_rule()
        raise_alert(rule, title="A", dedupe_key="a", branch=self.branch_a,
                    farm=self.farm_a)
        raise_alert(rule, title="B", dedupe_key="b", branch=self.branch_b,
                    farm=self.farm_b)

        titles_a = set(
            visible_notifications(Notification.objects.all(), self.user_a)
            .values_list("title", flat=True)
        )
        self.assertEqual(titles_a, {"A"})

        titles_b = set(
            visible_notifications(Notification.objects.all(), self.user_b)
            .values_list("title", flat=True)
        )
        self.assertEqual(titles_b, {"B"})

    def test_unrestricted_user_sees_both_branches(self):
        rule = self.make_rule()
        raise_alert(rule, title="A", dedupe_key="a", branch=self.branch_a,
                    farm=self.farm_a)
        raise_alert(rule, title="B", dedupe_key="b", branch=self.branch_b,
                    farm=self.farm_b)

        titles = set(
            visible_notifications(Notification.objects.all(), self.user_all)
            .values_list("title", flat=True)
        )
        self.assertEqual(titles, {"A", "B"})

    def test_losing_access_hides_already_delivered_alerts(self):
        """Scope is re-checked on read, not frozen at delivery.

        This is the whole reason visibility has two gates. The recipient row
        stays; the alert stops being readable the moment the branch is taken
        away.
        """
        rule = self.make_rule()
        raise_alert(rule, title="A", dedupe_key="a", branch=self.branch_a,
                    farm=self.farm_a)
        self.assertEqual(
            visible_notifications(Notification.objects.all(), self.user_a).count(), 1
        )

        profile = self.group_a.access_profile
        profile.branches.set([self.branch_b])
        profile.farms.set([self.farm_b])

        self.assertEqual(
            visible_notifications(Notification.objects.all(), self.user_a).count(), 0
        )
        # The delivery record itself is untouched — it is history.
        self.assertEqual(
            NotificationRecipient.objects.filter(user=self.user_a).count(), 1
        )

    def test_anonymous_and_none_see_nothing(self):
        from django.contrib.auth.models import AnonymousUser

        rule = self.make_rule()
        raise_alert(rule, title="A", dedupe_key="a", branch=self.branch_a,
                    farm=self.farm_a)

        self.assertEqual(
            visible_notifications(Notification.objects.all(), AnonymousUser()).count(), 0
        )
        self.assertEqual(
            visible_notifications(Notification.objects.all(), None).count(), 0
        )

    def test_unscoped_columns_are_visible_to_scoped_users(self):
        """A system alert has no branch. That is not another branch's data."""
        rule = self.make_rule(rule_key="system.storage_low", module="system")
        raise_alert(rule, title="Disk", dedupe_key="disk")

        self.assertEqual(
            visible_notifications(Notification.objects.all(), self.user_a).count(), 1
        )

    def test_untargeted_user_sees_nothing_even_inside_their_scope(self):
        """Being in scope is not being told.

        The alert is about Branch A and user_a is scoped to Branch A, but the
        rule only notifies Branch B's group, so it never reaches them.
        """
        rule = self.make_rule()
        rule.notify_groups.set([self.group_b])
        raise_alert(rule, title="A", dedupe_key="a", branch=self.branch_a,
                    farm=self.farm_a)

        self.assertEqual(
            visible_notifications(Notification.objects.all(), self.user_a).count(), 0
        )


class AudienceTests(ScopeTestCase):
    def test_group_targeting_limits_recipients(self):
        rule = self.make_rule()
        rule.notify_groups.set([self.group_a])
        notification = raise_alert(rule, title="A", dedupe_key="a",
                                   branch=self.branch_a, farm=self.farm_a)

        recipients = set(
            notification.recipients.values_list("user__username", flat=True)
        )
        self.assertEqual(recipients, {"ann"})

    def test_out_of_scope_group_members_are_not_recipients(self):
        """Naming a group does not override that group's data scope.

        Group B is told about a Branch A alert. Nobody in it can see Branch A,
        so the alert has no audience and is not written at all — a notification
        nobody could open would only inflate the counts.
        """
        rule = self.make_rule()
        rule.notify_groups.set([self.group_b])
        notification = raise_alert(rule, title="A", dedupe_key="a",
                                   branch=self.branch_a, farm=self.farm_a)

        self.assertIsNone(notification)
        self.assertEqual(Notification.objects.count(), 0)

    def test_preference_opt_out_removes_a_recipient(self):
        from alerthub.models import NotificationPreference

        pref = NotificationPreference.for_user(self.user_a)
        pref.receive_in_app = False
        pref.save()

        rule = self.make_rule()
        rule.notify_groups.set([self.group_a])
        self.assertIsNone(
            raise_alert(rule, title="A", dedupe_key="a", branch=self.branch_a,
                        farm=self.farm_a)
        )

    def test_min_priority_filters_by_urgency_not_alphabetically(self):
        """A user wanting only High and above must not receive Medium.

        Guards the ranking: sorting the priority *strings* puts "low" before
        "medium", which would let Low through a High filter.
        """
        from alerthub.models import NotificationPreference

        pref = NotificationPreference.for_user(self.user_a)
        pref.min_priority = Priority.HIGH
        pref.save()

        rule = self.make_rule(priority=Priority.MEDIUM)
        rule.notify_groups.set([self.group_a])
        self.assertIsNone(
            raise_alert(rule, title="medium", dedupe_key="m",
                        branch=self.branch_a, farm=self.farm_a)
        )

        rule.priority = Priority.CRITICAL
        rule.save()
        self.assertIsNotNone(
            raise_alert(rule, title="critical", dedupe_key="c",
                        branch=self.branch_a, farm=self.farm_a)
        )

    def test_inactive_users_are_never_recipients(self):
        self.user_a.is_active = False
        self.user_a.save()

        rule = self.make_rule()
        rule.notify_groups.set([self.group_a])
        self.assertIsNone(
            raise_alert(rule, title="A", dedupe_key="a", branch=self.branch_a,
                        farm=self.farm_a)
        )


class UnreadCountTests(ScopeTestCase):
    def test_badge_matches_what_the_list_shows(self):
        rule = self.make_rule()
        raise_alert(rule, title="A", dedupe_key="a", branch=self.branch_a,
                    farm=self.farm_a)
        raise_alert(rule, title="B", dedupe_key="b", branch=self.branch_b,
                    farm=self.farm_b)

        self.assertEqual(unread_count(self.user_a), 1)
        self.assertEqual(unread_count(self.user_b), 1)
        self.assertEqual(unread_count(self.user_all), 2)

    def test_mark_read_only_touches_the_calling_user(self):
        from alerthub.engine import mark_read

        rule = self.make_rule()
        notification = raise_alert(rule, title="A", dedupe_key="a",
                                   branch=self.branch_a, farm=self.farm_a)

        mark_read(self.user_a, [notification.pk])

        self.assertEqual(unread_count(self.user_a), 0)
        # The head-office user was also a recipient and is still unread.
        self.assertEqual(unread_count(self.user_all), 1)
