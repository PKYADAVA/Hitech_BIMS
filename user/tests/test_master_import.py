"""Spreadsheet import on master pages.

The parsers already existed as django-import-export Resources, but only inside
the Django admin, which is superuser-only. These tests cover the two things
that changed: who may run one, and that a bad file cannot half-write a master.
"""
import io

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from inventory.models import Item, ItemCategory
from user.models import GroupAccessProfile, GroupTabPermission
from user.services.bulk_import import IMPORTABLE, resource_for, template_columns


#: The columns Item actually requires. A thinner sheet is refused, which is
#: correct behaviour rather than the thing under test.
ITEM_HEADER = ("item_code,description,category,valuation_method,"
               "standard_cost_per_unit,usage,source,type,item_account")


def item_row(code, description, category):
    return "%s\n%s,%s,%s,Weighted Average,50,Produced,Purchased,Raw Material,Expense\n" % (
        ITEM_HEADER, code, description, category)


def sheet(text, name="import.csv"):
    buffer = io.BytesIO(text.encode("utf-8"))
    buffer.name = name
    return buffer


class ImportRegistryTests(TestCase):
    def test_every_registered_resource_actually_exists(self):
        """A registry entry pointing at a missing class would render an Import
        button that fails when clicked."""
        missing = [tab for tab in IMPORTABLE if resource_for(tab) is None]
        self.assertEqual(missing, [])

    def test_every_resource_yields_columns(self):
        empty = [tab for tab in IMPORTABLE if not template_columns(tab)]
        self.assertEqual(empty, [])

    def test_every_registered_tab_is_a_real_tab(self):
        from user.access import ALL_TAB_CODES

        for tab in IMPORTABLE:
            with self.subTest(tab=tab):
                self.assertIn(tab, ALL_TAB_CODES)


class ImportPermissionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser("mi_admin", "mi@x.com",
                                                   "Str0ngPass!")
        self.clerk = User.objects.create_user("mi_clerk", "mc@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Item Viewers")
        self.clerk.groups.add(self.group)
        GroupAccessProfile.objects.create(group=self.group)
        self.perm = GroupTabPermission.objects.create(
            group=self.group, tab_code="items", can_view=True)
        self.category = ItemCategory.objects.create(name="Feed")
        self.url = reverse("master_import", args=["items"])

    def test_view_rights_are_not_import_rights(self):
        """Importing is a bulk add — reading a master is not permission to
        rewrite it."""
        self.client.force_login(self.clerk)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_the_add_right_allows_it(self):
        self.perm.can_add = True
        self.perm.save()
        self.client.force_login(self.clerk)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_an_unregistered_page_is_a_404_not_a_500(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("master_import", args=["vouchers"]))
        self.assertEqual(response.status_code, 404)


class ImportRunTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser("ir_admin", "ir@x.com",
                                                   "Str0ngPass!")
        self.category = ItemCategory.objects.create(name="Feed")
        self.client.force_login(self.admin)
        self.url = reverse("master_import", args=["items"])

    def test_the_template_carries_the_resource_s_own_columns(self):
        """Template and parser cannot disagree if both come from the resource."""
        response = self.client.get(self.url, {"template": "csv"})
        self.assertEqual(response.status_code, 200)
        header = response.content.decode().strip().split(",")
        self.assertEqual(header, template_columns("items"))
        self.assertIn("attachment", response["Content-Disposition"])

    def test_a_dry_run_writes_nothing(self):
        before = Item.objects.count()
        response = self.client.post(self.url, {"file": sheet(
            item_row("IMP-1", "Imported Feed", self.category.name))})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["committed"])
        self.assertEqual(Item.objects.count(), before)

    def test_committing_writes(self):
        response = self.client.post(self.url, {
            "commit": "1",
            "file": sheet(item_row("IMP-2", "Committed Feed", self.category.name))})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["committed"])
        self.assertTrue(Item.objects.filter(description="Committed Feed").exists())

    def test_row_errors_come_back_numbered_as_the_sheet_shows_them(self):
        """"Row 2 is wrong" is only useful if row 2 is what they see."""
        response = self.client.post(self.url, {"file": sheet(
            item_row("BAD-1", "Orphan", "No Such Category"))})
        errors = response.json()["errors"]
        self.assertTrue(errors)
        self.assertEqual(errors[0]["row"], 2)      # 1 is the header

    def test_a_wrong_file_type_is_refused_politely(self):
        response = self.client.post(self.url, {"file": sheet("nope", "notes.txt")})
        self.assertEqual(response.status_code, 400)
        self.assertIn("csv", response.json()["errors"][0]["message"].lower())

    def test_no_file_is_a_message_not_a_crash(self):
        response = self.client.post(self.url, {})
        self.assertEqual(response.status_code, 400)
