"""User > Mobile Access — per-group visibility of the phone app's modules.

The rule that matters is the same one Dashboard Access follows: this can only
take a module away. It sits on top of the web tab matrix, so it must never
reveal a module the group cannot open on the web — and switching one off has to
close its API too, not just hide the tile.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from user.models import GroupMobileAccess, GroupTabPermission
from user.services.mobile_access import ALL_KEYS, MOBILE_MODULES

PERMISSIONS_URL = "/api/v1/auth/permissions"


class MobileAccessTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.admin = User.objects.create_superuser("ma_admin", "a@x.com", "Str0ngPass!")
        self.member = User.objects.create_user("ma_member", "m@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Field Staff")
        self.member.groups.add(self.group)
        # A tab in every mobile module, so the matrix is never what is being
        # measured — only Mobile Access.
        from user.access import NAV_GROUPS

        for _key, _title, nav, _icon, _colour in MOBILE_MODULES:
            for tab in sorted(NAV_GROUPS.get(nav, set()))[:1]:
                GroupTabPermission.objects.get_or_create(
                    group=self.group, tab_code=tab, defaults={"can_view": True})

    def navs(self, user=None):
        self.client.force_login(user or self.member)
        return set(self.client.get(PERMISSIONS_URL).json()["data"]["nav_groups"])

    def configure(self, **enabled_by_key):
        GroupMobileAccess.objects.filter(group=self.group).delete()
        for index, key in enumerate(ALL_KEYS):
            GroupMobileAccess.objects.create(
                group=self.group, module_key=key,
                enabled=enabled_by_key.get(key, True), position=index)

    # ---- defaults ---------------------------------------------------------

    def test_an_unconfigured_group_sees_every_module_its_tabs_allow(self):
        """Nothing saved yet must behave exactly as before this feature."""
        self.assertIn("broiler", self.navs())
        self.assertIn("hatchery", self.navs())

    def test_a_superuser_is_unaffected_by_group_rows(self):
        self.configure(broiler=False)
        self.assertIn("broiler", self.navs(self.admin))

    # ---- switching modules off --------------------------------------------

    def test_a_disabled_module_disappears_from_the_phone(self):
        self.configure(broiler=False)
        navs = self.navs()
        self.assertNotIn("broiler", navs)
        self.assertIn("hatchery", navs)

    def test_disabling_everything_leaves_an_empty_hub(self):
        self.configure(**{k: False for k in ALL_KEYS})
        self.assertEqual(self.navs() & set(m[2] for m in MOBILE_MODULES), set())

    def test_it_can_never_grant_a_module_the_matrix_withholds(self):
        """Enabled here, but the group has no permission on any of its tabs."""
        from user.access import NAV_GROUPS

        GroupTabPermission.objects.filter(
            group=self.group, tab_code__in=NAV_GROUPS["sales"]).delete()
        self.configure()
        self.assertNotIn("sales", self.navs())

    def test_the_sms_module_maps_to_the_notifications_nav(self):
        """The phone calls it `sms`, the registry calls it `notifications` —
        the one key where the two names differ."""
        self.configure(sms=False)
        self.assertNotIn("notifications", self.navs())

    def test_the_tabs_of_a_hidden_module_are_dropped_too(self):
        """Hub tiles are gated by RESOURCE_TABS, so a tab surviving its module
        being switched off would leave the tile on screen."""
        from user.access import NAV_GROUPS

        self.configure(broiler=False)
        self.client.force_login(self.member)
        tabs = set(self.client.get(PERMISSIONS_URL).json()["data"]["tabs"])
        self.assertEqual(tabs & NAV_GROUPS["broiler"], set())

    def test_module_actions_drop_with_the_module(self):
        self.configure(broiler=False)
        self.client.force_login(self.member)
        actions = self.client.get(PERMISSIONS_URL).json()["data"]["module_actions"]
        self.assertNotIn("broiler", actions)

    # ---- several groups ---------------------------------------------------

    def test_enabled_in_any_group_wins(self):
        """Matches how the tab matrix combines groups — granted anywhere is
        granted."""
        self.configure(broiler=False)
        other = Group.objects.create(name="Also Field Staff")
        self.member.groups.add(other)
        GroupMobileAccess.objects.create(group=other, module_key="broiler",
                                         enabled=True, position=0)
        self.assertIn("broiler", self.navs())

    def test_the_earliest_position_wins(self):
        from user.services.mobile_access import mobile_preferences

        self.configure()
        GroupMobileAccess.objects.filter(
            group=self.group, module_key="broiler").update(position=7)
        other = Group.objects.create(name="Earlier")
        self.member.groups.add(other)
        GroupMobileAccess.objects.create(group=other, module_key="broiler",
                                         enabled=True, position=2)
        member = get_user_model().objects.get(pk=self.member.pk)
        self.assertEqual(mobile_preferences(member)["broiler"], 2)

    # ---- server-side enforcement ------------------------------------------

    def test_hiding_a_module_closes_its_api_not_just_its_menu(self):
        """Otherwise the tile is hidden and every endpoint behind it stays
        callable by anything holding the token."""
        from user.services.mobile_access import tab_is_mobile_allowed

        self.configure(broiler=False)
        member = get_user_model().objects.get(pk=self.member.pk)
        self.assertFalse(tab_is_mobile_allowed(member, "broiler_batch"))
        self.assertTrue(tab_is_mobile_allowed(member, "egg_purchase_list"))

    def test_an_unconfigured_user_is_not_gated(self):
        from user.services.mobile_access import tab_is_mobile_allowed

        member = get_user_model().objects.get(pk=self.member.pk)
        self.assertTrue(tab_is_mobile_allowed(member, "broiler_batch"))

    def test_a_superuser_bypasses_the_mobile_gate(self):
        from user.services.mobile_access import tab_is_mobile_allowed

        self.configure(**{k: False for k in ALL_KEYS})
        self.assertTrue(tab_is_mobile_allowed(self.admin, "broiler_batch"))

    def test_a_tab_no_mobile_module_owns_is_left_alone(self):
        """Alerts and Change Requests are the two navs with no phone module.
        Gating them here would deny a request this page never claimed to
        govern, so they pass through even with every switch off."""
        from user.access import NAV_GROUPS
        from user.services.mobile_access import NAV_MODULE, tab_is_mobile_allowed

        ungated = sorted(set(NAV_GROUPS) - set(NAV_MODULE))
        self.assertTrue(ungated, "expected at least one nav with no phone module")

        self.configure(**{k: False for k in ALL_KEYS})
        member = get_user_model().objects.get(pk=self.member.pk)
        for nav in ungated:
            for tab in sorted(NAV_GROUPS[nav]):
                with self.subTest(tab=tab):
                    self.assertTrue(tab_is_mobile_allowed(member, tab))

    def test_tracking_follows_the_hr_module(self):
        """Tracking has no nav of its own — it lives under HR, so switching HR
        off takes it with it. Worth pinning: it reads like a separate module."""
        from user.services.mobile_access import tab_is_mobile_allowed

        self.configure(hr=False)
        member = get_user_model().objects.get(pk=self.member.pk)
        self.assertFalse(tab_is_mobile_allowed(member, "tracking_dashboard"))

    # ---- the editor -------------------------------------------------------

    def test_the_page_lists_every_module(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse("mobile_access_form"),
                               {"group": self.group.id}).content.decode()
        for key, title, *_ in MOBILE_MODULES:
            self.assertIn(f'name="on_{key}"', html)
            self.assertIn(f'name="pos_{key}"', html)
            self.assertIn(title, html)

    def test_the_form_says_when_a_group_is_unconfigured(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse("mobile_access_form"),
                               {"group": self.group.id}).content.decode()
        self.assertIn("Nothing is saved", html)

    def test_the_list_shows_only_configured_groups(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse("mobile_access")).content.decode()
        self.assertIn("No group has been configured yet", html)

        self.configure(broiler=False)
        html = self.client.get(reverse("mobile_access")).content.decode()
        self.assertIn("Field Staff", html)
        self.assertIn(f"?group={self.group.id}", html)
        self.assertIn(reverse("mobile_access_delete", args=[self.group.id]), html)

    def test_saving_stores_the_switches_and_positions(self):
        self.client.force_login(self.admin)
        data = {"group": self.group.id}
        for index, key in enumerate(ALL_KEYS):
            data[f"pos_{key}"] = len(ALL_KEYS) - index
            if key != "sales":
                data[f"on_{key}"] = "on"
        response = self.client.post(reverse("mobile_access_form"), data)
        self.assertEqual(response.status_code, 302)

        rows = {r.module_key: r for r in
                GroupMobileAccess.objects.filter(group=self.group)}
        self.assertEqual(len(rows), len(ALL_KEYS))
        self.assertFalse(rows["sales"].enabled)
        self.assertTrue(rows["broiler"].enabled)
        self.assertEqual(rows[ALL_KEYS[0]].position, len(ALL_KEYS))
        self.assertNotIn("sales", self.navs())

    def test_saving_replaces_rather_than_accumulates(self):
        self.client.force_login(self.admin)
        for _ in range(2):
            self.client.post(reverse("mobile_access_form"),
                             {"group": self.group.id,
                              **{f"on_{k}": "on" for k in ALL_KEYS}})
        self.assertEqual(
            GroupMobileAccess.objects.filter(group=self.group).count(),
            len(ALL_KEYS))

    def test_clearing_a_group_returns_it_to_the_default(self):
        self.configure(broiler=False)
        self.assertNotIn("broiler", self.navs())

        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("mobile_access_delete", args=[self.group.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            GroupMobileAccess.objects.filter(group=self.group).exists())
        self.assertIn("broiler", self.navs())

    def test_the_tab_is_registered_and_reachable(self):
        from user.access import ALL_TAB_CODES

        self.assertIn("mobile_access", ALL_TAB_CODES)
        self.assertEqual(reverse("mobile_access"), "/mobile-access/")

    def test_the_nav_link_is_permission_gated(self):
        """Same rule as every other tab: no view right, no link."""
        from user.access import allowed_view_tabs

        member = get_user_model().objects.get(pk=self.member.pk)
        self.assertNotIn("mobile_access", allowed_view_tabs(member))
        GroupTabPermission.objects.create(group=self.group,
                                          tab_code="mobile_access", can_view=True)
        member = get_user_model().objects.get(pk=self.member.pk)
        self.assertIn("mobile_access", allowed_view_tabs(member))


class MobileAccessPreviewTests(TestCase):
    """The Preview action answers for the group, not for whoever clicks it."""

    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.admin = User.objects.create_superuser("mp_admin", "v@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Preview Group")
        self.client.force_login(self.admin)

    def preview(self, **params):
        response = self.client.get(
            reverse("mobile_access_preview", args=[self.group.id]), params)
        self.assertEqual(response.status_code, 200)
        return {m["key"]: m for m in response.json()["modules"]}

    def test_a_module_the_group_cannot_reach_is_marked_unpermitted(self):
        # One row elsewhere, so the group counts as configured — with no rows
        # at all it would be unconfigured, which means unrestricted.
        GroupTabPermission.objects.create(group=self.group, tab_code="items",
                                          can_view=True)
        module = self.preview()["broiler"]
        self.assertFalse(module["shown"])
        self.assertEqual(module["reason"], "No permission on any of its screens")

    def test_a_permitted_and_enabled_module_is_shown(self):
        GroupTabPermission.objects.create(group=self.group,
                                          tab_code="broiler_batch", can_view=True)
        GroupMobileAccess.objects.create(group=self.group, module_key="broiler",
                                         enabled=True, position=0)
        self.assertTrue(self.preview()["broiler"]["shown"])

    def test_switched_off_is_distinguished_from_unpermitted(self):
        """The modal says which gate failed, so the two must not collapse."""
        GroupTabPermission.objects.create(group=self.group,
                                          tab_code="broiler_batch", can_view=True)
        GroupMobileAccess.objects.create(group=self.group, module_key="broiler",
                                         enabled=False, position=0)
        module = self.preview()["broiler"]
        self.assertFalse(module["shown"])
        self.assertEqual(module["reason"], "Switched off here")

    def test_an_override_wins_over_the_saved_rows(self):
        GroupTabPermission.objects.create(group=self.group,
                                          tab_code="broiler_batch", can_view=True)
        GroupMobileAccess.objects.create(group=self.group, module_key="broiler",
                                         enabled=False, position=0)
        self.assertTrue(self.preview(modules="broiler:0")["broiler"]["shown"])

    def test_an_empty_override_means_nothing_enabled(self):
        """Not 'unconfigured' — every switch off must preview as an empty hub,
        not as a full one."""
        GroupTabPermission.objects.create(group=self.group,
                                          tab_code="broiler_batch", can_view=True)
        self.assertFalse(self.preview(modules="")["broiler"]["shown"])

    def test_the_override_still_cannot_beat_the_tab_matrix(self):
        GroupTabPermission.objects.create(group=self.group, tab_code="items",
                                          can_view=True)
        self.assertFalse(self.preview(modules="broiler:0")["broiler"]["shown"])

    def test_rubbish_in_the_override_is_ignored(self):
        GroupTabPermission.objects.create(group=self.group,
                                          tab_code="broiler_batch", can_view=True)
        modules = self.preview(modules="not_a_module:0,broiler:x")
        self.assertTrue(modules["broiler"]["shown"])

    def test_both_pages_carry_the_preview_modal(self):
        GroupMobileAccess.objects.create(group=self.group, module_key="broiler",
                                         enabled=True, position=0)
        for url in (reverse("mobile_access"),
                    reverse("mobile_access_form") + f"?group={self.group.id}"):
            with self.subTest(url=url):
                html = self.client.get(url).content.decode()
                self.assertIn('id="ma-preview"', html)
                self.assertIn(f"mobileAccessPreview({self.group.id}", html)

    def test_the_list_button_sends_no_override(self):
        """From the list nothing is unsaved, so it must show the saved state."""
        GroupMobileAccess.objects.create(group=self.group, module_key="broiler",
                                         enabled=True, position=0)
        html = self.client.get(reverse("mobile_access")).content.decode()
        self.assertIn(f"mobileAccessPreview({self.group.id})", html)


class MobileAccessApiTests(TestCase):
    """The phone's own Manage Access screen edits Mobile Access too.

    Same switch as the web page, reached over the API — so the two must agree
    about what "unconfigured" means or a single toggle would silently disable
    everything else.
    """

    ROLES_URL = "/api/v1/user/access/roles"

    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.admin = User.objects.create_superuser("mq_admin", "q@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Api Role")
        self.client.force_login(self.admin)

    def url(self, group=None):
        return f"/api/v1/user/roles/{(group or self.group).id}/mobile-module"

    def roles(self):
        return self.client.get(self.ROLES_URL).json()["data"]

    def test_the_roles_payload_carries_the_mobile_switches(self):
        data = self.roles()
        self.assertTrue(data["mobile_modules"])
        self.assertEqual({m["key"] for m in data["mobile_modules"]}, set(ALL_KEYS))
        role = next(r for r in data["roles"] if r["id"] == self.group.id)
        self.assertEqual(set(role["mobile"]), set(ALL_KEYS))

    def test_an_unconfigured_role_reads_back_as_all_on(self):
        """Matches what the web editor shows for a first-time group."""
        role = next(r for r in self.roles()["roles"] if r["id"] == self.group.id)
        self.assertTrue(all(role["mobile"].values()))

    def test_toggling_one_module_off_leaves_the_others_on(self):
        """The bug this guards: writing a single row would make the group
        'configured' with one disabled entry, switching every other module off
        with it."""
        response = self.client.post(self.url(), {"module": "sales", "enabled": False},
                                    content_type="application/json")
        self.assertEqual(response.status_code, 200)

        mobile = response.json()["data"]["mobile"]
        self.assertFalse(mobile["sales"])
        self.assertTrue(mobile["broiler"])
        self.assertEqual(
            GroupMobileAccess.objects.filter(group=self.group).count(), len(ALL_KEYS))

    def test_toggling_back_on_restores_it(self):
        for enabled in (False, True):
            response = self.client.post(self.url(), {"module": "sales", "enabled": enabled},
                                        content_type="application/json")
            self.assertIs(response.json()["data"]["mobile"]["sales"], enabled)

    def test_a_toggle_does_not_disturb_the_saved_order(self):
        """Order is set in the web editor; a switch here has no opinion on it."""
        GroupMobileAccess.objects.create(group=self.group, module_key="sales",
                                         enabled=True, position=42)
        self.client.post(self.url(), {"module": "sales", "enabled": False},
                         content_type="application/json")
        row = GroupMobileAccess.objects.get(group=self.group, module_key="sales")
        self.assertEqual(row.position, 42)
        self.assertFalse(row.enabled)

    def test_an_unknown_module_is_refused(self):
        response = self.client.post(self.url(), {"module": "nope", "enabled": True},
                                    content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_an_unknown_role_is_not_found(self):
        response = self.client.post("/api/v1/user/roles/999999/mobile-module",
                                    {"module": "sales", "enabled": True},
                                    content_type="application/json")
        self.assertEqual(response.status_code, 404)

    def test_only_admins_may_edit_mobile_access(self):
        """Same guard as the rest of the RBAC surface."""
        plain = get_user_model().objects.create_user("mq_plain", "p@x.com", "Str0ngPass!")
        self.client.force_login(plain)
        response = self.client.post(self.url(), {"module": "sales", "enabled": False},
                                    content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_the_api_and_the_web_page_agree(self):
        """A module switched off over the API is off on the web page too."""
        self.client.post(self.url(), {"module": "sales", "enabled": False},
                         content_type="application/json")
        html = self.client.get(reverse("mobile_access")).content.decode()
        self.assertIn("Api Role", html)
        self.assertIn(f"{len(ALL_KEYS) - 1} of {len(ALL_KEYS)}", html)


class MobileModuleRegistryTests(TestCase):
    """The registry has to stay in step with both sides it bridges."""

    def test_every_module_maps_to_a_real_nav_group(self):
        from user.access import NAV_GROUPS

        for key, _title, nav, *_ in MOBILE_MODULES:
            with self.subTest(module=key):
                self.assertIn(nav, NAV_GROUPS)

    def test_module_keys_are_unique(self):
        self.assertEqual(len(ALL_KEYS), len(set(ALL_KEYS)))

    def test_the_nav_map_is_invertible(self):
        """NAV_MODULE is the inverse, so two modules must not share a nav."""
        from user.services.mobile_access import MODULE_NAV, NAV_MODULE

        self.assertEqual(len(MODULE_NAV), len(NAV_MODULE))

    def test_every_phone_screen_maps_to_a_real_web_tab(self):
        """A screen whose tab does not exist would be silently dropped from
        the editor, so it is worth failing here instead."""
        from user.access import ALL_TAB_CODES
        from user.services.mobile_access import PHONE_SCREENS

        for key, tab in PHONE_SCREENS:
            with self.subTest(screen=key):
                self.assertIn(tab, ALL_TAB_CODES)

    def test_the_screen_list_matches_the_mobile_client(self):
        """PHONE_SCREENS and RESOURCE_TABS in mobile/src/api/permissions.ts are
        two copies of one fact. They cannot be merged without a build step, so
        this catches the drift instead."""
        import re
        from pathlib import Path

        from django.conf import settings

        from user.services.mobile_access import PHONE_SCREENS

        source = Path(settings.BASE_DIR) / "mobile" / "src" / "api" / "permissions.ts"
        if not source.exists():                       # server-only checkout
            self.skipTest("mobile client not present")

        block = re.search(r"RESOURCE_TABS[^{]*\{(.*?)\n\};",
                          source.read_text(encoding="utf-8"), re.S)
        self.assertIsNotNone(block, "RESOURCE_TABS not found in the client")
        client = dict(re.findall(r'"([^"]+)":\s*"([^"]+)"', block.group(1)))
        self.assertEqual(client, dict(PHONE_SCREENS))

    def test_no_screen_is_listed_twice(self):
        from user.services.mobile_access import PHONE_REPORTS, PHONE_SCREENS

        keys = [k for k, _tab in PHONE_SCREENS]
        self.assertEqual(len(keys), len(set(keys)))
        tabs = [t for _k, t in PHONE_SCREENS]
        # Two rows on one tab would emit duplicate checkbox names and one
        # would silently overwrite the other on save.
        self.assertEqual(len(tabs), len(set(tabs)))
        report_tabs = [t for _k, t in PHONE_REPORTS]
        self.assertEqual(len(report_tabs), len(set(report_tabs)))
        self.assertFalse(set(tabs) & set(report_tabs))

    def test_the_generator_agrees_with_the_checked_in_client(self):
        """`sync_mobile_registry --check` is the one-command fix for drift;
        if it disagrees with the repo, the committed client is stale."""
        from io import StringIO

        from django.core.management import call_command
        from django.core.management.base import CommandError

        try:
            call_command("sync_mobile_registry", "--check", stdout=StringIO())
        except CommandError as exc:
            self.fail(f"client is out of date: {exc}")
        except FileNotFoundError:
            self.skipTest("mobile client not present")

    def test_no_hub_tile_is_silently_ungated(self):
        """The bug that shipped twice, made impossible.

        A tile missing from RESOURCE_TABS is shown to anyone who can open its
        module — that was right for nine screens and wrong for eleven
        inventory ones, and nothing told the two apart. Every tile must now be
        mapped or named in UNGATED_SCREENS with a reason.
        """
        import re
        from pathlib import Path

        from django.conf import settings

        from user.services.mobile_access import RESOURCE_TABS, UNGATED_SCREENS

        catalog = Path(settings.BASE_DIR) / "mobile" / "src" / "config" / "catalog.ts"
        if not catalog.exists():
            self.skipTest("mobile client not present")

        tiles = set()
        for block in re.findall(r"resourceKeys:\s*\[(.*?)\]",
                                catalog.read_text(encoding="utf-8"), re.S):
            tiles.update(re.findall(r'"([a-z0-9-]+)"', block))
        self.assertTrue(tiles, "no hub tiles found — has the catalog moved?")

        unaccounted = sorted(tiles - set(RESOURCE_TABS) - set(UNGATED_SCREENS))
        self.assertEqual(
            unaccounted, [],
            "These phone screens are ungated: anyone who can open the module "
            "sees them. Map them in PHONE_SCREENS, or add them to "
            "UNGATED_SCREENS with the reason.")

    def test_the_ungated_list_stays_honest(self):
        """An entry that has since been mapped, or a tile that no longer
        exists, would leave a stale excuse sitting in the code."""
        import re
        from pathlib import Path

        from django.conf import settings

        from user.services.mobile_access import RESOURCE_TABS, UNGATED_SCREENS

        for key, reason in UNGATED_SCREENS.items():
            with self.subTest(screen=key):
                self.assertNotIn(key, RESOURCE_TABS,
                                 "mapped now — drop it from UNGATED_SCREENS")
                self.assertTrue(reason.strip(), "every exemption needs a reason")

        catalog = Path(settings.BASE_DIR) / "mobile" / "src" / "config" / "catalog.ts"
        if not catalog.exists():
            self.skipTest("mobile client not present")
        text = catalog.read_text(encoding="utf-8")
        for key in UNGATED_SCREENS:
            with self.subTest(screen=key):
                self.assertIn(f'"{key}"', text, "no such screen in the app")

    def test_the_report_list_matches_the_mobile_client(self):
        """Report tiles are the other copied fact; same drift guard."""
        import re
        from pathlib import Path

        from django.conf import settings

        from user.services.mobile_access import PHONE_REPORTS

        source = Path(settings.BASE_DIR) / "mobile" / "src" / "api" / "permissions.ts"
        if not source.exists():
            self.skipTest("mobile client not present")

        block = re.search(r"REPORT_TABS[^{]*\{(.*?)\n\};",
                          source.read_text(encoding="utf-8"), re.S)
        self.assertIsNotNone(block, "REPORT_TABS not found in the client")
        client = dict(re.findall(r'"?([\w-]+)"?:\s*"([^"]+)"', block.group(1)))
        self.assertEqual(client, dict(PHONE_REPORTS))

    def test_every_report_maps_to_a_real_web_tab(self):
        from user.access import ALL_TAB_CODES
        from user.services.mobile_access import PHONE_REPORTS

        for key, tab in PHONE_REPORTS:
            with self.subTest(report=key):
                self.assertIn(tab, ALL_TAB_CODES)

    def test_the_editor_groups_screens_into_registry_sections(self):
        """Same three tiers as the Web Access matrix — module, section, screen
        — so an administrator reads one tree, not two shapes."""
        from user.services.mobile_access import screen_tree, screens_by_module

        tree = {key: groups for key, _t, groups in screen_tree()}
        flat = {key: rows for key, _t, rows in screens_by_module()}

        for key, groups in tree.items():
            with self.subTest(module=key):
                # every screen appears exactly once, under one section
                placed = [s["tab"] for _label, rows in groups for s in rows]
                self.assertEqual(sorted(placed),
                                 sorted(s["tab"] for s in flat[key]))
                self.assertEqual(len(placed), len(set(placed)))

    def test_sections_carry_real_registry_labels(self):
        from user.services.mobile_access import screen_tree

        labels = {label for _k, _t, groups in screen_tree() for label, _r in groups}
        self.assertTrue(labels)
        # Master / Transactions / Reports are the registry's own tiers.
        self.assertTrue(labels & {"Master", "Transactions", "Reports"})

    def test_reports_land_in_their_own_section(self):
        from user.services.mobile_access import screen_tree

        for key, _title, groups in screen_tree():
            for label, rows in groups:
                for row in rows:
                    if row["kind"] == "report":
                        with self.subTest(module=key, tab=row["tab"]):
                            self.assertEqual(label, "Reports")

    def test_a_report_row_offers_view_only(self):
        """Add/Edit/Delete on a report would be three boxes deciding nothing."""
        from user.services.mobile_access import screens_by_module

        rows = [s for _k, _t, screens in screens_by_module() for s in screens]
        reports = [r for r in rows if r["kind"] == "report"]
        self.assertTrue(reports)
        for row in reports:
            with self.subTest(report=row["tab"]):
                self.assertEqual(row["actions"], ["view"])

    def test_every_screen_lands_in_exactly_one_module(self):
        from user.services.mobile_access import (PHONE_REPORTS, PHONE_SCREENS,
                                                 screens_by_module)

        placed = [s["tab"] for _k, _t, screens in screens_by_module() for s in screens]
        self.assertEqual(len(placed), len(set(placed)))
        self.assertEqual(set(placed),
                         {tab for _k, tab in PHONE_SCREENS + PHONE_REPORTS})

    def test_only_the_four_enforceable_actions_are_offered(self):
        """print/save/update/favorite are already listed as ticks nothing
        reads. Offering them here would rebuild that problem."""
        from user.access import UNENFORCED_ACTIONS
        from user.services.mobile_access import MOBILE_ACTIONS

        self.assertEqual(MOBILE_ACTIONS, ["view", "add", "edit", "delete"])
        self.assertFalse(set(MOBILE_ACTIONS) & set(UNENFORCED_ACTIONS))


class MobileScreenMatrixTests(TestCase):
    """The screen × action matrix — the finer half of Mobile Access."""

    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.admin = User.objects.create_superuser("ms_admin", "s@x.com", "Str0ngPass!")
        self.member = User.objects.create_user("ms_member", "sm@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Screen Staff")
        self.member.groups.add(self.group)
        # Full web rights on two broiler screens, so the web matrix is never
        # what is being measured.
        for tab in ("daily_entry_list", "bird_sale_list"):
            GroupTabPermission.objects.create(
                group=self.group, tab_code=tab, can_view=True, can_add=True,
                can_edit=True, can_delete=True)

    def user(self):
        return get_user_model().objects.get(pk=self.member.pk)

    def configure(self, tab, **actions):
        from user.models import GroupMobileTabPermission

        GroupMobileTabPermission.objects.update_or_create(
            group=self.group, tab_code=tab,
            defaults={f"can_{a}": v for a, v in actions.items()})

    def can(self, tab, action):
        from user.services.mobile_access import mobile_can

        return mobile_can(self.user(), tab, action)

    def test_unconfigured_keeps_everything_the_web_matrix_allows(self):
        for action in ("view", "add", "edit", "delete"):
            with self.subTest(action=action):
                self.assertTrue(self.can("daily_entry_list", action))

    def test_an_unticked_action_is_refused(self):
        self.configure("daily_entry_list", view=True, add=True, edit=False, delete=False)
        self.configure("bird_sale_list", view=True, add=True, edit=True, delete=True)
        self.assertTrue(self.can("daily_entry_list", "add"))
        self.assertFalse(self.can("daily_entry_list", "edit"))
        self.assertFalse(self.can("daily_entry_list", "delete"))

    def test_one_screen_does_not_speak_for_another(self):
        """The whole reason for the per-screen matrix."""
        self.configure("daily_entry_list", view=True, add=True, edit=True, delete=True)
        self.configure("bird_sale_list", view=True, add=False, edit=False, delete=False)
        self.assertTrue(self.can("daily_entry_list", "edit"))
        self.assertFalse(self.can("bird_sale_list", "edit"))

    def test_it_can_never_grant_what_the_web_matrix_withholds(self):
        GroupTabPermission.objects.filter(
            group=self.group, tab_code="bird_sale_list").update(can_delete=False)
        self.configure("bird_sale_list", view=True, add=True, edit=True, delete=True)
        # mobile_can is the phone gate; the web gate is checked by the caller,
        # so assert through the API permission class that combines both.
        from user.access import user_can

        self.assertFalse(user_can(self.user(), "bird_sale_list", "delete"))

    def test_a_screen_outside_the_registry_is_not_governed(self):
        """Tracking has no phone screen; refusing it would deny a request this
        page never claimed to decide."""
        self.configure("daily_entry_list", view=True)
        self.assertTrue(self.can("tracking_dashboard", "view"))

    def test_an_action_outside_the_four_passes_through(self):
        self.configure("daily_entry_list", view=True, add=False, edit=False, delete=False)
        self.assertTrue(self.can("daily_entry_list", "print"))

    def test_a_superuser_bypasses_the_screen_matrix(self):
        self.configure("daily_entry_list", view=True, add=False, edit=False, delete=False)
        from user.services.mobile_access import mobile_can

        self.assertTrue(mobile_can(self.admin, "daily_entry_list", "edit"))

    def test_the_endpoint_reports_the_screen_actions(self):
        self.configure("daily_entry_list", view=True, add=True, edit=False, delete=False)
        self.configure("bird_sale_list", view=True, add=False, edit=False, delete=False)
        self.client.force_login(self.member)
        data = self.client.get(PERMISSIONS_URL).json()["data"]
        self.assertTrue(data["tab_actions"]["daily_entry_list"]["add"])
        self.assertFalse(data["tab_actions"]["daily_entry_list"]["edit"])
        self.assertFalse(data["tab_actions"]["bird_sale_list"]["add"])

    def test_a_screen_with_view_off_leaves_the_tab_list(self):
        """The hub filters tiles on `tabs`, so a hidden screen has to leave it
        or its tile survives the switch."""
        self.configure("daily_entry_list", view=False, add=False, edit=False, delete=False)
        self.configure("bird_sale_list", view=True, add=True, edit=True, delete=True)
        self.client.force_login(self.member)
        data = self.client.get(PERMISSIONS_URL).json()["data"]
        self.assertNotIn("daily_entry_list", data["tabs"])
        self.assertIn("bird_sale_list", data["tabs"])

    def test_the_editor_renders_a_box_per_screen_and_action(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse("mobile_access_form"),
                               {"group": self.group.id}).content.decode()
        for action in ("view", "add", "edit", "delete"):
            self.assertIn(f'name="p_daily_entry_list_{action}"', html)

    def test_a_screen_the_web_matrix_withholds_is_disabled_in_the_editor(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse("mobile_access_form"),
                               {"group": self.group.id}).content.decode()
        # customer is not granted to this group at all.
        self.assertIn("No web permission", html)

    def test_saving_the_matrix_stores_one_row_per_screen(self):
        from user.models import GroupMobileTabPermission
        from user.services.mobile_access import GOVERNED_TABS

        self.client.force_login(self.admin)
        data = {"group": self.group.id, "p_daily_entry_list_view": "on",
                "p_daily_entry_list_add": "on"}
        response = self.client.post(reverse("mobile_access_form"), data)
        self.assertEqual(response.status_code, 302)

        rows = {r.tab_code: r for r in
                GroupMobileTabPermission.objects.filter(group=self.group)}
        self.assertEqual(len(rows), len(GOVERNED_TABS))
        self.assertTrue(rows["daily_entry_list"].can_add)
        self.assertFalse(rows["daily_entry_list"].can_edit)
        self.assertFalse(rows["bird_sale_list"].can_view)


class MobileReportAccessTests(TestCase):
    """Report tiles are on the phone, so they belong in the matrix.

    They rendered unconditionally at first — anyone who could open a module saw
    every report in it — and then were gated but not configurable, which is the
    gap this covers.
    """

    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.admin = User.objects.create_superuser("mr_admin", "r2@x.com", "Str0ngPass!")
        self.member = User.objects.create_user("mr_member", "rm@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Report Staff")
        self.member.groups.add(self.group)
        for tab in ("live_flock_summary_report", "day_record_report",
                    "daily_entry_list"):
            GroupTabPermission.objects.create(
                group=self.group, tab_code=tab, can_view=True, can_add=True,
                can_edit=True, can_delete=True)

    def user(self):
        return get_user_model().objects.get(pk=self.member.pk)

    def configure(self, tab, view):
        from user.models import GroupMobileTabPermission

        GroupMobileTabPermission.objects.update_or_create(
            group=self.group, tab_code=tab,
            defaults={"can_view": view, "can_add": False,
                      "can_edit": False, "can_delete": False})

    def test_a_report_the_group_can_open_gets_a_row(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse("mobile_access_form"),
                               {"group": self.group.id}).content.decode()
        self.assertIn('name="p_live_flock_summary_report_view"', html)
        # ...and no add/edit/delete boxes for it
        self.assertNotIn('name="p_live_flock_summary_report_add"', html)

    def test_switching_a_report_off_removes_it_from_the_tab_list(self):
        """The hub filters report tiles on `tabs`, so that is what has to move."""
        self.configure("live_flock_summary_report", False)
        self.configure("day_record_report", True)
        self.client.force_login(self.member)
        data = self.client.get(PERMISSIONS_URL).json()["data"]
        self.assertNotIn("live_flock_summary_report", data["tabs"])
        self.assertIn("day_record_report", data["tabs"])

    def test_reports_report_view_only_actions(self):
        self.configure("live_flock_summary_report", True)
        self.client.force_login(self.member)
        actions = self.client.get(PERMISSIONS_URL).json()["data"]["tab_actions"]
        self.assertTrue(actions["live_flock_summary_report"]["view"])
        self.assertFalse(actions["live_flock_summary_report"]["add"])

    def test_a_reports_non_view_action_is_not_governed(self):
        """There is no add/edit/delete behind a report, so refusing one would
        be inventing a decision."""
        from user.services.mobile_access import mobile_can

        self.configure("live_flock_summary_report", False)
        self.assertFalse(mobile_can(self.user(), "live_flock_summary_report", "view"))
        self.assertTrue(mobile_can(self.user(), "live_flock_summary_report", "add"))

    def test_saving_stores_a_row_per_report(self):
        from user.models import GroupMobileTabPermission

        self.client.force_login(self.admin)
        self.client.post(reverse("mobile_access_form"),
                         {"group": self.group.id,
                          "p_live_flock_summary_report_view": "on"})
        rows = {r.tab_code: r for r in
                GroupMobileTabPermission.objects.filter(group=self.group)}
        self.assertTrue(rows["live_flock_summary_report"].can_view)
        self.assertFalse(rows["live_flock_summary_report"].can_add)
        self.assertFalse(rows["day_record_report"].can_view)


class UnbuiltScreenTests(TestCase):
    """Web tabs the app has no screen for are named, not silently dropped.

    Leaving them out was right for checkboxes and wrong for explanation: an
    administrator who granted a tab on the web had no way to tell "not built
    yet" from "the page is broken".
    """

    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.admin = User.objects.create_superuser("ub_admin", "u2@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Unbuilt Group")
        # Two attendance tabs the phone has no screen for, plus one it does.
        for tab in ("daily_attendance", "mark_attendance", "leave_employee"):
            GroupTabPermission.objects.create(group=self.group, tab_code=tab,
                                              can_view=True)
        self.client.force_login(self.admin)

    def html(self):
        return self.client.get(reverse("mobile_access_form"),
                               {"group": self.group.id}).content.decode()

    def test_an_unbuilt_tab_never_appears_in_governed(self):
        from user.services.mobile_access import GOVERNED_TABS, unbuilt_by_module

        for _key, rows in unbuilt_by_module().items():
            for row in rows:
                with self.subTest(tab=row["tab"]):
                    self.assertNotIn(row["tab"], GOVERNED_TABS)

    def test_the_page_names_the_unbuilt_screens(self):
        html = self.html()
        self.assertIn("not built in the app yet", html)
        self.assertIn("Daily Attendance", html)
        self.assertIn("Mark Attendance", html)

    def test_it_renders_no_checkbox_for_them(self):
        """The whole reason they were left out — a box that decides nothing."""
        html = self.html()
        for tab in ("daily_attendance", "mark_attendance"):
            for action in ("view", "add", "edit", "delete"):
                with self.subTest(tab=tab, action=action):
                    self.assertNotIn(f'name="p_{tab}_{action}"', html)

    def test_a_tab_the_group_holds_is_marked(self):
        """'I granted this and it is not here' is the question these answer."""
        self.assertIn("granted on web", self.html())

    def test_a_group_without_the_tab_gets_no_marker(self):
        other = Group.objects.create(name="No Attendance")
        GroupTabPermission.objects.create(group=other, tab_code="leave_employee",
                                          can_view=True)
        html = self.client.get(reverse("mobile_access_form"),
                               {"group": other.id}).content.decode()
        self.assertIn("not built in the app yet", html)
        self.assertNotIn("granted on web", html)

    def test_every_web_tab_is_either_governed_or_listed_as_unbuilt(self):
        """No tab of a phone module may fall between the two lists — that gap
        is what made Inventory invisible for a day."""
        from user.access import NAV_GROUPS
        from user.services.mobile_access import (GOVERNED_TABS, MOBILE_MODULES,
                                                 unbuilt_by_module)

        unbuilt = unbuilt_by_module()
        for key, _title, nav, _icon, _colour in MOBILE_MODULES:
            listed = {r["tab"] for r in unbuilt[key]}
            for tab in NAV_GROUPS.get(nav, set()):
                with self.subTest(tab=tab):
                    self.assertTrue(tab in GOVERNED_TABS or tab in listed)


class MobileOrderTests(TestCase):
    """The sort column was stored and never read. It is read now."""

    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.member = User.objects.create_user("mo_member", "o@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Order Staff")
        self.member.groups.add(self.group)
        from user.access import NAV_GROUPS

        for nav in ("broiler", "sales", "hatchery"):
            for tab in sorted(NAV_GROUPS[nav])[:1]:
                GroupTabPermission.objects.create(group=self.group, tab_code=tab,
                                                  can_view=True)

    def user(self):
        return get_user_model().objects.get(pk=self.member.pk)

    def test_registry_order_when_nothing_is_configured(self):
        from user.services.mobile_access import module_order

        order = module_order(self.user())
        self.assertEqual(order, [k for k in ALL_KEYS if k in order])

    def test_the_saved_position_sets_the_order(self):
        from user.services.mobile_access import module_order

        for position, key in enumerate(["sales", "hatchery", "broiler"]):
            GroupMobileAccess.objects.create(group=self.group, module_key=key,
                                             enabled=True, position=position)
        self.assertEqual(module_order(self.user()), ["sales", "hatchery", "broiler"])

    def test_modules_sharing_a_position_keep_registry_order(self):
        from user.services.mobile_access import module_order

        for key in ("sales", "hatchery", "broiler"):
            GroupMobileAccess.objects.create(group=self.group, module_key=key,
                                             enabled=True, position=0)
        order = module_order(self.user())
        self.assertEqual(order, [k for k in ALL_KEYS if k in order])

    def test_the_endpoint_ships_the_order(self):
        for position, key in enumerate(["sales", "hatchery", "broiler"]):
            GroupMobileAccess.objects.create(group=self.group, module_key=key,
                                             enabled=True, position=position)
        self.client.force_login(self.member)
        data = self.client.get(PERMISSIONS_URL).json()["data"]
        self.assertEqual(data["nav_order"], ["sales", "hatchery", "broiler"])
        # and it is not merely the alphabetical list under another name
        self.assertNotEqual(data["nav_order"], sorted(data["nav_order"]))


class AccessChangeLogTests(TestCase):
    """Every save is recorded, so "who changed this?" has an answer."""

    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.admin = User.objects.create_superuser("al_admin", "l@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Logged Group")
        GroupTabPermission.objects.create(group=self.group, tab_code="daily_entry_list",
                                          can_view=True, can_add=True, can_edit=True)
        self.client.force_login(self.admin)

    def entries(self):
        from user.models import AccessChangeLog

        return list(AccessChangeLog.objects.filter(group=self.group))

    def test_saving_the_matrix_writes_one_entry(self):
        self.client.post(reverse("mobile_access_form"),
                         {"group": self.group.id, "p_daily_entry_list_view": "on"})
        rows = self.entries()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].surface, "mobile")
        self.assertEqual(rows[0].changed_by, "al_admin")

    def test_the_entry_names_what_moved(self):
        self.client.post(reverse("mobile_access_form"),
                         {"group": self.group.id,
                          "p_daily_entry_list_view": "on",
                          "p_daily_entry_list_add": "on"})
        # Second save turns Add off again.
        self.client.post(reverse("mobile_access_form"),
                         {"group": self.group.id, "p_daily_entry_list_view": "on"})
        latest = self.entries()[0]
        # "changes" rather than "screens": all three surfaces share one shape
        # now, so entries from every surface share one shape.
        self.assertIn("daily_entry_list", latest.detail["changes"])
        self.assertEqual(latest.detail["changes"]["daily_entry_list"]["add"],
                         [True, False])
        self.assertIn("Daily Entry", latest.summary)

    def test_a_save_that_changes_nothing_says_so(self):
        for _ in range(2):
            self.client.post(reverse("mobile_access_form"),
                             {"group": self.group.id, "p_daily_entry_list_view": "on"})
        self.assertEqual(self.entries()[0].summary.split(";")[0], "No change")

    def test_logging_never_breaks_the_save(self):
        """An access page that 500s because its audit trail failed is worse
        than one with a gap in the trail."""
        from unittest.mock import patch

        with patch("user.models.AccessChangeLog.objects.create",
                   side_effect=RuntimeError("boom")):
            response = self.client.post(
                reverse("mobile_access_form"),
                {"group": self.group.id, "p_daily_entry_list_view": "on"})
        self.assertEqual(response.status_code, 302)
