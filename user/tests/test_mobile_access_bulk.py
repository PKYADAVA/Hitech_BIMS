"""Copying a Mobile Access configuration, and applying one save to many groups.

84 rows configured one group at a time is the practical bottleneck of this
feature. Both shortcuts have the same hard requirement as the editor itself:
neither may grant a group access its web matrix withholds.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from user.models import (AccessChangeLog, GroupMobileAccess,
                         GroupMobileTabPermission, GroupTabPermission)
from user.services.mobile_access import group_screen_perms

TAB = "daily_entry_list"
OTHER = "bird_sale_list"


class CopyFromTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.admin = User.objects.create_superuser("cp_admin", "a@x.com", "Str0ngPass!")
        self.source = Group.objects.create(name="Source Group")
        self.target = Group.objects.create(name="Target Group")
        for group in (self.source, self.target):
            GroupTabPermission.objects.create(
                group=group, tab_code=TAB, can_view=True, can_add=True,
                can_edit=True, can_delete=True)
        # The source can also reach a second screen; the target cannot.
        GroupTabPermission.objects.create(
            group=self.source, tab_code=OTHER, can_view=True, can_add=True)
        GroupMobileTabPermission.objects.create(
            group=self.source, tab_code=TAB, can_view=True, can_add=True,
            can_edit=False, can_delete=False)
        GroupMobileTabPermission.objects.create(
            group=self.source, tab_code=OTHER, can_view=True, can_add=True)
        self.client.force_login(self.admin)

    def html(self, **params):
        return self.client.get(reverse("mobile_access_form"),
                               {"group": self.target.id, **params}).content.decode()

    def test_the_form_offers_the_other_groups(self):
        self.assertIn("Copy from", self.html())

    def test_copying_shows_the_source_configuration(self):
        html = self.html(copy_from=self.source.id)
        self.assertIn("Showing “Source Group”", html)
        self.assertIn(f'name="p_{TAB}_view"', html)

    def test_copying_saves_nothing_by_itself(self):
        """It fills the form so it can be reviewed first."""
        self.html(copy_from=self.source.id)
        self.assertFalse(
            GroupMobileTabPermission.objects.filter(group=self.target).exists())

    def test_a_screen_the_target_cannot_reach_is_disabled(self):
        """Copying must not be a way round the web matrix."""
        html = self.html(copy_from=self.source.id)
        marker = f'name="p_{OTHER}_view"'
        row = html[html.index(marker) - 400:html.index(marker) + 200]
        self.assertIn("disabled", row)

    def test_copying_from_itself_is_ignored(self):
        self.assertNotIn("Showing “Target Group”",
                         self.html(copy_from=self.target.id))

    def test_a_rubbish_source_does_not_break_the_page(self):
        self.assertEqual(
            self.client.get(reverse("mobile_access_form"),
                            {"group": self.target.id, "copy_from": "abc"}).status_code,
            200)


class ApplyToManyTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.admin = User.objects.create_superuser("bm_admin", "b@x.com", "Str0ngPass!")
        self.first = Group.objects.create(name="First Group")
        self.second = Group.objects.create(name="Second Group")
        self.narrow = Group.objects.create(name="Narrow Group")
        for group in (self.first, self.second):
            GroupTabPermission.objects.create(
                group=group, tab_code=TAB, can_view=True, can_add=True,
                can_edit=True, can_delete=True)
        # Narrow may view but not add — the same save must respect that.
        GroupTabPermission.objects.create(group=self.narrow, tab_code=TAB,
                                          can_view=True)
        self.client.force_login(self.admin)

    def save(self, also=(), **extra):
        data = {"group": self.first.id, f"p_{TAB}_view": "on",
                f"p_{TAB}_add": "on", **extra}
        if also:
            data["also"] = [g.id for g in also]
        return self.client.post(reverse("mobile_access_form"), data)

    def test_a_plain_save_touches_only_its_own_group(self):
        self.save()
        self.assertTrue(group_screen_perms(self.first))
        self.assertIsNone(group_screen_perms(self.second))

    def test_applying_to_another_group_writes_it_there_too(self):
        self.save(also=[self.second])
        for group in (self.first, self.second):
            with self.subTest(group=group.name):
                perms = group_screen_perms(group)
                self.assertTrue(perms[TAB]["view"])
                self.assertTrue(perms[TAB]["add"])

    def test_each_group_gets_its_own_audit_entry(self):
        """Two groups changed is two facts; one entry would hide which."""
        self.save(also=[self.second])
        groups = {row.group_id for row in AccessChangeLog.objects.all()}
        self.assertEqual(groups, {self.first.id, self.second.id})

    def test_it_cannot_grant_beyond_a_target_s_web_matrix(self):
        """The rule the whole feature rests on, applied through the shortcut.

        The copied row really does say add=on for Narrow — Mobile Access stores
        what the form said. It still cannot add, because the web matrix is
        checked first and never asked this page's opinion.
        """
        from user.access import user_can

        self.save(also=[self.narrow], on_broiler="on")
        self.assertTrue(group_screen_perms(self.narrow)[TAB]["add"])

        member = get_user_model().objects.create_user("bm_m", "m@x.com", "Str0ngPass!")
        member.groups.add(self.narrow)
        member = get_user_model().objects.get(pk=member.pk)

        self.assertTrue(user_can(member, TAB, "view"))
        self.assertFalse(user_can(member, TAB, "add"))

    def test_the_message_names_the_extra_groups(self):
        from django.contrib.messages import get_messages

        response = self.save(also=[self.second])
        text = " ".join(str(m) for m in get_messages(response.wsgi_request))
        self.assertIn("Second Group", text)
        self.assertIn("First Group", text)

    def test_a_group_listed_twice_is_written_once(self):
        self.save(also=[self.first, self.second])
        self.assertEqual(
            AccessChangeLog.objects.filter(group=self.first).count(), 1)

    def test_modules_carry_across_too(self):
        self.save(also=[self.second], on_broiler="on", pos_broiler="3")
        row = GroupMobileAccess.objects.get(group=self.second, module_key="broiler")
        self.assertTrue(row.enabled)
        self.assertEqual(row.position, 3)


class StaleTickDisplayTests(TestCase):
    """A saved tick the web matrix no longer grants shows as off.

    It is not in effect either way — a disabled box does not submit — so
    rendering it ticked claimed access the group did not have.
    """

    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.admin = User.objects.create_superuser("st_admin", "s@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Stale Group")
        GroupTabPermission.objects.create(group=self.group, tab_code=TAB,
                                          can_view=True)   # view only
        GroupMobileTabPermission.objects.create(
            group=self.group, tab_code=TAB, can_view=True, can_edit=True)
        self.client.force_login(self.admin)

    def test_the_revoked_action_renders_unchecked_and_disabled(self):
        html = self.client.get(reverse("mobile_access_form"),
                               {"group": self.group.id}).content.decode()
        marker = f'name="p_{TAB}_edit"'
        row = html[html.index(marker) - 300:html.index(marker) + 260]
        self.assertIn("disabled", row)
        self.assertNotIn("checked", row)

    def test_the_action_still_granted_stays_checked(self):
        html = self.client.get(reverse("mobile_access_form"),
                               {"group": self.group.id}).content.decode()
        marker = f'name="p_{TAB}_view"'
        row = html[html.index(marker) - 300:html.index(marker) + 260]
        self.assertIn("checked", row)
