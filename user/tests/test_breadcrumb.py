"""The breadcrumb is computed from the nav registry, not written per template.

That is the whole point: ~180 pages would otherwise each carry their own trail,
and those trails would drift from the nav the first time a tab moved.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from user.access import breadcrumb_for


class BreadcrumbTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser("bc_admin", "bc@x.com",
                                                   "Str0ngPass!")
        self.client.force_login(self.admin)

    def labels(self, url_name):
        return [c["label"] for c in breadcrumb_for(url_name)]

    def test_a_tab_gets_module_section_and_page(self):
        self.assertEqual(self.labels("items"), ["Inventory", "Master", "Items"])
        self.assertEqual(self.labels("stock_transfer_list"),
                         ["Inventory", "Transactions", "Stock Transfer"])
        self.assertEqual(self.labels("supplier_balance"),
                         ["Purchase", "Reports", "Supplier Balance"])

    def test_an_add_page_inherits_its_tab(self):
        """/stock-transfer/add/ is not a tab of its own; it belongs to one."""
        self.assertEqual(self.labels("stock_transfer_add"),
                         ["Inventory", "Transactions", "Stock Transfer"])

    def test_a_page_outside_the_registry_gets_none(self):
        self.assertEqual(breadcrumb_for("dashboard"), [])
        self.assertEqual(breadcrumb_for("login"), [])
        self.assertEqual(breadcrumb_for(""), [])
        self.assertEqual(breadcrumb_for(None), [])

    def test_only_the_last_crumb_is_a_link(self):
        """A module is a dropdown, not a page, and a section's landing page
        depends on what the user may view — so neither is linked here."""
        crumbs = breadcrumb_for("items")
        self.assertEqual([bool(c["url"]) for c in crumbs], [False, False, True])
        self.assertTrue(crumbs[-1].get("current"))

    def test_a_page_the_user_cannot_view_is_not_linked(self):
        crumbs = breadcrumb_for("items", viewable=set())
        self.assertEqual(crumbs[-1]["url"], "")

    def test_it_renders_on_the_page(self):
        html = self.client.get(reverse("items")).content.decode()
        self.assertIn('class="ds-breadcrumb"', html)
        self.assertIn("Inventory", html)
        self.assertIn("Master", html)

    def test_the_dashboard_has_none(self):
        html = self.client.get(reverse("dashboard")).content.decode()
        self.assertNotIn('class="ds-breadcrumb"', html)

    def test_every_registry_tab_resolves_to_a_trail(self):
        """A tab with no trail would render a page with no breadcrumb at all,
        silently — this fails instead."""
        from user.access import ALL_TAB_CODES

        missing = [code for code in ALL_TAB_CODES if not breadcrumb_for(code)]
        self.assertEqual(missing, [])


class SidebarTests(TestCase):
    """The sidebar is generated from the registry, so it cannot drift from the
    guard the way a hand-written navbar does."""

    def setUp(self):
        from django.contrib.auth.models import Group
        from user.models import GroupAccessProfile, GroupTabPermission

        User = get_user_model()
        self.admin = User.objects.create_superuser("sb_admin", "sb@x.com",
                                                   "Str0ngPass!")
        self.clerk = User.objects.create_user("sb_clerk", "sc@x.com", "Str0ngPass!")
        group = Group.objects.create(name="Items Only Sidebar")
        self.clerk.groups.add(group)
        GroupAccessProfile.objects.create(group=group)
        GroupTabPermission.objects.create(group=group, tab_code="items",
                                          can_view=True)

    def nav(self, user, active=None):
        from user.services.navigation import sidebar_for
        return sidebar_for(get_user_model().objects.get(pk=user.pk), active)

    def test_a_superuser_gets_every_module(self):
        nav = self.nav(self.admin)
        self.assertIn("Inventory", [m["label"] for m in nav])
        self.assertIn("Broiler", [m["label"] for m in nav])

    def test_it_is_filtered_by_the_same_permissions_as_the_guard(self):
        nav = self.nav(self.clerk)
        self.assertEqual([m["label"] for m in nav], ["Inventory"])
        pages = [i["label"] for m in nav for s in m["sections"] for i in s["items"]]
        self.assertEqual(pages, ["Items"])

    def test_empty_modules_and_sections_are_dropped(self):
        """A module the user has no tab in should not appear as a dead heading."""
        for module in self.nav(self.clerk):
            for section in module["sections"]:
                self.assertTrue(section["items"])

    def test_the_active_page_marks_its_module(self):
        nav = self.nav(self.admin, active="items")
        inventory = next(m for m in nav if m["label"] == "Inventory")
        self.assertTrue(inventory["active"])
        self.assertFalse(next(m for m in nav if m["label"] == "Broiler")["active"])

    def test_an_add_page_marks_its_parent_tab(self):
        """extra_urls belong to their tab, so /add/ highlights the same entry."""
        nav = self.nav(self.admin, active="daily_entry_api_list")
        broiler = next(m for m in nav if m["label"] == "Broiler")
        self.assertTrue(broiler["active"])

    def test_the_shell_is_off_by_default(self):
        from django.conf import settings

        self.assertFalse(getattr(settings, "DS_SIDEBAR", False))
        self.client.force_login(self.admin)
        html = self.client.get(reverse("items")).content.decode()
        self.assertNotIn('id="dsSidebar"', html)

    def test_the_flag_turns_it_on(self):
        from django.test import override_settings

        self.client.force_login(self.admin)
        with override_settings(DS_SIDEBAR=True):
            html = self.client.get(reverse("items")).content.decode()
        self.assertIn('id="dsSidebar"', html)
        self.assertIn('class="ds-shell"', html)


class ReportStandardTests(TestCase):
    """Spec 25: a printed report must say when it was produced and by whom."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(
            "rs_admin", "rs@x.com", "Str0ngPass!",
            first_name="Asha", last_name="Rao")
        self.client.force_login(self.admin)

    def test_every_report_carries_a_generated_stamp(self):
        for name in ("stock_report", "item_ledger_report", "negative_stock_report",
                     "supplier_balance", "customer_balance", "purchase_report"):
            with self.subTest(report=name):
                html = self.client.get(reverse(name)).content.decode()
                self.assertIn('class="co-stamp"', html)
                self.assertIn("Generated", html)

    def test_the_stamp_names_the_person_who_ran_it(self):
        """A copy on someone's desk should say who produced it."""
        html = self.client.get(reverse("stock_report")).content.decode()
        self.assertIn("Asha Rao", html)

    def test_the_letterhead_is_shared_rather_than_copied(self):
        """29 reports include it; a stamp added to one template reaches all."""
        import pathlib

        users = [p for p in pathlib.Path(".").rglob("*.html")
                 if ".venv" not in p.parts and "staticfiles" not in p.parts
                 and "_report_letterhead" in p.read_text(encoding="utf-8", errors="ignore")]
        self.assertGreater(len(users), 20)
