"""Access changes made from the phone are audited too.

The web editors recorded their saves and the API endpoints did not, so "who
turned Sales off?" was answerable only when the answer was "someone at a desk".
These three endpoints are the ones that change access, and one of them grants a
whole module of tabs in a single call.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TestCase

from user.models import AccessChangeLog, GroupMobileAccess, GroupTabPermission

ROLE_MODULE = "/api/v1/user/roles/{}/module"
MOBILE_MODULE = "/api/v1/user/roles/{}/mobile-module"
USER_ROLES = "/api/v1/user/users/{}/roles"


class ApiAuditTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.admin = User.objects.create_superuser("aa_admin", "a@x.com", "Str0ngPass!")
        self.member = User.objects.create_user("aa_member", "m@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Api Audited")
        self.client.force_login(self.admin)

    def post(self, url, payload):
        return self.client.post(url, payload, content_type="application/json")

    def entries(self, surface=None):
        rows = AccessChangeLog.objects.all()
        if surface:
            rows = rows.filter(surface=surface)
        return list(rows)

    # ---- granting a whole module -------------------------------------------

    def test_granting_a_module_is_recorded(self):
        """The largest single change either editor can make."""
        response = self.post(ROLE_MODULE.format(self.group.id),
                             {"module": "sales", "enabled": True})
        self.assertEqual(response.status_code, 200)

        rows = self.entries("web")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].changed_by, "aa_admin")
        self.assertIn("sales", rows[0].summary)
        self.assertIn("granted", rows[0].summary)

    def test_revoking_a_module_is_recorded_with_what_it_removed(self):
        self.post(ROLE_MODULE.format(self.group.id),
                  {"module": "sales", "enabled": True})
        self.post(ROLE_MODULE.format(self.group.id),
                  {"module": "sales", "enabled": False})

        latest = self.entries("web")[0]
        self.assertIn("revoked", latest.summary)
        # The tabs it took away are named, not just counted.
        self.assertTrue(latest.detail["changes"])

    def test_it_is_marked_as_coming_from_the_phone(self):
        """Where a change was made is half of who made it."""
        self.post(ROLE_MODULE.format(self.group.id),
                  {"module": "sales", "enabled": True})
        self.assertEqual(self.entries("web")[0].source, "mobile")

    def test_a_no_op_grant_still_records_honestly(self):
        for _ in range(2):
            self.post(ROLE_MODULE.format(self.group.id),
                      {"module": "sales", "enabled": True})
        self.assertEqual(self.entries("web")[0].summary.split(";")[0], "No change")

    # ---- the phone module switch -------------------------------------------

    def test_toggling_a_phone_module_is_recorded(self):
        self.post(MOBILE_MODULE.format(self.group.id),
                  {"module": "sales", "enabled": False})
        rows = self.entries("mobile_module")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].detail["changes"]["sales"]["enabled"], [True, False])

    def test_a_phone_module_change_can_be_reverted(self):
        from django.urls import reverse

        self.post(MOBILE_MODULE.format(self.group.id),
                  {"module": "sales", "enabled": False})
        self.assertFalse(GroupMobileAccess.objects.get(
            group=self.group, module_key="sales").enabled)

        entry = self.entries("mobile_module")[0]
        self.client.post(reverse("access_change_revert", args=[entry.id]))
        self.assertTrue(GroupMobileAccess.objects.get(
            group=self.group, module_key="sales").enabled)

    # ---- membership --------------------------------------------------------

    def test_adding_a_user_to_a_role_is_recorded(self):
        """Membership decides which matrices apply, so moving someone between
        roles changes their access as surely as editing one."""
        self.post(USER_ROLES.format(self.member.id), {"group_ids": [self.group.id]})
        rows = self.entries("membership")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].group_id, self.group.id)
        self.assertIn("Added", rows[0].summary)
        self.assertIn("aa_member", rows[0].summary)

    def test_removing_a_user_is_recorded(self):
        self.member.groups.add(self.group)
        self.post(USER_ROLES.format(self.member.id), {"group_ids": []})
        self.assertIn("Removed", self.entries("membership")[0].summary)

    def test_only_the_groups_that_moved_are_recorded(self):
        stay = Group.objects.create(name="Unchanged")
        self.member.groups.add(stay)
        self.post(USER_ROLES.format(self.member.id),
                  {"group_ids": [stay.id, self.group.id]})

        groups = {row.group_id for row in self.entries("membership")}
        self.assertEqual(groups, {self.group.id})

    def test_membership_entries_are_not_revertable(self):
        """They record who joined or left, not a row of fields to put back."""
        from user.services.access_log import REVERTABLE

        self.assertNotIn("membership", REVERTABLE)

    # ---- the trail as a whole ----------------------------------------------

    def test_every_access_writing_endpoint_leaves_a_trail(self):
        self.post(ROLE_MODULE.format(self.group.id),
                  {"module": "sales", "enabled": True})
        self.post(MOBILE_MODULE.format(self.group.id),
                  {"module": "sales", "enabled": False})
        self.post(USER_ROLES.format(self.member.id), {"group_ids": [self.group.id]})

        self.assertEqual({r.surface for r in self.entries()},
                         {"web", "mobile_module", "membership"})
        for row in self.entries():
            with self.subTest(surface=row.surface):
                self.assertEqual(row.source, "mobile")
                self.assertEqual(row.changed_by, "aa_admin")

    def test_the_page_shows_a_phone_change_as_such(self):
        from django.urls import reverse

        self.post(ROLE_MODULE.format(self.group.id),
                  {"module": "sales", "enabled": True})
        html = self.client.get(reverse("access_changes")).content.decode()
        self.assertIn("Made from the phone app", html)

    def test_auditing_never_breaks_the_endpoint(self):
        from unittest.mock import patch

        with patch("user.models.AccessChangeLog.objects.create",
                   side_effect=RuntimeError("boom")):
            response = self.post(ROLE_MODULE.format(self.group.id),
                                 {"module": "sales", "enabled": True})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(GroupTabPermission.objects.filter(group=self.group).exists())
