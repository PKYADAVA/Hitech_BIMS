"""Duplicate Entries resolver: "Keep both" and the Resolved history.

A group kept as genuinely separate records stops being listed — on the page,
in the counts the dashboard card reads, in the export — while it holds only
those records. A further matching record brings it back. Undo restores it
and leaves the history row stamped.
"""
import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group as AuthGroup
from django.test import TestCase

from purchase.models import Supplier
from user.models import DuplicateDismissal, GroupTabPermission
from user.services import duplicate_scan


def supplier_groups(counts_only=False):
    check = duplicate_scan.run(only="supplier_name", counts_only=counts_only)[0]
    return check


class DuplicateResolverTests(TestCase):

    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("dupadmin", "d@x.com", "Str0ngPass!")
        self.client.force_login(self.admin)
        self.a = Supplier.objects.create(name="Shree Feeds")
        self.b = Supplier.objects.create(name="shree feeds")

    def keep(self, ids, **extra):
        body = dict(check="supplier_name", ids=ids, numbers="S-1, S-2", matched="shree feeds",
                    title="Suppliers with the same name", module="Purchase", note="Two firms", **extra)
        return self.client.post("/duplicate-entries/dismiss/", json.dumps(body), content_type="application/json")

    def ids(self, *rows):
        return ",".join(str(r.id) for r in rows)

    def test_the_group_is_found_before_anything_is_kept(self):
        self.assertEqual(supplier_groups().count, 1)
        self.assertEqual(supplier_groups(counts_only=True).count, 1)

    def test_keep_both_hides_the_group_everywhere(self):
        response = self.keep(self.ids(self.a, self.b))
        self.assertEqual(response.status_code, 200, response.content)
        full, counts = supplier_groups(), supplier_groups(counts_only=True)
        self.assertEqual((full.count, full.dismissed), (0, 1))
        self.assertEqual((counts.count, counts.dismissed), (0, 1))   # what the dashboard card reads
        d = DuplicateDismissal.objects.get()
        self.assertEqual((d.record_ids, d.note, d.dismissed_by), (self.ids(self.a, self.b), "Two firms", self.admin))

    def test_a_new_matching_record_brings_the_group_back(self):
        self.keep(self.ids(self.a, self.b))
        Supplier.objects.create(name="SHREE FEEDS")
        self.assertEqual(supplier_groups().count, 1)

    def test_a_kept_group_that_loses_a_record_stays_hidden(self):
        c = Supplier.objects.create(name="Shree Feeds ")  # not matched: trailing space differs
        Supplier.objects.create(name="SHREE FEEDS")
        third = Supplier.objects.get(name="SHREE FEEDS")
        self.keep(self.ids(self.a, self.b, third))
        third.delete()
        self.assertEqual(supplier_groups().count, 0)
        c.delete()

    def test_undo_lists_the_group_again_and_keeps_the_history(self):
        self.keep(self.ids(self.a, self.b))
        d = DuplicateDismissal.objects.get()
        response = self.client.post("/duplicate-entries/undo/", json.dumps({"id": d.id}),
                                    content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(supplier_groups().count, 1)
        d.refresh_from_db()
        self.assertIsNotNone(d.undone_at)
        self.assertEqual(d.undone_by, self.admin)

    def test_a_group_that_is_not_there_is_refused(self):
        self.assertEqual(self.keep(str(self.a.id)).status_code, 400)             # one record
        self.assertEqual(self.keep(self.ids(self.a) + ",999999").status_code, 400)  # a missing record
        response = self.client.post("/duplicate-entries/dismiss/", json.dumps({"check": "nope", "ids": "1,2"}),
                                    content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(DuplicateDismissal.objects.exists())

    def test_keeping_needs_edit_rights_on_the_page(self):
        viewer = get_user_model().objects.create_user("dupviewer", "v@x.com", "Str0ngPass!")
        group = AuthGroup.objects.create(name="Viewers")
        viewer.groups.add(group)
        GroupTabPermission.objects.create(group=group, tab_code="duplicate_analyser", can_view=True)
        self.client.force_login(viewer)
        self.assertIn(self.keep(self.ids(self.a, self.b)).status_code, (302, 403))
        self.assertFalse(DuplicateDismissal.objects.exists())
        html = self.client.get("/duplicate-entries/").content.decode()
        self.assertNotIn('class="dup-keep"', html)

    def test_the_page_offers_keep_both_and_shows_the_history(self):
        html = self.client.get("/duplicate-entries/").content.decode()
        self.assertIn('class="dup-keep"', html)
        self.assertIn('data-ids="%s"' % self.ids(self.a, self.b), html)
        self.keep(self.ids(self.a, self.b))
        html = self.client.get("/duplicate-entries/").content.decode()
        self.assertIn("Resolved (1)", html)
        self.assertIn("Two firms", html)
        self.assertIn("1 kept", html)


class DuplicatesCardMigrationTests(TestCase):
    """0018: a hand-set dashboard gains the card before Field Team; a default one is left alone."""

    def test_the_card_joins_a_configured_dashboard_before_field_team(self):
        import importlib
        from django.apps import apps
        from user.models import GroupDashboardWidget as W
        migration = importlib.import_module("user.migrations.0018_duplicates_widget_for_configured_groups")

        managers = AuthGroup.objects.create(name="Managers")
        for pos, key in enumerate(["quick_actions", "stock_alerts", "field_team"], 1):
            W.objects.create(group=managers, widget_key=key, position=pos)
        untouched = AuthGroup.objects.create(name="Defaults")
        migration.add_duplicates_card(apps, None)
        order = list(W.objects.filter(group=managers).order_by("position").values_list("widget_key", flat=True))
        self.assertEqual(order, ["quick_actions", "stock_alerts", "duplicates", "field_team"])
        self.assertFalse(W.objects.filter(group=untouched).exists())
        migration.add_duplicates_card(apps, None)   # running again changes nothing
        self.assertEqual(W.objects.filter(group=managers, widget_key="duplicates").count(), 1)
