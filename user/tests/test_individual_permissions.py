"""One person's own tab matrix, instead of their role's.

Groups answer "what may this role do", which is right until one person in a
role needs something the rest of it does not. Giving them a group of their own
works and leaves a group per person behind for whoever inherits the system.

An individual matrix **replaces** the group's rather than adding to or
subtracting from it, so one place answers "what may this person reach" — the
property that makes a permission auditable. It is switched on per user, and
while the switch is off nothing here applies.
"""
from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from user.access import (allowed_view_tabs, uses_individual_permissions,
                         user_can)
from user.models import GroupTabPermission, UserProfile, UserTabPermission


class IndividualPermissionTests(TestCase):
    def setUp(self):
        self.group = Group.objects.create(name="Branch Manager")
        # The role can reach two tabs.
        GroupTabPermission.objects.create(group=self.group, tab_code="daily_entry_list",
                                          can_view=True, can_add=True)
        GroupTabPermission.objects.create(group=self.group, tab_code="bird_sale_list",
                                          can_view=True)
        self.user = User.objects.create_user("rajesh", "r@x.com", "Str0ngPass!")
        self.user.groups.add(self.group)

    def give_own(self, **tabs):
        profile, _ = UserProfile.objects.get_or_create(user=self.user)
        profile.individual_permissions = True
        profile.save()
        for code, actions in tabs.items():
            UserTabPermission.objects.create(
                user=self.user, tab_code=code,
                **{f"can_{a}": True for a in actions})

    # ---- while the switch is off -------------------------------------------

    def test_the_groups_answer_until_the_switch_is_on(self):
        self.assertFalse(uses_individual_permissions(self.user))
        self.assertTrue(user_can(self.user, "daily_entry_list", "view"))
        self.assertEqual(allowed_view_tabs(self.user),
                         {"daily_entry_list", "bird_sale_list"})

    def test_rows_alone_change_nothing(self):
        """Prepared but not switched on: the groups still decide. Ticking a
        matrix must not silently take effect."""
        UserTabPermission.objects.create(user=self.user, tab_code="broiler_batch",
                                         can_view=True)
        self.assertFalse(user_can(self.user, "broiler_batch", "view"))
        self.assertTrue(user_can(self.user, "daily_entry_list", "view"))

    # ---- once it is on ------------------------------------------------------

    def test_the_individual_matrix_replaces_the_group_s(self):
        """Replace, not union: a tab the role grants is gone unless it is
        ticked here too."""
        self.give_own(broiler_batch=["view"])
        self.assertEqual(allowed_view_tabs(self.user), {"broiler_batch"})
        self.assertTrue(user_can(self.user, "broiler_batch", "view"))
        self.assertFalse(user_can(self.user, "daily_entry_list", "view"))

    def test_it_can_grant_what_no_group_grants(self):
        self.give_own(warehouse=["view", "add"])
        self.assertTrue(user_can(self.user, "warehouse", "add"))

    def test_any_ticked_action_grants_the_page(self):
        """Same rule as the group matrix: Add alone implies reaching the page,
        or the Add could never be used."""
        self.give_own(warehouse=["add"])
        self.assertTrue(user_can(self.user, "warehouse", "view"))
        self.assertFalse(user_can(self.user, "warehouse", "delete"))

    def test_an_empty_individual_matrix_means_nothing_not_everything(self):
        """The trap this switch exists to avoid. With no rows and the switch on,
        the fail-open for unconfigured users must not apply — it would hand over
        every tab at the moment access was meant to be removed.
        """
        profile, _ = UserProfile.objects.get_or_create(user=self.user)
        profile.individual_permissions = True
        profile.save()
        self.assertEqual(allowed_view_tabs(self.user), set())
        self.assertFalse(user_can(self.user, "daily_entry_list", "view"))

    def test_a_superuser_still_bypasses_everything(self):
        boss = User.objects.create_superuser("boss", "b@x.com", "Str0ngPass!")
        UserProfile.objects.create(user=boss, individual_permissions=True)
        self.assertTrue(user_can(boss, "daily_entry_list", "view"))

    # ---- the phone sees the same answer -------------------------------------

    def test_the_mobile_payload_follows_the_individual_matrix(self):
        from rest_framework_simplejwt.tokens import RefreshToken

        self.give_own(broiler_batch=["view", "add"])
        tok = str(RefreshToken.for_user(self.user).access_token)
        resp = self.client.get("/api/v1/auth/permissions",
                               HTTP_AUTHORIZATION=f"Bearer {tok}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertIn("broiler_batch", data["tabs"])
        self.assertNotIn("daily_entry_list", data["tabs"])


class PermissionEditorTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("boss", "b@x.com", "Str0ngPass!")
        self.subject = User.objects.create_user("rajesh", "r@x.com", "Str0ngPass!")
        self.client.force_login(self.admin)

    def url(self):
        return reverse("create_user_permissions", args=[self.subject.id])

    def test_the_page_renders_the_matrix_and_the_switch(self):
        page = self.client.get(self.url()).content.decode()
        self.assertIn("Individual Permissions", page)
        self.assertIn("individual_permissions", page)
        self.assertIn("perm_daily_entry_list_view", page)

    def test_saving_stores_the_ticked_tabs_and_the_switch(self):
        self.client.post(self.url(), {
            "individual_permissions": "on",
            "perm_daily_entry_list_view": "on",
            "perm_daily_entry_list_add": "on",
            "perm_warehouse_view": "on",
        })
        profile = UserProfile.objects.get(user=self.subject)
        self.assertTrue(profile.individual_permissions)
        rows = {r.tab_code: r for r in UserTabPermission.objects.filter(user=self.subject)}
        self.assertEqual(set(rows), {"daily_entry_list", "warehouse"})
        self.assertTrue(rows["daily_entry_list"].can_add)
        self.assertFalse(rows["warehouse"].can_add)

    def test_clearing_a_tick_removes_it(self):
        """The form posts the whole grid, so a cleared box has to become a
        missing row rather than a leftover one."""
        self.client.post(self.url(), {"individual_permissions": "on",
                                      "perm_daily_entry_list_view": "on"})
        self.client.post(self.url(), {"individual_permissions": "on",
                                      "perm_warehouse_view": "on"})
        self.assertEqual(
            list(UserTabPermission.objects.filter(user=self.subject)
                 .values_list("tab_code", flat=True)),
            ["warehouse"])

    def test_switching_it_off_keeps_the_prepared_matrix(self):
        """Turning the switch off hands the user back to their groups without
        throwing away what was set up, so it can be turned on again."""
        self.client.post(self.url(), {"individual_permissions": "on",
                                      "perm_warehouse_view": "on"})
        self.client.post(self.url(), {"perm_warehouse_view": "on"})
        profile = UserProfile.objects.get(user=self.subject)
        self.assertFalse(profile.individual_permissions)
        self.assertEqual(UserTabPermission.objects.filter(user=self.subject).count(), 1)

    def test_the_users_page_offers_the_link(self):
        page = self.client.get(reverse("create_user")).content.decode()
        self.assertIn(f"/user/{self.subject.id}/permissions/", page)
