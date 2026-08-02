"""User > Explain Access — per-user answers, and which gate gave them.

The editors answer per group. This answers the question people actually ask,
and its one hard requirement is that it never disagrees with the guards: it
reports by calling them, so a test that catches disagreement is the test that
matters most here.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from user.models import (GroupAccessProfile, GroupMobileAccess,
                         GroupMobileTabPermission, GroupTabPermission)
from user.services.access_explain import (ALLOWED, BYPASS, NO_MODULE, NO_SCREEN,
                                          NO_WEB, explain, summarise)

TAB = "daily_entry_list"


class ExplainTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.member = User.objects.create_user("ex_member", "m@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Explained")
        self.member.groups.add(self.group)
        GroupTabPermission.objects.create(
            group=self.group, tab_code=TAB, can_view=True, can_add=True,
            can_edit=True, can_delete=True)

    def user(self):
        return get_user_model().objects.get(pk=self.member.pk)

    def test_a_permitted_action_is_allowed_on_both(self):
        verdict = explain(self.user(), TAB, "edit")
        self.assertTrue(verdict["web"])
        self.assertTrue(verdict["phone"])
        self.assertEqual(verdict["reason"], ALLOWED)

    def test_it_names_the_group_the_permission_came_from(self):
        """A user in several groups inherits the union, so naming the source is
        the difference between an explanation and a restatement."""
        self.assertEqual(explain(self.user(), TAB, "edit")["groups"], ["Explained"])

    def test_no_web_permission_is_reported_as_such(self):
        GroupTabPermission.objects.filter(group=self.group, tab_code=TAB).update(
            can_edit=False)
        verdict = explain(self.user(), TAB, "edit")
        self.assertFalse(verdict["web"])
        self.assertEqual(verdict["reason"], NO_WEB)

    def test_a_module_switched_off_is_distinguished_from_a_screen_unticked(self):
        """The whole point: two gates that both say no, for different reasons
        and with different fixes."""
        for key in ("broiler", "hatchery"):
            GroupMobileAccess.objects.create(group=self.group, module_key=key,
                                             enabled=key != "broiler", position=0)
        verdict = explain(self.user(), TAB, "edit")
        self.assertTrue(verdict["web"])
        self.assertFalse(verdict["phone"])
        self.assertEqual(verdict["reason"], NO_MODULE)

        GroupMobileAccess.objects.filter(group=self.group).delete()
        GroupMobileTabPermission.objects.create(
            group=self.group, tab_code=TAB, can_view=True, can_add=True,
            can_edit=False, can_delete=False)
        verdict = explain(self.user(), TAB, "edit")
        self.assertTrue(verdict["web"])
        self.assertFalse(verdict["phone"])
        self.assertEqual(verdict["reason"], NO_SCREEN)

    def test_a_tab_with_no_phone_screen_is_not_applicable_not_denied(self):
        """`None` and `False` mean different things and must not collapse."""
        GroupTabPermission.objects.create(group=self.group,
                                          tab_code="stock_report", can_view=True)
        verdict = explain(self.user(), "stock_report", "view")
        self.assertTrue(verdict["web"])
        self.assertIsNone(verdict["phone"])

    def test_a_superuser_is_reported_as_bypassing(self):
        boss = get_user_model().objects.create_superuser("ex_boss", "b@x.com",
                                                         "Str0ngPass!")
        verdict = explain(boss, TAB, "delete")
        self.assertEqual(verdict["reason"], BYPASS)
        self.assertTrue(verdict["phone"])

    def test_an_admin_access_type_is_reported_as_bypassing(self):
        GroupAccessProfile.objects.create(group=self.group, access_type="admin")
        self.assertEqual(explain(self.user(), TAB, "delete")["reason"], BYPASS)

    # ---- the requirement that matters --------------------------------------

    def test_it_never_disagrees_with_the_guards(self):
        """An explanation that computes its own answer is a second
        implementation, and it will drift. Check it against the real ones."""
        from user.access import user_can
        from user.services.mobile_access import GOVERNED_TABS, mobile_can

        GroupMobileTabPermission.objects.create(
            group=self.group, tab_code=TAB, can_view=True, can_add=False,
            can_edit=True, can_delete=False)
        GroupTabPermission.objects.create(
            group=self.group, tab_code="bird_sale_list", can_view=True,
            can_add=True)

        user = self.user()
        for tab in (TAB, "bird_sale_list", "stock_report"):
            for action in ("view", "add", "edit", "delete"):
                with self.subTest(tab=tab, action=action):
                    verdict = explain(user, tab, action)
                    self.assertEqual(verdict["web"], bool(user_can(user, tab, action)))
                    if tab in GOVERNED_TABS:
                        expected = bool(user_can(user, tab, action)
                                        and mobile_can(user, tab, action))
                        self.assertEqual(verdict["phone"], expected)

    # ---- summary -----------------------------------------------------------

    def test_the_summary_flags_an_unconfigured_user(self):
        loose = get_user_model().objects.create_user("ex_loose", "l@x.com",
                                                     "Str0ngPass!")
        self.assertFalse(summarise(loose)["configured"])

    def test_the_summary_reports_the_groups(self):
        self.assertEqual(summarise(self.user())["groups"], ["Explained"])


class ExplainPageTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.admin = User.objects.create_superuser("xp_admin", "a@x.com", "Str0ngPass!")
        self.member = User.objects.create_user("xp_member", "m@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Page Explained")
        self.member.groups.add(self.group)
        GroupTabPermission.objects.create(group=self.group, tab_code=TAB,
                                          can_view=True, can_edit=True)
        self.client.force_login(self.admin)

    def html(self, **params):
        return self.client.get(reverse("access_explain"), params).content.decode()

    def test_it_asks_for_a_user_first(self):
        self.assertIn("Pick a user", self.html())

    def test_it_lists_screens_for_the_chosen_user(self):
        html = self.html(user=self.member.id)
        self.assertIn("Daily Entry", html)
        self.assertIn("Page Explained", html)

    def test_the_search_narrows_the_table(self):
        # Assert on the tab code, which only the table renders — screen titles
        # also appear in the navbar, so matching those proves nothing.
        html = self.html(user=self.member.id, q="daily entry")
        self.assertIn("daily_entry_list", html)
        self.assertNotIn("bird_sale_receipt_list", html)

    def test_it_warns_that_a_superuser_bypasses_everything(self):
        """The page whose absence caused this feature's first bug report."""
        html = self.html(user=self.admin.id)
        self.assertIn("bypasses every access gate", html)

    def test_it_warns_when_no_matrix_is_configured(self):
        loose = get_user_model().objects.create_user("xp_loose", "l@x.com",
                                                     "Str0ngPass!")
        self.assertIn("No permission matrix is configured",
                      self.html(user=loose.id))

    def test_a_missing_user_does_not_break_the_page(self):
        self.assertEqual(
            self.client.get(reverse("access_explain"),
                            {"user": "9999999"}).status_code, 200)

    def test_the_tab_is_registered_and_gated(self):
        from user.access import ALL_TAB_CODES, allowed_view_tabs

        self.assertIn("access_explain", ALL_TAB_CODES)
        self.assertEqual(reverse("access_explain"), "/explain-access/")
        member = get_user_model().objects.get(pk=self.member.pk)
        self.assertNotIn("access_explain", allowed_view_tabs(member))
