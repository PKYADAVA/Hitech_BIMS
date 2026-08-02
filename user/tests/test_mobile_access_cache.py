"""The Mobile Access cache, and the three things that must retire it.

A permission cache is only worth having if it cannot serve a stale "yes". The
speed is incidental; every test here is really about invalidation.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TestCase

from user.models import GroupMobileAccess, GroupMobileTabPermission
from user.services.mobile_access import (mobile_can, mobile_preferences,
                                         screen_perms)

TAB = "daily_entry_list"


class CacheTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.member = User.objects.create_user("ch_member", "m@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Cached Group")
        self.member.groups.add(self.group)
        GroupMobileAccess.objects.create(group=self.group, module_key="broiler",
                                         enabled=True, position=0)

    def user(self):
        return get_user_model().objects.get(pk=self.member.pk)

    # ---- it actually caches ------------------------------------------------

    def test_a_repeat_read_costs_no_queries(self):
        user = self.user()
        mobile_preferences(user)                      # warm
        with self.assertNumQueries(0):
            mobile_preferences(user)

    def test_screen_perms_is_cached_too(self):
        GroupMobileTabPermission.objects.create(group=self.group, tab_code=TAB,
                                                can_view=True)
        user = self.user()
        screen_perms(user)
        with self.assertNumQueries(0):
            screen_perms(user)

    def test_unconfigured_is_cached_as_an_answer_not_a_miss(self):
        """`None` means "unconfigured", which is a real answer. Cached
        unwrapped it would be indistinguishable from a miss and re-queried
        forever — the case with no rows is also the most common one."""
        loose = get_user_model().objects.create_user("ch_loose", "l@x.com",
                                                     "Str0ngPass!")
        self.assertIsNone(screen_perms(loose))
        with self.assertNumQueries(0):
            self.assertIsNone(screen_perms(loose))

    def test_users_do_not_share_an_answer(self):
        other = get_user_model().objects.create_user("ch_other", "o@x.com",
                                                     "Str0ngPass!")
        self.assertIsNotNone(mobile_preferences(self.user()))
        self.assertIsNone(mobile_preferences(other))

    # ---- and it retires when it must ---------------------------------------

    def test_changing_a_module_switch_retires_it(self):
        user = self.user()
        self.assertIn("broiler", mobile_preferences(user))

        GroupMobileAccess.objects.filter(group=self.group).update(enabled=False)
        # .update() skips signals on purpose here: prove the cache would be
        # stale without one, then that the real path (a save) is not.
        self.assertIn("broiler", mobile_preferences(user))

        GroupMobileAccess.objects.get(group=self.group,
                                      module_key="broiler").save()
        self.assertNotIn("broiler", mobile_preferences(self.user()))

    def test_deleting_a_row_retires_it(self):
        user = self.user()
        mobile_preferences(user)
        GroupMobileAccess.objects.filter(group=self.group).delete()
        self.assertIsNone(mobile_preferences(self.user()))

    def test_changing_the_screen_matrix_retires_it(self):
        user = self.user()
        GroupMobileTabPermission.objects.create(
            group=self.group, tab_code=TAB, can_view=True, can_edit=True)
        self.assertTrue(screen_perms(user)[TAB]["edit"])

        row = GroupMobileTabPermission.objects.get(group=self.group, tab_code=TAB)
        row.can_edit = False
        row.save()
        self.assertFalse(screen_perms(self.user())[TAB]["edit"])

    def test_joining_a_group_retires_it(self):
        """The input that is easiest to forget: membership is changed from
        four places and none of them is where the cache lives."""
        newcomer = get_user_model().objects.create_user("ch_new", "n@x.com",
                                                        "Str0ngPass!")
        self.assertIsNone(mobile_preferences(newcomer))

        newcomer.groups.add(self.group)
        newcomer = get_user_model().objects.get(pk=newcomer.pk)
        self.assertIn("broiler", mobile_preferences(newcomer))

    def test_leaving_a_group_retires_it(self):
        user = self.user()
        self.assertIsNotNone(mobile_preferences(user))
        user.groups.remove(self.group)
        self.assertIsNone(mobile_preferences(self.user()))

    def test_clearing_all_groups_retires_it(self):
        user = self.user()
        self.assertIsNotNone(mobile_preferences(user))
        user.groups.clear()
        self.assertIsNone(mobile_preferences(self.user()))

    # ---- the verdict itself ------------------------------------------------

    def test_a_revoked_action_stops_being_allowed_immediately(self):
        """The whole point, end to end: no stale yes."""
        from user.models import GroupTabPermission

        GroupTabPermission.objects.create(
            group=self.group, tab_code=TAB, can_view=True, can_edit=True)
        GroupMobileTabPermission.objects.create(
            group=self.group, tab_code=TAB, can_view=True, can_edit=True)
        self.assertTrue(mobile_can(self.user(), TAB, "edit"))

        row = GroupMobileTabPermission.objects.get(group=self.group, tab_code=TAB)
        row.can_edit = False
        row.save()
        self.assertFalse(mobile_can(self.user(), TAB, "edit"))

    def test_the_editor_save_path_retires_it(self):
        """Through the view, not the model — the path an administrator uses."""
        from django.urls import reverse
        from user.models import GroupTabPermission

        GroupTabPermission.objects.create(
            group=self.group, tab_code=TAB, can_view=True, can_edit=True)
        GroupMobileTabPermission.objects.create(
            group=self.group, tab_code=TAB, can_view=True, can_edit=True)
        self.assertTrue(mobile_can(self.user(), TAB, "edit"))

        admin = get_user_model().objects.create_superuser("ch_admin", "a@x.com",
                                                          "Str0ngPass!")
        self.client.force_login(admin)
        self.client.post(reverse("mobile_access_form"),
                         {"group": self.group.id, f"p_{TAB}_view": "on",
                          "on_broiler": "on"})
        self.assertFalse(mobile_can(self.user(), TAB, "edit"))
