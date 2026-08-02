"""Undoing a recorded access change.

Cheap only because the log already stores both sides. The two rules it must not
bend: the undo is itself recorded rather than erasing the entry, and it writes
the same tables the editors write, so every gate downstream still applies.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from user.models import (AccessChangeLog, GroupDashboardWidget,
                         GroupMobileTabPermission, GroupTabPermission)

TAB = "daily_entry_list"


class RevertTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.admin = User.objects.create_superuser("rv_admin", "a@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Revert Group")
        GroupTabPermission.objects.create(
            group=self.group, tab_code=TAB, can_view=True, can_add=True,
            can_edit=True, can_delete=True)
        self.client.force_login(self.admin)

    def latest(self, surface=None):
        rows = AccessChangeLog.objects.filter(group=self.group)
        if surface:
            rows = rows.filter(surface=surface)
        return rows.first()

    def revert(self, entry):
        return self.client.post(
            reverse("access_change_revert", args=[entry.id]), follow=False)

    # ---- mobile ------------------------------------------------------------

    def test_it_puts_back_what_a_mobile_save_replaced(self):
        self.client.post(reverse("mobile_access_form"),
                         {"group": self.group.id, f"p_{TAB}_view": "on",
                          f"p_{TAB}_edit": "on"})
        self.client.post(reverse("mobile_access_form"),
                         {"group": self.group.id, f"p_{TAB}_view": "on"})
        row = GroupMobileTabPermission.objects.get(group=self.group, tab_code=TAB)
        self.assertFalse(row.can_edit)

        self.revert(self.latest("mobile"))
        row.refresh_from_db()
        self.assertTrue(row.can_edit)

    def test_the_undo_is_recorded_rather_than_erasing_the_entry(self):
        """An audit trail that can delete its own rows answers a weaker
        question than one that cannot."""
        self.client.post(reverse("mobile_access_form"),
                         {"group": self.group.id, f"p_{TAB}_view": "on"})
        entry = self.latest("mobile")
        before = AccessChangeLog.objects.count()

        self.revert(entry)
        self.assertTrue(AccessChangeLog.objects.filter(id=entry.id).exists())
        self.assertEqual(AccessChangeLog.objects.count(), before + 1)
        self.assertTrue(self.latest().summary.startswith("Reverted:"))

    def test_the_undo_entry_records_the_opposite_move(self):
        self.client.post(reverse("mobile_access_form"),
                         {"group": self.group.id, f"p_{TAB}_view": "on",
                          f"p_{TAB}_edit": "on"})
        self.client.post(reverse("mobile_access_form"),
                         {"group": self.group.id, f"p_{TAB}_view": "on"})
        self.revert(self.latest("mobile"))

        moved = self.latest().detail["changes"][TAB]
        self.assertEqual(moved["edit"], [False, True])

    def test_reverting_cannot_restore_what_the_web_matrix_withdrew(self):
        """It writes the same table the editor writes, so the gate above it
        still decides."""
        from user.access import user_can

        self.client.post(reverse("mobile_access_form"),
                         {"group": self.group.id, f"p_{TAB}_view": "on",
                          f"p_{TAB}_edit": "on"})
        self.client.post(reverse("mobile_access_form"),
                         {"group": self.group.id, f"p_{TAB}_view": "on"})
        GroupTabPermission.objects.filter(group=self.group, tab_code=TAB).update(
            can_edit=False)

        self.revert(self.latest("mobile"))

        member = get_user_model().objects.create_user("rv_m", "m@x.com", "Str0ngPass!")
        member.groups.add(self.group)
        member = get_user_model().objects.get(pk=member.pk)
        self.assertFalse(user_can(member, TAB, "edit"))

    # ---- web ---------------------------------------------------------------

    def test_it_puts_back_a_web_access_change(self):
        self.client.post(reverse("user_groups"), {
            "group": self.group.id, "name": self.group.name,
            f"perm_{TAB}_view": "on"})           # add/edit/delete dropped
        self.assertFalse(
            GroupTabPermission.objects.get(group=self.group, tab_code=TAB).can_add)

        self.revert(self.latest("web"))
        self.assertTrue(
            GroupTabPermission.objects.get(group=self.group, tab_code=TAB).can_add)

    def test_reverting_to_nothing_removes_the_row(self):
        """A web tab with nothing ticked is stored as absent; an all-false row
        would read as configured."""
        self.client.post(reverse("user_groups"), {
            "group": self.group.id, "name": self.group.name,
            "perm_broiler_batch_view": "on"})
        self.assertTrue(GroupTabPermission.objects.filter(
            group=self.group, tab_code="broiler_batch").exists())

        self.revert(self.latest("web"))
        self.assertFalse(GroupTabPermission.objects.filter(
            group=self.group, tab_code="broiler_batch").exists())

    # ---- dashboard ---------------------------------------------------------

    def test_it_puts_back_a_dashboard_change(self):
        GroupDashboardWidget.objects.create(group=self.group,
                                            widget_key="live_flock",
                                            enabled=True, position=0)
        self.client.post(reverse("dashboard_access_form"), {"group": self.group.id})
        self.assertFalse(GroupDashboardWidget.objects.get(
            group=self.group, widget_key="live_flock").enabled)

        self.revert(self.latest("dashboard"))
        self.assertTrue(GroupDashboardWidget.objects.get(
            group=self.group, widget_key="live_flock").enabled)

    # ---- guards ------------------------------------------------------------

    def test_an_entry_with_no_change_cannot_be_reverted(self):
        entry = AccessChangeLog.objects.create(
            surface="mobile", group=self.group, changed_by="x",
            summary="No change", detail={"changes": {}})
        response = self.revert(entry)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(AccessChangeLog.objects.filter(
            summary__startswith="Reverted").count(), 0)

    def test_an_unrevertable_surface_is_refused(self):
        entry = AccessChangeLog.objects.create(
            surface="mobile_module", group=self.group, changed_by="x",
            summary="something", detail={"changes": {"broiler": {"on": [True, False]}}})
        self.revert(entry)
        self.assertEqual(AccessChangeLog.objects.filter(
            summary__startswith="Reverted").count(), 0)

    def test_a_get_does_not_change_anything(self):
        """Undo is a write; it must not be reachable by following a link."""
        self.client.post(reverse("mobile_access_form"),
                         {"group": self.group.id, f"p_{TAB}_view": "on"})
        entry = self.latest("mobile")
        before = AccessChangeLog.objects.count()
        self.client.get(reverse("access_change_revert", args=[entry.id]))
        self.assertEqual(AccessChangeLog.objects.count(), before)

    def test_the_page_offers_undo_only_where_it_works(self):
        self.client.post(reverse("mobile_access_form"),
                         {"group": self.group.id, f"p_{TAB}_view": "on"})
        AccessChangeLog.objects.create(
            surface="mobile", group=self.group, changed_by="x",
            summary="No change", detail={"changes": {}})
        html = self.client.get(reverse("access_changes")).content.decode()
        self.assertIn("Revert this change", html)
        # one button for the real entry, none for the empty one
        self.assertEqual(html.count("Revert this change"), 1)
