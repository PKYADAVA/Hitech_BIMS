"""User > Dashboard Access — per-group widget visibility and order.

The rule that matters: this can only take a widget away. It sits on top of the
tab gate, so it must never reveal a card for a report the group cannot open.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils.html import escape

from user.models import GroupDashboardWidget, GroupTabPermission
from user.services.dashboard_widgets import (WIDGETS, all_panels,
                                             dashboard_widgets)

ALL_KEYS = [w[0] for w in WIDGETS]           # the data cards
ALL_PANEL_KEYS = [p[0] for p in all_panels()]  # plus Quick Actions / Field Team


class DashboardAccessTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.admin = User.objects.create_superuser("da_admin", "a@x.com", "Str0ngPass!")
        self.member = User.objects.create_user("da_member", "m@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Farm Managers")
        self.member.groups.add(self.group)
        # Every widget's tab, so the tab gate is never what is being measured.
        for _key, _t, tabs, _u, _i, _c, _b in WIDGETS:
            for tab in tabs:
                GroupTabPermission.objects.get_or_create(
                    group=self.group, tab_code=tab, defaults={"can_view": True})

    def keys(self, user):
        return [w["key"] for w in dashboard_widgets(user, use_cache=False)]

    def user(self):
        return get_user_model().objects.get(pk=self.member.pk)

    # ---- defaults ---------------------------------------------------------

    def test_an_unconfigured_group_sees_everything_its_tabs_allow(self):
        """Nothing saved yet must behave exactly as before this feature."""
        self.assertEqual(self.keys(self.user()), ALL_KEYS)

    def test_a_superuser_is_unaffected_by_group_rows(self):
        GroupDashboardWidget.objects.create(group=self.group, widget_key="live_flock",
                                            enabled=False)
        self.assertEqual(self.keys(self.admin), ALL_KEYS)

    # ---- switching widgets off -------------------------------------------

    def configure(self, **enabled_by_key):
        GroupDashboardWidget.objects.filter(group=self.group).delete()
        for index, key in enumerate(ALL_KEYS):
            GroupDashboardWidget.objects.create(
                group=self.group, widget_key=key,
                enabled=enabled_by_key.get(key, True), position=index)

    def test_a_disabled_widget_disappears(self):
        self.configure(receivables=False)
        keys = self.keys(self.user())
        self.assertNotIn("receivables", keys)
        self.assertIn("live_flock", keys)

    def test_disabling_everything_leaves_an_empty_dashboard(self):
        self.configure(**{k: False for k in ALL_KEYS})
        self.assertEqual(self.keys(self.user()), [])

    def test_it_can_never_grant_a_widget_the_matrix_withholds(self):
        """Enabled here, but the group cannot open the report it links to."""
        GroupTabPermission.objects.filter(
            group=self.group, tab_code="negative_stock_report").delete()
        self.configure()
        self.assertNotIn("stock_alerts", self.keys(self.user()))

    # ---- ordering ---------------------------------------------------------

    def test_position_sets_the_order(self):
        GroupDashboardWidget.objects.filter(group=self.group).delete()
        for position, key in enumerate(reversed(ALL_KEYS)):
            GroupDashboardWidget.objects.create(group=self.group, widget_key=key,
                                                enabled=True, position=position)
        self.assertEqual(self.keys(self.user()), list(reversed(ALL_KEYS)))

    def test_widgets_sharing_a_position_keep_registry_order(self):
        GroupDashboardWidget.objects.filter(group=self.group).delete()
        for key in ALL_KEYS:
            GroupDashboardWidget.objects.create(group=self.group, widget_key=key,
                                                enabled=True, position=0)
        self.assertEqual(self.keys(self.user()), ALL_KEYS)

    # ---- several groups ---------------------------------------------------

    def test_enabled_in_any_group_wins_at_the_earliest_position(self):
        """Matches how the tab matrix combines groups — a permission granted
        anywhere is granted."""
        self.configure(live_flock=False)
        other = Group.objects.create(name="Also Managers")
        self.member.groups.add(other)
        GroupDashboardWidget.objects.create(group=other, widget_key="live_flock",
                                            enabled=True, position=0)
        keys = self.keys(self.user())
        self.assertEqual(keys[0], "live_flock")

    # ---- the editor -------------------------------------------------------

    def test_the_page_lists_every_widget(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse("dashboard_access_form"),
                               {"group": self.group.id}).content.decode()
        for key, title, *_ in all_panels():
            self.assertIn(f'name="on_{key}"', html)
            self.assertIn(f'name="pos_{key}"', html)
            self.assertIn(escape(title), html)   # "Receivables &amp; Payables"

    def test_the_form_says_when_a_group_is_unconfigured(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse("dashboard_access_form"),
                               {"group": self.group.id}).content.decode()
        self.assertIn("Nothing is saved", html)

    def test_the_list_shows_only_configured_groups(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse("dashboard_access")).content.decode()
        self.assertIn("No group has been configured yet", html)

        self.configure(receivables=False)
        html = self.client.get(reverse("dashboard_access")).content.decode()
        self.assertIn("Farm Managers", html)
        self.assertIn(f'?group={self.group.id}', html)      # edit link
        self.assertIn(reverse("dashboard_access_delete", args=[self.group.id]), html)

    def test_clearing_a_group_returns_it_to_the_default(self):
        self.configure(receivables=False)
        self.assertNotIn("receivables", self.keys(self.user()))

        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("dashboard_access_delete", args=[self.group.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            GroupDashboardWidget.objects.filter(group=self.group).exists())
        self.assertEqual(self.keys(self.user()), ALL_KEYS)

    def test_saving_stores_the_switches_and_positions(self):
        self.client.force_login(self.admin)
        data = {"group": self.group.id}
        for index, key in enumerate(ALL_KEYS):
            data[f"pos_{key}"] = len(ALL_KEYS) - index
            if key != "receivables":
                data[f"on_{key}"] = "on"
        response = self.client.post(reverse("dashboard_access_form"), data)
        self.assertEqual(response.status_code, 302)

        rows = {r.widget_key: r for r in
                GroupDashboardWidget.objects.filter(group=self.group)}
        self.assertEqual(len(rows), len(ALL_PANEL_KEYS))
        self.assertFalse(rows["receivables"].enabled)
        self.assertTrue(rows["live_flock"].enabled)
        self.assertEqual(rows[ALL_KEYS[0]].position, len(ALL_KEYS))
        # and it takes effect
        self.assertNotIn("receivables", self.keys(self.user()))

    def test_saving_replaces_rather_than_accumulates(self):
        self.client.force_login(self.admin)
        for _ in range(2):
            self.client.post(reverse("dashboard_access_form"),
                             {"group": self.group.id,
                              **{f"on_{k}": "on" for k in ALL_PANEL_KEYS}})
        self.assertEqual(
            GroupDashboardWidget.objects.filter(group=self.group).count(),
            len(ALL_PANEL_KEYS))

    def test_the_tab_is_registered_and_reachable(self):
        from user.access import ALL_TAB_CODES

        self.assertIn("dashboard_access", ALL_TAB_CODES)
        self.assertEqual(reverse("dashboard_access"), "/dashboard-access/")

    def test_the_nav_link_is_permission_gated(self):
        """Same rule as every other tab: no view right, no link. The link lives
        in the User Management subnav, not on the dashboard."""
        from user.access import allowed_view_tabs

        self.assertNotIn("dashboard_access", allowed_view_tabs(self.user()))
        GroupTabPermission.objects.create(group=self.group,
                                          tab_code="dashboard_access", can_view=True)
        self.assertIn("dashboard_access", allowed_view_tabs(self.user()))

        self.client.force_login(self.admin)
        html = self.client.get(reverse("dashboard_access")).content.decode()
        self.assertIn(reverse("dashboard_access_form"), html)


class DashboardPanelTests(TestCase):
    """Quick Actions and Field Team are rendered server-side, so they are
    switched and ordered through the same page as the data cards."""

    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.member = User.objects.create_user("dp_member", "p@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Field Supervisors")
        self.member.groups.add(self.group)
        for key, _t, tabs, *_ in all_panels():
            for tab in tabs:
                GroupTabPermission.objects.get_or_create(
                    group=self.group, tab_code=tab, defaults={"can_view": True})

    def user(self):
        return get_user_model().objects.get(pk=self.member.pk)

    def panels(self):
        from user.services.dashboard_widgets import dashboard_panels
        return dashboard_panels(self.user())

    def test_field_team_is_a_switchable_panel(self):
        self.assertIn("field_team", ALL_PANEL_KEYS)
        self.assertIn("quick_actions", ALL_PANEL_KEYS)

    def test_an_unconfigured_group_gets_every_panel(self):
        self.assertEqual(set(self.panels()), set(ALL_PANEL_KEYS))

    def test_switching_field_team_off_hides_it(self):
        for key in ALL_PANEL_KEYS:
            GroupDashboardWidget.objects.create(
                group=self.group, widget_key=key,
                enabled=key != "field_team", position=0)
        self.assertNotIn("field_team", self.panels())
        self.assertIn("quick_actions", self.panels())

    def test_the_tracking_tab_alone_no_longer_shows_field_team(self):
        """Before this, the block keyed straight off the tracking tab. Now the
        group can hold that tab and still not want the panel."""
        for key in ALL_PANEL_KEYS:
            GroupDashboardWidget.objects.create(
                group=self.group, widget_key=key,
                enabled=key != "field_team", position=0)
        self.client.force_login(self.member)
        html = self.client.get(reverse("dashboard")).content.decode()
        self.assertNotIn('id="home-trk-map"', html)

    def test_a_panel_still_needs_its_tab(self):
        GroupTabPermission.objects.filter(
            group=self.group, tab_code="tracking_dashboard").delete()
        self.assertNotIn("field_team", self.panels())

    def test_the_dashboard_orders_the_blocks_by_position(self):
        for key in ALL_PANEL_KEYS:
            GroupDashboardWidget.objects.create(
                group=self.group, widget_key=key, enabled=True,
                position=0 if key == "field_team" else 5)
        self.client.force_login(self.member)
        html = self.client.get(reverse("dashboard")).content.decode()
        self.assertIn("order:0;", html)          # field team hoisted to the top
        self.assertIn('class="dash-panels"', html)


class DashboardAccessPreviewTests(TestCase):
    """The Preview action answers for the group, not for whoever clicks it."""

    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.admin = User.objects.create_superuser("pv_admin", "v@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Preview Group")
        self.client.force_login(self.admin)

    def preview(self):
        response = self.client.get(
            reverse("dashboard_access_preview", args=[self.group.id]))
        self.assertEqual(response.status_code, 200)
        return {p["key"]: p for p in response.json()["panels"]}

    def test_a_panel_the_group_cannot_reach_is_marked_not_permitted(self):
        # One row elsewhere, so the group counts as configured — with no rows
        # at all it would be unconfigured, which means unrestricted.
        GroupTabPermission.objects.create(group=self.group, tab_code="items",
                                          can_view=True)
        panels = self.preview()
        self.assertFalse(panels["live_flock"]["permitted"])
        self.assertFalse(panels["live_flock"]["shown"])

    def test_a_permitted_and_enabled_panel_is_shown(self):
        GroupTabPermission.objects.create(group=self.group, can_view=True,
                                          tab_code="live_flock_summary_report")
        GroupDashboardWidget.objects.create(group=self.group, widget_key="live_flock",
                                            enabled=True, position=0)
        self.assertTrue(self.preview()["live_flock"]["shown"])

    def test_switched_off_is_distinguished_from_not_permitted(self):
        """The modal says which gate failed, so the two must not collapse."""
        GroupTabPermission.objects.create(group=self.group, can_view=True,
                                          tab_code="live_flock_summary_report")
        GroupDashboardWidget.objects.create(group=self.group, widget_key="live_flock",
                                            enabled=False, position=0)
        panel = self.preview()["live_flock"]
        self.assertTrue(panel["permitted"])
        self.assertFalse(panel["switched_on"])
        self.assertFalse(panel["shown"])

    def test_the_preview_follows_the_saved_order(self):
        for tab in ("live_flock_summary_report", "negative_stock_report"):
            GroupTabPermission.objects.create(group=self.group, tab_code=tab,
                                              can_view=True)
        GroupDashboardWidget.objects.create(group=self.group, widget_key="stock_alerts",
                                            enabled=True, position=0)
        GroupDashboardWidget.objects.create(group=self.group, widget_key="live_flock",
                                            enabled=True, position=1)
        response = self.client.get(
            reverse("dashboard_access_preview", args=[self.group.id]))
        keys = [p["key"] for p in response.json()["panels"]]
        self.assertLess(keys.index("stock_alerts"), keys.index("live_flock"))

    def test_both_pages_carry_the_preview_modal(self):
        GroupDashboardWidget.objects.create(group=self.group, widget_key="live_flock",
                                            enabled=True, position=0)
        for url in (reverse("dashboard_access"),
                    reverse("dashboard_access_form") + f"?group={self.group.id}"):
            with self.subTest(url=url):
                html = self.client.get(url).content.decode()
                self.assertIn('id="da-preview"', html)
                # The list passes the group alone (saved state); the form adds
                # its live switches.
                self.assertIn(f"dashboardAccessPreview({self.group.id}", html)


class DashboardPreviewRenderTests(TestCase):
    """The preview renders the real dashboard page as the group would get it."""

    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.admin = User.objects.create_superuser("pr_admin", "r@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Preview Render")
        GroupTabPermission.objects.create(group=self.group, can_view=True,
                                          tab_code="live_flock_summary_report")
        GroupDashboardWidget.objects.create(group=self.group, widget_key="live_flock",
                                            enabled=True, position=0)

    def preview(self, **extra):
        self.client.force_login(self.admin)
        return self.client.get(reverse("dashboard"),
                               {"preview_group": self.group.id, **extra})

    def test_the_frame_is_allowed_from_the_same_origin(self):
        """X_FRAME_OPTIONS is DENY site-wide, which would blank the iframe."""
        self.assertEqual(self.preview()["X-Frame-Options"], "SAMEORIGIN")

    def test_preview_mode_drops_the_navbar(self):
        html = self.preview(preview="1").content.decode()
        # navClock is in the welcome banner, not the navbar — pick a marker that
        # only the top navbar carries.
        self.assertNotIn("Change Requests", html)
        self.assertIn("Change Requests", self.client.get(
            reverse("dashboard")).content.decode())
        self.assertIn("Preview of what", html)

    def test_the_preview_shows_the_group_panels_not_the_viewers(self):
        """The admin sees every panel; this group has one."""
        html = self.preview(preview="1").content.decode()
        self.assertNotIn('class="qa-card"', html)      # quick actions withheld
        self.assertIn('id="dash-widgets"', html)

    def test_the_widgets_api_answers_for_the_previewed_group(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard_widgets_api"),
                                   {"preview_group": self.group.id})
        self.assertEqual([w["key"] for w in response.json()["widgets"]],
                         ["live_flock"])

    def test_a_user_without_dashboard_access_cannot_preview_a_group(self):
        """Otherwise preview would be a way around the matrix."""
        User = get_user_model()
        outsider = User.objects.create_user("pr_out", "o@x.com", "Str0ngPass!")
        plain = Group.objects.create(name="Plain")
        outsider.groups.add(plain)
        GroupTabPermission.objects.create(group=plain, tab_code="items", can_view=True)

        self.client.force_login(outsider)
        response = self.client.get(reverse("dashboard_widgets_api"),
                                   {"preview_group": self.group.id})
        # falls back to their own (empty) dashboard rather than the group's
        self.assertEqual(response.json()["widgets"], [])


class UnsavedPreviewTests(TestCase):
    """The editor's Preview shows the form, not the database.

    Previewing the saved state while mid-edit is worse than no preview: it
    quietly answers a different question from the one being asked.
    """

    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.admin = User.objects.create_superuser("up_admin", "u@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Unsaved Group")
        for tab in ("live_flock_summary_report", "negative_stock_report"):
            GroupTabPermission.objects.create(group=self.group, tab_code=tab,
                                              can_view=True)
        # Saved: only Live Flock.
        GroupDashboardWidget.objects.create(group=self.group, widget_key="live_flock",
                                            enabled=True, position=0)
        GroupDashboardWidget.objects.create(group=self.group, widget_key="stock_alerts",
                                            enabled=False, position=1)
        self.client.force_login(self.admin)

    def widgets(self, **params):
        response = self.client.get(reverse("dashboard_widgets_api"),
                                   {"preview_group": self.group.id, **params})
        return [w["key"] for w in response.json()["widgets"]]

    def test_without_an_override_the_saved_state_is_used(self):
        self.assertEqual(self.widgets(), ["live_flock"])

    def test_an_override_wins_over_the_saved_rows(self):
        self.assertEqual(self.widgets(panels="stock_alerts:0"), ["stock_alerts"])

    def test_the_override_carries_the_order(self):
        self.assertEqual(self.widgets(panels="stock_alerts:0,live_flock:1"),
                         ["stock_alerts", "live_flock"])

    def test_an_empty_override_means_nothing_enabled(self):
        """Not 'unconfigured' — the editor with every switch off must preview
        as an empty dashboard, not as a full one."""
        self.assertEqual(self.widgets(panels=""), [])

    def test_the_override_still_cannot_beat_the_tab_matrix(self):
        self.assertEqual(self.widgets(panels="receivables:0"), [])

    def test_rubbish_in_the_override_is_ignored(self):
        self.assertEqual(self.widgets(panels="not_a_widget:0,live_flock:x"),
                         ["live_flock"])

    def test_the_override_needs_the_dashboard_access_right(self):
        User = get_user_model()
        outsider = User.objects.create_user("up_out", "x@x.com", "Str0ngPass!")
        plain = Group.objects.create(name="Plain Group")
        outsider.groups.add(plain)
        GroupTabPermission.objects.create(group=plain, tab_code="items", can_view=True)
        self.client.force_login(outsider)
        self.assertEqual(self.widgets(panels="stock_alerts:0"), [])

    def test_the_form_button_sends_its_live_state(self):
        html = self.client.get(reverse("dashboard_access_form"),
                               {"group": self.group.id}).content.decode()
        self.assertIn('id="da-preview-btn"', html)
        self.assertIn("dashboardAccessPreview({}, live)".format(self.group.id), html)

    def test_the_list_button_sends_no_override(self):
        """From the list there is nothing unsaved, so it must show the saved
        state — no panels argument at all."""
        html = self.client.get(reverse("dashboard_access")).content.decode()
        self.assertIn(f"dashboardAccessPreview({self.group.id})", html)

    def test_the_preview_page_passes_the_override_to_the_widget_fetch(self):
        """The four data cards are fetched by JS, so the override has to reach
        that request too. Without this the cards showed the saved state while
        the server-rendered panels showed the live one."""
        html = self.client.get(reverse("dashboard"),
                               {"preview": "1", "preview_group": self.group.id,
                                "panels": "stock_alerts:0"}).content.decode()
        self.assertIn("params.set('panels', 'stock_alerts:0')", html)

    def test_no_panels_param_when_there_is_no_override(self):
        html = self.client.get(reverse("dashboard"),
                               {"preview": "1",
                                "preview_group": self.group.id}).content.decode()
        self.assertNotIn("params.set('panels'", html)

    def test_every_toggled_on_widget_reaches_the_preview(self):
        keys = self.widgets(panels="stock_alerts:0,live_flock:1")
        self.assertEqual(keys, ["stock_alerts", "live_flock"])


class GroupTabResolutionTests(TestCase):
    """group_viewable_tabs must reproduce every rule allowed_view_tabs uses.

    It originally read only the permission rows, so the preview withheld panels
    the group really would get: six switched on, three shown.
    """

    def setUp(self):
        cache.clear()
        from django.contrib.auth.models import User as AuthUser

        self.admin = AuthUser.objects.create_superuser("gt_admin", "g@x.com",
                                                       "Str0ngPass!")
        self.group = Group.objects.create(name="Resolution Group")
        for key, *_ in all_panels():
            GroupDashboardWidget.objects.create(group=self.group, widget_key=key,
                                                enabled=True, position=0)

    def tabs(self):
        from user.services.dashboard_widgets import group_viewable_tabs
        return group_viewable_tabs(self.group)

    def shown(self):
        from user.services.dashboard_widgets import panels_for_group
        return [p["key"] for p in panels_for_group(self.group) if p["shown"]]

    def test_an_unconfigured_group_counts_as_unrestricted(self):
        """user_can treats a user with no matrix rows as unrestricted, so the
        preview has to as well or it shows a stricter dashboard than reality."""
        from user.access import ALL_TAB_CODES

        self.assertEqual(self.tabs(), set(ALL_TAB_CODES))
        self.assertEqual(self.shown(), ALL_PANEL_KEYS)

    def test_an_admin_access_type_bypasses_the_matrix(self):
        from user.access import ALL_TAB_CODES
        from user.models import GroupAccessProfile

        GroupTabPermission.objects.create(group=self.group, tab_code="items",
                                          can_view=True)
        self.assertEqual(self.tabs(), {"items"})       # sub-admin: just that one

        GroupAccessProfile.objects.create(group=self.group, access_type="admin")
        self.assertEqual(self.tabs(), set(ALL_TAB_CODES))

    def test_a_configured_group_is_held_to_its_rows(self):
        """Alerts rides along: it declares no tabs, so the matrix cannot
        withhold it. Every other panel is held to the group's single row."""
        GroupTabPermission.objects.create(
            group=self.group, tab_code="live_flock_summary_report", can_view=True)
        self.assertEqual(self.tabs(), {"live_flock_summary_report"})
        self.assertEqual(self.shown(), ["alerts_widget", "live_flock"])

    def test_the_preview_names_what_it_withholds(self):
        from user.services.dashboard_widgets import withheld_panels

        GroupTabPermission.objects.create(
            group=self.group, tab_code="live_flock_summary_report", can_view=True)
        withheld = withheld_panels(self.group)
        self.assertNotIn("Live Flock", withheld)
        self.assertIn("Stock Alerts", withheld)

        self.client.force_login(self.admin)
        html = self.client.get(reverse("dashboard"),
                               {"preview": "1",
                                "preview_group": self.group.id}).content.decode()
        self.assertIn("Switched on but withheld", html)
        self.assertIn("Stock Alerts", html)

    def test_all_six_panels_render_when_all_are_on(self):
        """The reported case, end to end."""
        self.client.force_login(self.admin)
        live = ",".join(f"{k}:{i}" for i, (k, *_) in enumerate(all_panels()))
        html = self.client.get(reverse("dashboard"),
                               {"preview": "1", "preview_group": self.group.id,
                                "panels": live}).content.decode()
        self.assertIn('class="qa-card"', html)          # Quick Actions
        self.assertIn('id="home-trk-map"', html)        # Field Team
        self.assertNotIn("Switched on but withheld", html)

        cards = self.client.get(reverse("dashboard_widgets_api"),
                                {"preview_group": self.group.id, "panels": live})
        self.assertEqual([w["key"] for w in cards.json()["widgets"]], ALL_KEYS)


class ManagerOrderTests(TestCase):
    """A manager's own dashboard must match its group's preview.

    The Admin access type bypasses the permission matrix, and that bypass was
    also discarding the group's widget order — so the preview showed the chosen
    layout and the manager's real dashboard showed the registry one.
    """

    def setUp(self):
        cache.clear()
        from user.models import GroupAccessProfile

        User = get_user_model()
        self.admin = User.objects.create_superuser("mo_admin", "ma@x.com",
                                                   "Str0ngPass!")
        self.group = Group.objects.create(name="Managers")
        GroupAccessProfile.objects.create(group=self.group, access_type="admin")
        self.manager = User.objects.create_user("mo_mgr", "mm@x.com", "Str0ngPass!")
        self.manager.groups.add(self.group)

        self.order = list(reversed(ALL_PANEL_KEYS))
        for position, key in enumerate(self.order):
            GroupDashboardWidget.objects.create(group=self.group, widget_key=key,
                                                enabled=True, position=position)

    def cards(self, client, **params):
        return [w["key"] for w in
                client.get(reverse("dashboard_widgets_api"), params).json()["widgets"]]

    def test_a_manager_gets_the_order_configured_for_their_group(self):
        self.client.force_login(self.manager)
        expected = [k for k in self.order if k in ALL_KEYS]
        self.assertEqual(self.cards(self.client), expected)

    def test_the_manager_dashboard_matches_its_own_preview(self):
        self.client.force_login(self.manager)
        mine = self.cards(self.client)

        self.client.force_login(self.admin)
        preview = self.cards(self.client, preview_group=self.group.id)
        self.assertEqual(mine, preview)

    def test_a_manager_still_bypasses_the_permission_matrix(self):
        """Order is a preference; access is not. The bypass must survive."""
        from user.access import allowed_view_tabs, ALL_TAB_CODES

        manager = get_user_model().objects.get(pk=self.manager.pk)
        self.assertEqual(allowed_view_tabs(manager), set(ALL_TAB_CODES))

    def test_switching_a_widget_off_applies_to_a_manager_too(self):
        GroupDashboardWidget.objects.filter(
            group=self.group, widget_key="receivables").update(enabled=False)
        self.client.force_login(self.manager)
        self.assertNotIn("receivables", self.cards(self.client))

    def test_a_superuser_in_no_configured_group_is_unaffected(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.cards(self.client), ALL_KEYS)


class DefaultPanelOrderTests(TestCase):
    """Quick Actions leads the dashboard unless a group says otherwise."""

    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.admin = User.objects.create_superuser("dp_admin", "d2@x.com",
                                                   "Str0ngPass!")
        self.group = Group.objects.create(name="Defaults Group")

    def test_quick_actions_is_first_in_the_registry(self):
        from user.services.dashboard_widgets import DEFAULT_PANEL_ORDER

        self.assertEqual([k for k, *_ in all_panels()][0], "quick_actions")
        self.assertEqual(DEFAULT_PANEL_ORDER[0], "quick_actions")

    def test_an_unconfigured_group_gets_quick_actions_at_the_top(self):
        from user.services.dashboard_widgets import dashboard_panels

        panels = dashboard_panels(None, as_group=self.group)
        self.assertEqual(panels["quick_actions"], 0)
        self.assertEqual(min(panels.values()), panels["quick_actions"])

    def test_the_editor_lists_it_first_for_a_new_group(self):
        import re

        self.client.force_login(self.admin)
        html = self.client.get(reverse("dashboard_access_form"),
                               {"group": self.group.id}).content.decode()
        self.assertEqual(re.findall(r'data-key="(\w+)"', html)[0], "quick_actions")

    def test_a_configured_group_keeps_its_own_order(self):
        """The default must not reach in and move a saved dashboard."""
        from user.services.dashboard_widgets import dashboard_panels

        for position, key in enumerate(["field_team", "quick_actions"]):
            GroupDashboardWidget.objects.create(group=self.group, widget_key=key,
                                                enabled=True, position=position)
        panels = dashboard_panels(None, as_group=self.group)
        self.assertEqual(panels["field_team"], 0)
        self.assertEqual(panels["quick_actions"], 1)

    def test_every_registry_panel_is_placed_in_the_default_order(self):
        """A panel added to WIDGETS but forgotten in DEFAULT_PANEL_ORDER still
        appears, but this fails first so the order stays deliberate."""
        from user.services.dashboard_widgets import DEFAULT_PANEL_ORDER

        self.assertEqual(set(k for k, *_ in all_panels()), set(DEFAULT_PANEL_ORDER))


class DashboardFlagTests(TestCase):
    """GroupAccessProfile.dashboard was stored and never read.

    A group with it switched off still landed on the full dashboard.
    """

    def setUp(self):
        cache.clear()
        from user.models import GroupAccessProfile

        User = get_user_model()
        self.user = User.objects.create_user("df_user", "df@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="No Dashboard")
        self.user.groups.add(self.group)
        GroupTabPermission.objects.create(group=self.group, tab_code="items",
                                          can_view=True)
        self.profile = GroupAccessProfile.objects.create(group=self.group,
                                                         dashboard=True)
        self.client.force_login(self.user)

    def test_with_the_flag_on_the_dashboard_renders(self):
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    def test_with_it_off_they_land_on_their_first_permitted_page(self):
        self.profile.dashboard = False
        self.profile.save()
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("items"))

    def test_home_behaves_the_same_way(self):
        self.profile.dashboard = False
        self.profile.save()
        self.assertEqual(self.client.get(reverse("home")).status_code, 302)

    def test_granted_in_any_group_is_granted(self):
        """Combined like every other permission here."""
        from user.models import GroupAccessProfile

        self.profile.dashboard = False
        self.profile.save()
        other = Group.objects.create(name="Has Dashboard")
        self.user.groups.add(other)
        GroupAccessProfile.objects.create(group=other, dashboard=True)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    def test_it_still_renders_when_there_is_nowhere_else_to_go(self):
        """The middleware's denial redirects to home, so refusing home would
        loop. An empty dashboard beats a redirect cycle."""
        self.profile.dashboard = False
        self.profile.save()
        GroupTabPermission.objects.filter(group=self.group).delete()
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)

    def test_a_superuser_is_unaffected(self):
        self.profile.dashboard = False
        self.profile.save()
        boss = get_user_model().objects.create_superuser("df_boss", "dfb@x.com",
                                                          "Str0ngPass!")
        self.client.force_login(boss)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    def test_the_editor_marks_the_flags_that_still_do_nothing(self):
        from user.access import UNENFORCED_FLAGS

        self.assertNotIn("dashboard", UNENFORCED_FLAGS)
        self.assertEqual(sorted(UNENFORCED_FLAGS),
                         ["is_superuser", "login_type",
                          "sale_multiple_delete", "sale_multiple_edit"])

        boss = get_user_model().objects.create_superuser("df_boss2", "dfb2@x.com",
                                                          "Str0ngPass!")
        self.client.force_login(boss)
        html = self.client.get(reverse("user_groups"),
                               {"group": self.group.id}).content.decode()
        self.assertIn("nothing reads them yet", html)
        self.assertIn("Dashboard is enforced", html)


class RegistryGrowthTests(TestCase):
    """A widget added after a group was configured must not vanish for it.

    The reported symptom: Alerts & Notifications had a switch in the editor,
    showing on, and never appeared on the dashboard. Managers had been saved
    when the registry held six widgets; Alerts was the seventh, so it had no
    row — and "no row" was being read as "switched off" while the editor read
    it as "on". The two disagreed, permanently and silently.
    """

    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.member = User.objects.create_user("rg_member", "r@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Configured Early")
        self.member.groups.add(self.group)
        for key, _t, tabs, *_ in all_panels():
            for tab in tabs:
                GroupTabPermission.objects.get_or_create(
                    group=self.group, tab_code=tab, defaults={"can_view": True})

    def user(self):
        return get_user_model().objects.get(pk=self.member.pk)

    def panels(self):
        from user.services.dashboard_widgets import dashboard_panels
        return dashboard_panels(self.user())

    def configure_all_but(self, missing):
        """Save every widget except one — as an older registry would have."""
        GroupDashboardWidget.objects.filter(group=self.group).delete()
        for index, (key, *_rest) in enumerate(all_panels()):
            if key == missing:
                continue
            GroupDashboardWidget.objects.create(
                group=self.group, widget_key=key, enabled=True, position=index)

    def test_a_widget_with_no_saved_row_still_shows(self):
        self.configure_all_but("alerts_widget")
        self.assertIn("alerts_widget", self.panels())

    def test_it_matches_what_the_editor_shows_for_that_widget(self):
        """The editor defaults an unsaved widget's switch to on; the dashboard
        has to agree, or the page is lying about what it does."""
        self.configure_all_but("alerts_widget")
        admin = get_user_model().objects.create_superuser("rg_admin", "a@x.com",
                                                          "Str0ngPass!")
        self.client.force_login(admin)
        html = self.client.get(reverse("dashboard_access_form"),
                               {"group": self.group.id}).content.decode()
        marker = 'name="on_alerts_widget"'
        row = html[html.index(marker) - 200:html.index(marker) + 120]
        self.assertIn("checked", row)
        self.assertIn("alerts_widget", self.panels())

    def test_an_explicitly_disabled_widget_still_stays_off(self):
        """The fix must not turn "off" into "on" — only "unanswered"."""
        GroupDashboardWidget.objects.filter(group=self.group).delete()
        for index, (key, *_rest) in enumerate(all_panels()):
            GroupDashboardWidget.objects.create(
                group=self.group, widget_key=key,
                enabled=key != "alerts_widget", position=index)
        self.assertNotIn("alerts_widget", self.panels())

    def test_an_unconfigured_group_is_unaffected(self):
        self.assertEqual(set(self.panels()), {k for k, *_ in all_panels()})
