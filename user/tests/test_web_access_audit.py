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
        """/branch_list/ is not claimed by any tab. Today it is open, and audit
        mode must not change that."""
        response = self.client.get("/branch_list/")
        self.assertEqual(response.status_code, 200)

    def test_the_unmapped_url_is_recorded(self):
        self.client.get("/branch_list/")
        row = WebAccessAudit.objects.get(url_name="branch_list")
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
            self.client.get("/branch_list/")
        rows = WebAccessAudit.objects.filter(url_name="branch_list")
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().hits, 3)

    def test_the_throttle_stops_a_row_per_request(self):
        for _ in range(3):
            self.client.get("/branch_list/")   # no cache.clear() this time
        self.assertEqual(WebAccessAudit.objects.get(url_name="branch_list").hits, 1)

    def test_different_users_are_recorded_separately(self):
        from django.core.cache import cache

        User = get_user_model()
        other = User.objects.create_user("auditclerk2", "b@x.com", "Str0ngPass!")
        other.groups.add(Group.objects.get(name="Items Only"))
        self.client.get("/branch_list/")
        cache.clear()
        self.client.force_login(other)
        self.client.get("/branch_list/")
        self.assertEqual(
            set(WebAccessAudit.objects.filter(url_name="branch_list")
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
        response = self.client.get("/branch_list/")
        self.assertEqual(response.status_code, 302)

    @override_settings(WEB_ACCESS_ENFORCE=True)
    def test_enforcing_leaves_public_urls_alone(self):
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    @override_settings(WEB_ACCESS_ENFORCE=True)
    def test_enforcing_answers_ajax_with_403_not_a_redirect(self):
        response = self.client.get("/branch_list/",
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
