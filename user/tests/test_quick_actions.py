"""The dashboard's Quick Actions row.

Each card is gated on a tab code. A wrong code does not raise — the card just
never renders, for anybody — which is exactly how the widget registry drifted
before it was pinned down. These tests fail loudly instead.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from user.models import GroupTabPermission

#: label -> the tab code and url name behind it (they are the same string).
QUICK_ACTIONS = [
    ("Batch Creation", "broiler_batch"),
    ("Chicks Placement", "chicks_placement_list"),
    ("Stock Transfer", "stock_transfer_list"),
    ("Daily Entry", "daily_entry_list"),
    ("Medicine &amp; Vaccine Consumption", "medicine_entry_list"),
    ("Bird Sale", "bird_sale_list"),
    ("Bird Receipt", "bird_sale_receipt_list"),
]


class QuickActionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser("qaadmin", "q@x.com", "Str0ngPass!")

    def dashboard(self, user):
        self.client.force_login(user)
        return self.client.get(reverse("dashboard")).content.decode()

    def test_every_quick_action_renders_for_a_superuser(self):
        """Catches a mistyped tab code: it would silently hide the card."""
        html = self.dashboard(self.admin)
        for label, code in QUICK_ACTIONS:
            with self.subTest(action=label):
                self.assertIn(label, html)
                self.assertIn(f'href="{reverse(code)}"', html)

    def test_quick_actions_open_in_a_new_tab(self):
        """Same as the search results — the dashboard stays where it was."""
        html = self.dashboard(self.admin)
        for label, code in QUICK_ACTIONS:
            with self.subTest(action=label):
                self.assertIn(f'href="{reverse(code)}" target="_blank" rel="noopener"',
                              html)

    def test_the_workspace_row_is_gone(self):
        """Quick Actions replaced it; the module cards duplicated the navbar."""
        html = self.dashboard(self.admin)
        self.assertNotIn("Workspace", html)
        self.assertNotIn("dash-module", html)

    def test_every_quick_action_code_is_a_real_tab(self):
        from user.access import ALL_TAB_CODES

        for label, code in QUICK_ACTIONS:
            with self.subTest(action=label):
                self.assertIn(code, ALL_TAB_CODES)

    def test_a_user_only_sees_the_actions_they_may_open(self):
        User = get_user_model()
        clerk = User.objects.create_user("qaclerk", "c@x.com", "Str0ngPass!")
        group = Group.objects.create(name="Daily Entry Only")
        clerk.groups.add(group)
        GroupTabPermission.objects.create(group=group, tab_code="daily_entry_list",
                                          can_view=True)

        html = self.dashboard(clerk)
        self.assertIn("Daily Entry", html)
        for label, code in QUICK_ACTIONS:
            if code == "daily_entry_list":
                continue
            with self.subTest(action=label):
                self.assertNotIn(f'class="qa-card" href="{reverse(code)}"', html)

    def test_the_whole_row_is_dropped_for_a_user_with_no_actions(self):
        """Quick Actions is a dashboard panel now, so a user with none of its
        tabs gets no heading and no empty row — not a row with nothing in it."""
        User = get_user_model()
        outsider = User.objects.create_user("qanone", "n@x.com", "Str0ngPass!")
        group = Group.objects.create(name="No Broiler")
        outsider.groups.add(group)
        GroupTabPermission.objects.create(group=group, tab_code="items", can_view=True)

        html = self.dashboard(outsider)
        self.assertNotIn('class="qa-card"', html)
        # the heading travels with the row (the words also appear in a CSS
        # comment, so match the element rather than the text)
        self.assertNotIn(">Quick Actions</h2>", html)
