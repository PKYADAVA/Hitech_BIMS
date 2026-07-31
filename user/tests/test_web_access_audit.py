"""The Web-Access guard's audit mode.

The contract that matters: with WEB_ACCESS_ENFORCE off, behaviour is *exactly*
what it was before — nothing new is refused — while the requests that would be
refused once it is on get recorded. If that is not true the audit is worse than
useless, because it would be changing the very behaviour it is meant to measure.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse

from user.models import GroupTabPermission, WebAccessAudit


class WebAccessAuditTests(TestCase):
    def setUp(self):
        from django.core.cache import cache

        # The write throttle lives in the process cache, which outlives a test
        # database. Without this, the second test to hit a url finds the
        # throttle already set and records nothing.
        cache.clear()
        User = get_user_model()
        self.clerk = User.objects.create_user("auditclerk", "a@x.com", "Str0ngPass!")
        group = Group.objects.create(name="Items Only")
        self.clerk.groups.add(group)
        # One row is enough to take the user out of the "unconfigured, so allow
        # everything" bypass.
        GroupTabPermission.objects.create(group=group, tab_code="items", can_view=True)
        self.client.force_login(self.clerk)

    # ---- audit mode changes nothing --------------------------------------

    def test_an_unmapped_url_still_works_in_audit_mode(self):
        """/gc_settlement_batches/ is claimed by no tab and matches no naming
        convention. Today it is open, and audit mode must not change that."""
        response = self.client.get("/gc_settlement_batches/")
        self.assertEqual(response.status_code, 200)

    def test_the_unmapped_url_is_recorded(self):
        self.client.get("/gc_settlement_batches/")
        row = WebAccessAudit.objects.get(url_name="gc_settlement_batches")
        self.assertEqual(row.verdict, WebAccessAudit.UNMAPPED)
        self.assertEqual(row.username, "auditclerk")
        self.assertEqual(row.method, "GET")
        self.assertTrue(row.view.startswith("broiler."))

    def test_a_mapped_denial_still_denies_and_is_recorded(self):
        """This one was already enforced; the audit must not weaken it."""
        response = self.client.get(reverse("coa"))
        self.assertEqual(response.status_code, 302)          # bounced home
        row = WebAccessAudit.objects.get(url_name="coa")
        self.assertEqual(row.verdict, WebAccessAudit.DENIED)
        self.assertEqual(row.tab_code, "coa")
        self.assertEqual(row.action, "view")

    def test_a_permitted_page_is_not_recorded(self):
        response = self.client.get(reverse("items"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(WebAccessAudit.objects.filter(url_name="items").exists())

    def test_public_urls_are_never_recorded(self):
        self.client.get(reverse("dashboard"))
        self.assertFalse(WebAccessAudit.objects.filter(url_name="dashboard").exists())
        self.assertFalse(WebAccessAudit.objects.filter(url_name="home").exists())

    # ---- what it records --------------------------------------------------

    def test_repeat_hits_increment_rather_than_duplicate(self):
        from django.core.cache import cache

        for _ in range(3):
            cache.clear()                 # bypass the write throttle
            self.client.get("/gc_settlement_batches/")
        rows = WebAccessAudit.objects.filter(url_name="gc_settlement_batches")
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().hits, 3)

    def test_the_throttle_stops_a_row_per_request(self):
        for _ in range(3):
            self.client.get("/gc_settlement_batches/")   # no cache.clear() this time
        self.assertEqual(WebAccessAudit.objects.get(url_name="gc_settlement_batches").hits, 1)

    def test_different_users_are_recorded_separately(self):
        from django.core.cache import cache

        User = get_user_model()
        other = User.objects.create_user("auditclerk2", "b@x.com", "Str0ngPass!")
        other.groups.add(Group.objects.get(name="Items Only"))
        self.client.get("/gc_settlement_batches/")
        cache.clear()
        self.client.force_login(other)
        self.client.get("/gc_settlement_batches/")
        self.assertEqual(
            set(WebAccessAudit.objects.filter(url_name="gc_settlement_batches")
                .values_list("username", flat=True)),
            {"auditclerk", "auditclerk2"})

    def test_an_unconfigured_user_bypasses_and_is_not_recorded(self):
        """Documents today's fail-open: a group with no matrix rows is treated
        as unrestricted, so nothing is denied and nothing is worth recording."""
        User = get_user_model()
        free = User.objects.create_user("auditfree", "f@x.com", "Str0ngPass!")
        free.groups.add(Group.objects.create(name="Nothing Configured"))
        self.client.force_login(free)
        self.assertEqual(self.client.get(reverse("coa")).status_code, 200)
        self.assertFalse(WebAccessAudit.objects.filter(verdict="denied").exists())

    # ---- and what happens when it is switched on -------------------------

    @override_settings(WEB_ACCESS_ENFORCE=True)
    def test_enforcing_closes_the_unmapped_url(self):
        response = self.client.get("/gc_settlement_batches/")
        self.assertEqual(response.status_code, 302)

    @override_settings(WEB_ACCESS_ENFORCE=True)
    def test_enforcing_leaves_public_urls_alone(self):
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    @override_settings(WEB_ACCESS_ENFORCE=True)
    def test_enforcing_answers_ajax_with_403_not_a_redirect(self):
        response = self.client.get("/gc_settlement_batches/",
                                   HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 403)

    @override_settings(WEB_ACCESS_ENFORCE=True)
    def test_a_permitted_page_survives_enforcement(self):
        self.assertEqual(self.client.get(reverse("items")).status_code, 200)


class WebAccessAuditCommandTests(TestCase):
    def test_the_summary_runs_and_names_the_urls(self):
        from io import StringIO
        from django.core.management import call_command

        WebAccessAudit.objects.create(
            url_name="branch_toggle_active", method="POST", verdict="unmapped",
            username="clerk", view="broiler.views.toggle", hits=4)
        WebAccessAudit.objects.create(
            url_name="region_list", method="GET", verdict="unmapped",
            username="clerk", view="broiler.views.RegionAPI", hits=9)

        out = StringIO()
        call_command("webaccess_audit", stdout=out)
        text = out.getvalue()
        self.assertIn("branch_toggle_active", text)
        self.assertIn("region_list", text)
        # writes are called out separately — an open mutation matters more
        self.assertIn("WRITE endpoints", text)
        self.assertLess(text.index("WRITE endpoints"), text.index("READ endpoints"))

    def test_clear_empties_the_table(self):
        from io import StringIO
        from django.core.management import call_command

        WebAccessAudit.objects.create(url_name="x", method="GET",
                                      verdict="unmapped", username="u")
        call_command("webaccess_audit", clear=True, stdout=StringIO())
        self.assertEqual(WebAccessAudit.objects.count(), 0)


class NoConfigDefaultTests(TestCase):
    """A group saved with nothing ticked must grant nothing.

    Counting only tab rows made such a group look untouched, so its members got
    every tab — the opposite of what ticking nothing means.
    """

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def user_in(self, group_name, with_profile=False, with_tab=None):
        from user.models import GroupAccessProfile

        User = get_user_model()
        user = User.objects.create_user(group_name.lower().replace(" ", ""),
                                        f"{group_name}@x.com", "Str0ngPass!")
        group = Group.objects.create(name=group_name)
        user.groups.add(group)
        if with_profile:
            GroupAccessProfile.objects.create(group=group)
        if with_tab:
            GroupTabPermission.objects.create(group=group, tab_code=with_tab,
                                              can_view=True)
        return get_user_model().objects.get(pk=user.pk)

    def test_an_untouched_group_is_still_unrestricted(self):
        """The fail-open that keeps pre-existing accounts working."""
        from user.access import ALL_TAB_CODES, allowed_view_tabs

        user = self.user_in("Untouched Group")
        self.assertEqual(allowed_view_tabs(user), set(ALL_TAB_CODES))

    def test_a_group_saved_with_nothing_ticked_grants_nothing(self):
        from user.access import allowed_view_tabs, user_can

        user = self.user_in("Saved Empty", with_profile=True)
        self.assertEqual(allowed_view_tabs(user), set())
        self.assertFalse(user_can(user, "coa", "view"))
        self.assertFalse(user_can(user, "coa", "delete"))

    def test_a_group_with_one_tab_is_held_to_it(self):
        from user.access import allowed_view_tabs

        user = self.user_in("One Tab", with_profile=True, with_tab="items")
        self.assertEqual(allowed_view_tabs(user), {"items"})


class PrintRightTests(TestCase):
    """Exporting is the Print column, which nothing had ever checked."""

    def setUp(self):
        from django.core.cache import cache
        from user.models import GroupAccessProfile

        cache.clear()
        User = get_user_model()
        self.user = User.objects.create_user("pr_user", "pr@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Report Readers")
        self.user.groups.add(self.group)
        GroupAccessProfile.objects.create(group=self.group)
        self.perm = GroupTabPermission.objects.create(
            group=self.group, tab_code="negative_stock_report", can_view=True)
        self.client.force_login(self.user)

    def test_viewing_a_report_is_allowed(self):
        self.assertEqual(
            self.client.get(reverse("negative_stock_report")).status_code, 200)

    def test_exporting_it_without_the_print_right_is_refused(self):
        response = self.client.get(reverse("negative_stock_report"),
                                   {"export": "excel"})
        self.assertEqual(response.status_code, 302)

    def test_exporting_with_the_print_right_is_allowed(self):
        self.perm.can_print = True
        self.perm.save()
        response = self.client.get(reverse("negative_stock_report"),
                                   {"export": "excel"})
        self.assertEqual(response.status_code, 200)

    def test_export_display_is_not_an_export(self):
        """Several reports pass export=display for the on-screen view."""
        response = self.client.get(reverse("negative_stock_report"),
                                   {"export": "display"})
        self.assertEqual(response.status_code, 200)

    def test_the_editor_marks_the_columns_that_still_do_nothing(self):
        from user.access import UNENFORCED_ACTIONS

        self.assertEqual(UNENFORCED_ACTIONS, ["save", "update", "favorite"])
        self.assertNotIn("print", UNENFORCED_ACTIONS)

        boss = get_user_model().objects.create_superuser("pr_boss", "pb@x.com",
                                                          "Str0ngPass!")
        self.client.force_login(boss)
        html = self.client.get(reverse("user_groups"),
                               {"group": self.group.id}).content.decode()
        self.assertIn("nothing reads them yet", html)


class MappedFromAuditTests(TestCase):
    """The urls the audit surfaced are now claimed, and stay claimed.

    A url that slips back out of the mapping does not raise — it just becomes
    open again, which is exactly the failure this whole exercise is about.
    """

    #: What `manage.py webaccess_audit` reported, and how each was resolved.
    RECORDED = {
        "bird_sale_api_list": "bird_sale_list",
        "broiler_batch_list": "broiler_batch",
        "broiler_farm_detail": "branch_farm",
        "broiler_farm_list": "branch_farm",
        "broiler_farm_shed_list": "broiler_farm_shed",
        "daily_entry_api_list": "daily_entry_list",
        "farmer_detail": "branch_farm",
        "farmer_list": "branch_farm",
        "stock_transfer_api": "stock_transfer_list",
        "stock_transfer_api_list": "stock_transfer_list",
        "stock_transfer_farm_batches": "stock_transfer_list",
        "stock_transfer_item_lookup": "stock_transfer_list",
    }
    PUBLIC = ["alert-unread-count", "get_branches_by_region",
              "get_lines_by_branch", "get_supervisors"]

    def test_each_audited_url_now_belongs_to_its_tab(self):
        from user.access import URLNAME_TO_TAB

        for url_name, tab in self.RECORDED.items():
            with self.subTest(url=url_name):
                self.assertEqual(URLNAME_TO_TAB.get(url_name), tab)

    def test_the_shared_pickers_are_public_rather_than_misassigned(self):
        from user.access import PUBLIC_URL_NAMES

        for url_name in self.PUBLIC:
            with self.subTest(url=url_name):
                self.assertIn(url_name, PUBLIC_URL_NAMES)

    def test_a_mapped_json_endpoint_now_obeys_the_matrix(self):
        """/daily_entry_api/ was open; it was the data behind a page the matrix
        already refused."""
        from user.models import GroupAccessProfile

        User = get_user_model()
        clerk = User.objects.create_user("map_clerk", "m@x.com", "Str0ngPass!")
        group = Group.objects.create(name="Items Only Map")
        clerk.groups.add(group)
        GroupAccessProfile.objects.create(group=group)
        GroupTabPermission.objects.create(group=group, tab_code="items",
                                          can_view=True)
        self.client.force_login(clerk)

        response = self.client.get("/daily_entry_api/",
                                   HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 403)


class ProductionAuditMappingTests(TestCase):
    """Everything the first production audit reported is now claimed.

    30 urls, 6 of them accepting writes. A url that falls back out of the
    mapping does not raise — it silently becomes open again.
    """

    PRODUCTION_AUDIT = """
        broiler_farm_shed_create broiler_line_list farmer_create farmer_update
        stock_transfer_api stock_transfer_api_list alert-unread-count branch_list
        broiler_batch_list broiler_farm_detail broiler_farm_list
        broiler_farm_shed_list change_request_api_list chicks_purchase_api_list
        daily_entry_api_list daily_entry_farm_lookup farmer_detail
        farmer_group_list farmer_list feed_phase_master_api_list
        get_branches_by_region get_lines_by_branch get_supervisors
        payment_api_list region_list sms_transaction_source
        stock_transfer_farm_batches stock_transfer_item_lookup
        stock_transfer_stock_lookup supervisor_list
    """.split()

    def test_none_of_them_is_still_unmapped(self):
        from user.access import PUBLIC_URL_NAMES, URLNAME_TO_TAB, resolve_action

        unmapped = [n for n in self.PRODUCTION_AUDIT
                    if n not in PUBLIC_URL_NAMES and n not in URLNAME_TO_TAB
                    and resolve_action(n) is None]
        self.assertEqual(unmapped, [])

    def test_the_mutations_need_their_own_right_not_merely_view(self):
        """Routed through the action-suffix map rather than extra_urls, so
        creating a farmer needs add and updating one needs edit."""
        from user.access import resolve_action

        self.assertEqual(resolve_action("farmer_create"), ("branch_farm", "add"))
        self.assertEqual(resolve_action("farmer_update"), ("branch_farm", "edit"))
        self.assertEqual(resolve_action("broiler_farm_shed_create"),
                         ("broiler_farm_shed", "add"))

    def test_a_write_endpoint_is_refused_without_the_right(self):
        from user.models import GroupAccessProfile

        User = get_user_model()
        clerk = User.objects.create_user("pa_clerk", "pa@x.com", "Str0ngPass!")
        group = Group.objects.create(name="Farm Viewers")
        clerk.groups.add(group)
        GroupAccessProfile.objects.create(group=group)
        GroupTabPermission.objects.create(group=group, tab_code="branch_farm",
                                          can_view=True)
        self.client.force_login(clerk)

        response = self.client.post("/create-farmer/", {"farmer_name": "Sneaked"},
                                    content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_the_same_write_is_allowed_with_the_add_right(self):
        from user.models import GroupAccessProfile

        User = get_user_model()
        clerk = User.objects.create_user("pa_clerk2", "pa2@x.com", "Str0ngPass!")
        group = Group.objects.create(name="Farm Editors")
        clerk.groups.add(group)
        GroupAccessProfile.objects.create(group=group)
        GroupTabPermission.objects.create(group=group, tab_code="branch_farm",
                                          can_view=True, can_add=True)
        self.client.force_login(clerk)

        response = self.client.post("/create-farmer/", {"farmer_name": "Allowed"},
                                    content_type="application/json")
        self.assertNotEqual(response.status_code, 403)


class ScopedPickerTests(TestCase):
    """The shared pickers are public, so their data has to be scoped instead."""

    def setUp(self):
        from django.core.cache import cache
        from broiler.models import Branch, Region, Supervisor
        from user.models import GroupAccessProfile

        cache.clear()
        User = get_user_model()
        self.user = User.objects.create_user("pick_user", "pk@x.com", "Str0ngPass!")
        group = Group.objects.create(name="Akbarpur Picker")
        self.user.groups.add(group)

        self.region = Region.objects.create(description="East")
        self.mine = Branch.objects.create(branch_name="Akbarpur", region=self.region,
                                          prefix="AKB")
        self.theirs = Branch.objects.create(branch_name="Bahraich",
                                            region=self.region, prefix="BHR")
        Supervisor.objects.create(branch=self.theirs, name="Their Supervisor")

        profile = GroupAccessProfile.objects.create(group=group, all_branches=False)
        profile.branches.add(self.mine)
        self.client.force_login(self.user)

    def test_the_branch_picker_lists_only_permitted_branches(self):
        body = self.client.get("/get-branches-by-region/",
                               {"region_id": self.region.id}).content.decode()
        self.assertIn("Akbarpur", body)
        self.assertNotIn("Bahraich", body)

    def test_the_supervisor_picker_refuses_another_branch(self):
        body = self.client.get("/get-supervisors/",
                               {"branch_id": self.theirs.id}).content.decode()
        self.assertNotIn("Their Supervisor", body)


class DerivedTabTests(TestCase):
    """Endpoints named after the tab they serve are claimed by one rule.

    Most of the unmapped surface is the JSON behind a page the matrix already
    governs. A hand-written list would be out of date by the next feature.
    """

    def test_read_endpoints_take_the_tabs_view_right(self):
        from user.access import derive_tab

        cases = {
            "broiler_disease_list": ("broiler_disease", "view"),
            "medicine_entry_api_list": ("medicine_entry_list", "view"),
            "daily_entry_stock_lookup": ("daily_entry_list", "view"),
            "user_analytics_data": ("user_analytics", "view"),
        }
        for url_name, expected in cases.items():
            with self.subTest(url=url_name):
                self.assertEqual(derive_tab(url_name), expected)

    def test_mutations_take_their_own_right(self):
        """The toggles and bulk deletes the first audit flagged as open."""
        from user.access import derive_tab

        self.assertEqual(derive_tab("region_toggle_active"), ("region", "edit"))
        self.assertEqual(derive_tab("farmer_group_toggle_lock"),
                         ("farmer_group", "edit"))
        self.assertEqual(derive_tab("daily_entry_group_delete"),
                         ("daily_entry_list", "delete"))

    def test_a_near_miss_maps_to_nothing_rather_than_the_wrong_tab(self):
        """A wrong mapping refuses what the web app allows, which is worse than
        leaving it for the audit."""
        from user.access import derive_tab

        self.assertIsNone(derive_tab("something_unrelated_list"))
        self.assertIsNone(derive_tab("list"))
        self.assertIsNone(derive_tab(""))
        self.assertIsNone(derive_tab("items"))          # no suffix at all

    def test_a_derived_read_endpoint_now_obeys_the_matrix(self):
        from user.models import GroupAccessProfile

        User = get_user_model()
        clerk = User.objects.create_user("dv_clerk", "dv@x.com", "Str0ngPass!")
        group = Group.objects.create(name="Items Only Derived")
        clerk.groups.add(group)
        GroupAccessProfile.objects.create(group=group)
        GroupTabPermission.objects.create(group=group, tab_code="items",
                                          can_view=True)
        self.client.force_login(clerk)

        response = self.client.get("/medicine_entry_api/",
                                   HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 403)

    def test_a_derived_mutation_needs_the_edit_right(self):
        from broiler.models import Region
        from user.models import GroupAccessProfile

        User = get_user_model()
        clerk = User.objects.create_user("dv_clerk2", "dv2@x.com", "Str0ngPass!")
        group = Group.objects.create(name="Region Viewers")
        clerk.groups.add(group)
        GroupAccessProfile.objects.create(group=group)
        perm = GroupTabPermission.objects.create(group=group, tab_code="region",
                                                 can_view=True)
        region = Region.objects.create(description="Toggle Me")
        self.client.force_login(clerk)

        url = f"/region/{region.id}/toggle-active/"
        self.assertEqual(self.client.post(url).status_code, 403)

        perm.can_edit = True
        perm.save()
        self.assertNotEqual(self.client.post(url).status_code, 403)

    def test_crud_verbs_are_derived_too(self):
        """_ACTION_BASE_TO_TAB covers the bases someone listed by hand; this
        catches the rest, which is most of them."""
        from user.access import derive_tab

        cases = {
            "bird_category_create": ("bird_category", "add"),
            "feed_phase_master_add": ("feed_phase_master_list", "add"),
            "farm_location_capture_add": ("farm_location_capture_list", "add"),
        }
        for url_name, expected in cases.items():
            with self.subTest(url=url_name):
                self.assertEqual(derive_tab(url_name), expected)

    def test_the_hand_written_base_map_still_wins(self):
        """resolve_action runs first, so an explicit entry is never overridden
        by the convention — the two must agree where they overlap."""
        from user.access import derive_tab, resolve_action

        for url_name in ("farmer_create", "farmer_update",
                         "broiler_farm_shed_create"):
            with self.subTest(url=url_name):
                explicit = resolve_action(url_name)
                derived = derive_tab(url_name)
                self.assertIsNotNone(explicit)
                if derived is not None:
                    self.assertEqual(explicit, derived)


class AuditIsNotItselfAudited(TestCase):
    """The Web-Access audit table must not feed the alerts system.

    alerts auto-registers every model, so it picked this one up: each audit
    write raised its own alert, and `webaccess_audit --clear` emitted one per
    deleted row — a wall of WARNING ALERT lines. Auditing the audit table is
    circular, and it is infrastructure rather than a business record.
    """

    def test_the_model_is_excluded_from_alert_tracking(self):
        from alerts.constants import DEFAULT_IGNORE_MODELS
        from alerts.registry import registry

        self.assertIn("user.webaccessaudit", DEFAULT_IGNORE_MODELS)
        self.assertFalse(registry.is_registered(WebAccessAudit))

    def test_writing_and_clearing_raises_no_alerts(self):
        from alerts.models import Alert

        before = Alert.objects.count()
        for i in range(3):
            WebAccessAudit.objects.create(url_name=f"probe_{i}", method="GET",
                                          verdict="unmapped", username="probe")
        self.assertEqual(Alert.objects.count(), before)

        WebAccessAudit.objects.filter(username="probe").delete()
        self.assertEqual(Alert.objects.count(), before)

    def test_other_models_are_still_tracked(self):
        """The exclusion is one model, not a hole in the alerts system."""
        from alerts.registry import registry
        from broiler.models import Region

        self.assertTrue(registry.is_registered(Region))

    def test_the_purge_command_removes_only_the_audit_tables_own_rows(self):
        from io import StringIO
        from django.core.management import call_command

        from alerts.models import Alert

        mine = Alert.objects.create(model_name="WebAccessAudit", title="noise",
                                    message="unmapped: GET alert-list")
        theirs = Alert.objects.create(model_name="BroilerFarm", title="real",
                                      message="someone edited a farm")

        out = StringIO()
        call_command("purge_audit_alerts", dry_run=True, stdout=out)
        self.assertIn("would be removed", out.getvalue())
        self.assertTrue(Alert.objects.filter(pk=mine.pk).exists())   # dry run

        call_command("purge_audit_alerts", stdout=StringIO())
        self.assertFalse(Alert.objects.filter(pk=mine.pk).exists())
        self.assertTrue(Alert.objects.filter(pk=theirs.pk).exists())

    def test_the_alert_endpoints_no_longer_feed_the_loop(self):
        """Opening the alert centre recorded an audit row, which raised an
        alert, which appeared in the centre being read."""
        from user.access import PUBLIC_URL_NAMES

        for url_name in ("alert_center", "alert-list", "alert-unread-count",
                         "alert-mark-all-read"):
            with self.subTest(url=url_name):
                self.assertIn(url_name, PUBLIC_URL_NAMES)
