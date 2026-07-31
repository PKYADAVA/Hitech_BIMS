"""The Web-Access editor must not imply a restriction it does not apply.

Access Type = Admin bypasses the matrix entirely (see
``user.access._user_is_unrestricted``), so a group can show one ticked box and
still have all 138 tabs. The editor warns about that; these tests pin both the
warning and the behaviour it describes.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from user.access import ALL_TAB_CODES, allowed_view_tabs, user_can
from user.models import GroupAccessProfile, GroupTabPermission


class AdminAccessTypeTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser("wa_admin", "w@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Warehouse Team")
        GroupTabPermission.objects.create(group=self.group, tab_code="items",
                                          can_view=True)
        self.member = User.objects.create_user("wa_member", "m@x.com", "Str0ngPass!")
        self.member.groups.add(self.group)

    def profile(self, access_type):
        GroupAccessProfile.objects.update_or_create(
            group=self.group, defaults={"access_type": access_type})
        return get_user_model().objects.get(pk=self.member.pk)

    # ---- the behaviour the warning is about -------------------------------

    def test_sub_admin_is_held_to_the_matrix(self):
        user = self.profile("sub_admin")
        self.assertEqual(allowed_view_tabs(user), {"items"})
        self.assertFalse(user_can(user, "coa", "view"))

    def test_admin_ignores_every_ticked_box(self):
        """Same single ticked row; only the toggle changes."""
        user = self.profile("admin")
        self.assertEqual(allowed_view_tabs(user), set(ALL_TAB_CODES))
        self.assertTrue(user_can(user, "coa", "view"))
        self.assertTrue(user_can(user, "coa", "delete"))

    def test_one_admin_group_overrides_a_restricted_one(self):
        """The check is an exists() across the user's groups, so Admin wins —
        adding someone to an Admin group cannot be offset elsewhere."""
        self.profile("sub_admin")
        loose = Group.objects.create(name="Anything Goes")
        GroupAccessProfile.objects.create(group=loose, access_type="admin")
        self.member.groups.add(loose)

        user = get_user_model().objects.get(pk=self.member.pk)
        self.assertEqual(allowed_view_tabs(user), set(ALL_TAB_CODES))

    def test_admin_access_type_is_not_django_admin(self):
        """It grants the whole ERP but not /admin/, which is superuser-only."""
        self.profile("admin")
        self.client.force_login(self.member)
        response = self.client.get("/admin/", follow=False)
        self.assertEqual(response.status_code, 302)

    # ---- the warning itself -----------------------------------------------

    def test_the_editor_warns_that_admin_ignores_the_matrix(self):
        self.client.force_login(self.admin)
        # The editor only renders for a selected group.
        html = self.client.get(reverse("user_groups"),
                               {"group": self.group.id}).content.decode()
        self.assertIn('id="wa-admin-note"', html)
        self.assertIn("the permissions below are ignored", html)
        # and it is driven by the radio rather than being always visible
        self.assertIn("wa-is-admin", html)

    def test_the_matrix_inputs_are_not_disabled_by_the_warning(self):
        """Dimming is visual only. Disabled inputs would not post, so saving a
        group while Admin was selected would wipe whatever was ticked."""
        self.client.force_login(self.admin)
        html = self.client.get(reverse("user_groups"),
                               {"group": self.group.id}).content.decode()
        matrix = html.split('class="wa-matrix"')[1]
        self.assertNotIn("disabled", matrix[:matrix.index("</table>")])
