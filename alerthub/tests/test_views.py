"""The API and the pages, including the parts that must refuse.

The detail-page test is the important one here: a notification id is guessable,
so the page has to re-check permission rather than trust whatever linked to it.
"""
from __future__ import annotations

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from alerthub.constants import Priority
from alerthub.engine import raise_alert
from alerthub.models import AlertRule, Notification, NotificationPreference

from .test_scoping import ScopeTestCase


def grant(group, *tab_codes):
    """Give a group view rights on the named tabs.

    The Alert Configuration screens are matrix-gated like any other master, so
    a test that opens them has to say so — which is also the assertion that the
    gate is wired to the right tab codes.
    """
    from user.models import GroupTabPermission

    for code in tab_codes:
        GroupTabPermission.objects.update_or_create(
            group=group, tab_code=code,
            defaults={"can_view": True, "can_add": True, "can_edit": True,
                      "can_delete": True},
        )


class ApiTests(ScopeTestCase):
    def setUp(self):
        self.rule = self.make_rule()
        self.alert_a = raise_alert(
            self.rule, title="Mortality at Akbarpur", dedupe_key="a",
            branch=self.branch_a, farm=self.farm_a,
        )
        self.alert_b = raise_alert(
            self.rule, title="Mortality at Basti", dedupe_key="b",
            branch=self.branch_b, farm=self.farm_b,
        )

    def test_list_is_scoped_to_the_caller(self):
        self.client.force_login(self.user_a)
        response = self.client.get("/api/alerthub/notifications/")
        self.assertEqual(response.status_code, 200)

        titles = [row["title"] for row in response.json()["results"]]
        self.assertEqual(titles, ["Mortality at Akbarpur"])

    def test_unread_count_is_scoped(self):
        self.client.force_login(self.user_a)
        response = self.client.get("/api/alerthub/notifications/unread_count/")
        self.assertEqual(response.json()["unread"], 1)

        self.client.force_login(self.user_all)
        response = self.client.get("/api/alerthub/notifications/unread_count/")
        self.assertEqual(response.json()["unread"], 2)

    def test_anonymous_is_refused(self):
        response = self.client.get("/api/alerthub/notifications/")
        self.assertIn(response.status_code, (401, 403))

    def test_retrieving_another_branches_alert_is_a_404(self):
        self.client.force_login(self.user_a)
        response = self.client.get(
            f"/api/alerthub/notifications/{self.alert_b.pk}/"
        )
        self.assertEqual(response.status_code, 404)

    def test_mark_read_clears_only_the_callers_badge(self):
        self.client.force_login(self.user_a)
        response = self.client.post(
            f"/api/alerthub/notifications/{self.alert_a.pk}/mark_read/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["unread"], 0)

        self.client.force_login(self.user_all)
        response = self.client.get("/api/alerthub/notifications/unread_count/")
        self.assertEqual(response.json()["unread"], 2)

    def test_mark_all_read(self):
        self.client.force_login(self.user_all)
        response = self.client.post("/api/alerthub/notifications/mark_all_read/")
        self.assertEqual(response.json()["marked_read"], 2)
        self.assertEqual(response.json()["unread"], 0)

    def test_summary_counts_are_scoped(self):
        self.client.force_login(self.user_a)
        data = self.client.get("/api/alerthub/notifications/summary/").json()
        self.assertEqual(data["critical"], 1)
        self.assertEqual(data["unread"], 1)
        self.assertTrue(any(t["key"] == "high_mortality" for t in data["tiles"]))

    def test_recent_returns_unread_urgency_first(self):
        self.client.force_login(self.user_all)
        data = self.client.get("/api/alerthub/notifications/recent/").json()
        self.assertEqual(len(data["results"]), 2)
        self.assertEqual(data["unread"], 2)

    def test_priority_filter(self):
        self.client.force_login(self.user_all)
        response = self.client.get(
            "/api/alerthub/notifications/?priority=critical"
        )
        self.assertEqual(response.json()["count"], 2)
        response = self.client.get("/api/alerthub/notifications/?priority=low")
        self.assertEqual(response.json()["count"], 0)

    def test_branch_filter_cannot_reach_outside_scope(self):
        """Passing another branch's id returns nothing, not that branch's data."""
        self.client.force_login(self.user_a)
        response = self.client.get(
            f"/api/alerthub/notifications/?branch={self.branch_b.pk}"
        )
        self.assertEqual(response.json()["count"], 0)


class PreferenceApiTests(ScopeTestCase):
    def test_read_and_write_own_preferences(self):
        self.client.force_login(self.user_a)

        data = self.client.get("/api/alerthub/preferences/").json()
        self.assertTrue(data["receive_in_app"])

        response = self.client.post(
            "/api/alerthub/preferences/",
            data={"sound_notification": True, "min_priority": "high"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        pref = NotificationPreference.objects.get(user=self.user_a)
        self.assertTrue(pref.sound_notification)
        self.assertEqual(pref.min_priority, "high")


class PageTests(ScopeTestCase):
    def setUp(self):
        self.rule = self.make_rule()
        self.alert_a = raise_alert(
            self.rule, title="Mortality at Akbarpur", dedupe_key="a",
            branch=self.branch_a, farm=self.farm_a,
        )
        self.alert_b = raise_alert(
            self.rule, title="Mortality at Basti", dedupe_key="b",
            branch=self.branch_b, farm=self.farm_b,
        )

    def test_personal_pages_render_without_any_tab_permission(self):
        """The centre, history and preferences belong to no module's tab.

        Every user reads the alerts addressed to them regardless of which
        modules they can open — that is why these url names are in
        ``PUBLIC_URL_NAMES``. user_all has an access profile and no tab rows,
        so this would 302 if they were matrix-gated.
        """
        self.client.force_login(self.user_all)
        for name in ("alerthub:notification_center",
                     "alerthub:notification_history",
                     "alerthub:preferences"):
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_config_master_is_refused_without_the_tab_permission(self):
        """The administrative screens *are* matrix-gated, unlike the feed."""
        self.client.force_login(self.user_all)
        for name in ("alerthub:alert_rule_list", "alerthub:alert_catalog"):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertNotEqual(response.status_code, 200)

    def test_config_master_renders_with_the_tab_permission(self):
        grant(self.group_all, "alert_rule_list", "alert_catalog")
        self.client.force_login(self.user_all)
        for name in ("alerthub:alert_rule_list",
                     "alerthub:alert_rule_create",
                     "alerthub:alert_catalog"):
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_detail_page_refuses_another_branches_alert_with_404(self):
        """404 rather than 403 — confirming the alert exists is itself a leak."""
        self.client.force_login(self.user_a)
        response = self.client.get(
            reverse("alerthub:notification_detail", args=[self.alert_b.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_opening_the_detail_page_marks_it_read(self):
        self.client.force_login(self.user_a)
        response = self.client.get(
            reverse("alerthub:notification_detail", args=[self.alert_a.pk])
        )
        self.assertEqual(response.status_code, 200)

        recipient = self.alert_a.recipients.get(user=self.user_a)
        self.assertTrue(recipient.is_read)
        self.assertIsNotNone(recipient.read_at)

    def test_pages_require_login(self):
        response = self.client.get(reverse("alerthub:notification_center"))
        self.assertEqual(response.status_code, 302)


class RuleFormTests(ScopeTestCase):
    def setUp(self):
        grant(self.group_all, "alert_rule_list", "alert_catalog")

    def test_creating_a_rule(self):
        self.client.force_login(self.user_all)
        response = self.client.post(reverse("alerthub:alert_rule_create"), {
            "name": "Mortality watch",
            "rule_key": "production.high_mortality",
            "priority": "critical",
            "operator": "gte",
            "threshold": "0.75",
            "cooldown_hours": "24",
            "via_in_app": "on",
            "is_active": "on",
        })
        self.assertEqual(response.status_code, 302)

        rule = AlertRule.objects.get(name="Mortality watch")
        # module is derived from the catalogue rather than posted.
        self.assertEqual(rule.module, "production")

    def test_a_thresholdless_rule_rejects_a_threshold(self):
        self.client.force_login(self.user_all)
        response = self.client.post(reverse("alerthub:alert_rule_create"), {
            "name": "Negative stock",
            "rule_key": "inventory.negative_stock",
            "priority": "critical",
            "operator": "gte",
            "threshold": "5",
            "cooldown_hours": "24",
            "via_in_app": "on",
        })
        self.assertEqual(response.status_code, 200)   # re-rendered with errors
        self.assertFalse(AlertRule.objects.filter(name="Negative stock").exists())

    def test_a_rule_needing_a_threshold_requires_one(self):
        self.client.force_login(self.user_all)
        response = self.client.post(reverse("alerthub:alert_rule_create"), {
            "name": "Mortality no threshold",
            "rule_key": "production.high_mortality",
            "priority": "critical",
            "operator": "gte",
            "cooldown_hours": "24",
            "via_in_app": "on",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            AlertRule.objects.filter(name="Mortality no threshold").exists()
        )

    def test_deleting_a_rule_keeps_its_notifications(self):
        rule = self.make_rule(name="Doomed")
        raise_alert(rule, title="A", dedupe_key="a", branch=self.branch_a,
                    farm=self.farm_a)

        self.client.force_login(self.user_all)
        response = self.client.post(
            reverse("alerthub:alert_rule_delete", args=[rule.pk])
        )
        self.assertEqual(response.status_code, 302)

        self.assertFalse(AlertRule.objects.filter(pk=rule.pk).exists())
        notification = Notification.objects.get(title="A")
        self.assertIsNone(notification.rule_id)
        self.assertEqual(notification.rule_key, "production.high_mortality")
