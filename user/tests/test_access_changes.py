"""User > Access Changes — the audit trail for access edits.

Two gaps this covers. The log recorded only Mobile Access saves, so the other
two editors changed people's access silently; and nothing read the table at
all, so the question it exists to answer ("who turned this off?") still needed
a database shell.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from user.models import (AccessChangeLog, GroupDashboardWidget,
                         GroupTabPermission)


class RecordingTests(TestCase):
    """Every editor writes an entry, and they phrase them the same way."""

    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.admin = User.objects.create_superuser("ac_admin", "a@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Audited Group")
        GroupTabPermission.objects.create(
            group=self.group, tab_code="daily_entry_list", can_view=True,
            can_add=True, can_edit=True)
        self.client.force_login(self.admin)

    def entries(self, surface=None):
        rows = AccessChangeLog.objects.filter(group=self.group)
        if surface:
            rows = rows.filter(surface=surface)
        return list(rows)

    # ---- web ---------------------------------------------------------------

    def test_a_web_access_save_is_recorded(self):
        """This surface recorded nothing at all before."""
        self.client.post(reverse("user_groups"), {
            "group": self.group.id, "name": self.group.name,
            "perm_daily_entry_list_view": "on",
        })
        rows = self.entries("web")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].changed_by, "ac_admin")

    def test_the_web_entry_names_the_tab_that_moved(self):
        self.client.post(reverse("user_groups"), {
            "group": self.group.id, "name": self.group.name,
            "perm_daily_entry_list_view": "on",     # add + edit dropped
        })
        row = self.entries("web")[0]
        moved = row.detail["changes"]
        self.assertIn("daily_entry_list", moved)
        self.assertEqual(moved["daily_entry_list"]["can_add"], [True, False])
        self.assertIn("Daily Entry", row.summary)

    # ---- dashboard ---------------------------------------------------------

    def test_a_dashboard_access_save_is_recorded(self):
        self.client.post(reverse("dashboard_access_form"),
                         {"group": self.group.id, "on_live_flock": "on"})
        rows = self.entries("dashboard")
        self.assertEqual(len(rows), 1)
        self.assertIn("widget", rows[0].summary)

    def test_the_dashboard_entry_records_order_moves_too(self):
        GroupDashboardWidget.objects.create(group=self.group,
                                            widget_key="live_flock",
                                            enabled=True, position=0)
        self.client.post(reverse("dashboard_access_form"),
                         {"group": self.group.id, "on_live_flock": "on",
                          "pos_live_flock": "5"})
        moved = self.entries("dashboard")[0].detail["changes"]
        self.assertEqual(moved["live_flock"]["position"], [0, 5])

    # ---- mobile ------------------------------------------------------------

    def test_a_mobile_access_save_is_recorded(self):
        self.client.post(reverse("mobile_access_form"),
                         {"group": self.group.id, "p_daily_entry_list_view": "on"})
        self.assertEqual(len(self.entries("mobile")), 1)

    def test_all_three_surfaces_share_one_shape(self):
        """They are read together on one page, so an entry from one must not
        need different handling from another."""
        self.client.post(reverse("user_groups"), {
            "group": self.group.id, "name": self.group.name,
            "perm_daily_entry_list_view": "on"})
        self.client.post(reverse("dashboard_access_form"),
                         {"group": self.group.id, "on_live_flock": "on"})
        self.client.post(reverse("mobile_access_form"),
                         {"group": self.group.id, "p_daily_entry_list_view": "on"})

        surfaces = {r.surface for r in self.entries()}
        self.assertEqual(surfaces, {"web", "dashboard", "mobile"})
        for row in self.entries():
            with self.subTest(surface=row.surface):
                self.assertIn("changes", row.detail)
                self.assertIsInstance(row.detail["changes"], dict)
                self.assertTrue(row.summary)
                self.assertEqual(row.changed_by, "ac_admin")

    def test_a_save_that_changes_nothing_says_so(self):
        for _ in range(2):
            self.client.post(reverse("mobile_access_form"),
                             {"group": self.group.id,
                              "p_daily_entry_list_view": "on"})
        self.assertEqual(self.entries("mobile")[0].summary.split(";")[0],
                         "No change")


class AccessChangesPageTests(TestCase):
    """The page that made the log readable."""

    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.admin = User.objects.create_superuser("ap_admin", "p@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Page Group")
        self.other = Group.objects.create(name="Other Group")
        AccessChangeLog.objects.create(
            surface="web", group=self.group, changed_by="alice",
            summary="1 tab changed: Daily Entry",
            detail={"changes": {"daily_entry_list": {"can_edit": [True, False]}}})
        AccessChangeLog.objects.create(
            surface="mobile", group=self.other, changed_by="bob",
            summary="1 screen changed: Bird Sale",
            detail={"changes": {"bird_sale_list": {"can_add": [False, True]}}})
        self.client.force_login(self.admin)

    def html(self, **params):
        return self.client.get(reverse("access_changes"), params).content.decode()

    def test_the_page_lists_entries_from_every_surface(self):
        html = self.html()
        self.assertIn("alice", html)
        self.assertIn("bob", html)
        self.assertIn("Page Group", html)
        self.assertIn("Other Group", html)

    def test_it_renders_the_before_and_after(self):
        """Raw JSON would make an administrator decode it themselves."""
        html = self.html()
        self.assertIn("can_edit: on → off", html)
        self.assertIn("can_add: off → on", html)

    def test_it_filters_by_group(self):
        html = self.html(group=self.group.id)
        self.assertIn("alice", html)
        self.assertNotIn("bob", html)

    def test_it_filters_by_surface(self):
        html = self.html(surface="mobile")
        self.assertIn("bob", html)
        self.assertNotIn("alice", html)

    def test_an_empty_filter_says_so_rather_than_showing_nothing(self):
        empty = Group.objects.create(name="Never Touched")
        self.assertIn("No access changes recorded", self.html(group=empty.id))

    def test_rubbish_filters_do_not_break_the_page(self):
        self.assertEqual(
            self.client.get(reverse("access_changes"),
                            {"group": "abc", "surface": "nope"}).status_code, 200)

    def test_the_tab_is_registered_and_permission_gated(self):
        from user.access import ALL_TAB_CODES, allowed_view_tabs

        self.assertIn("access_changes", ALL_TAB_CODES)
        self.assertEqual(reverse("access_changes"), "/access-changes/")

        User = get_user_model()
        member = User.objects.create_user("ap_member", "m@x.com", "Str0ngPass!")
        plain = Group.objects.create(name="Plain")
        member.groups.add(plain)
        GroupTabPermission.objects.create(group=plain, tab_code="items",
                                          can_view=True)
        member = User.objects.get(pk=member.pk)
        self.assertNotIn("access_changes", allowed_view_tabs(member))
