"""Using a transaction should not require owning the masters it reads.

A master's JSON endpoints are registered under that master's tab, so a user
granted Daily Entry but not Broiler Farm was refused ``branch_list`` — and the
branch picker on the very transaction they had been granted came back empty.
Granting the master as well would work, and would hand out edit rights on
reference data to everyone who records a day's figures.

Read is opened; write is not. And opening the read does not widen what comes
back: these feeds are data-scoped, which is the other half of this file.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from broiler.models import Branch, Region
from hr.models import Employee
from user.access import MASTER_REFERENCE_URLS, user_can
from user.models import EmployeeAccessProfile, GroupTabPermission


class MasterReferenceReadTests(TestCase):
    def setUp(self):
        region = Region.objects.create(description="East")
        self.akbarpur = Branch.objects.create(branch_name="Akbarpur",
                                              region=region, prefix="AKB")
        self.tulsipur = Branch.objects.create(branch_name="Tulsipur",
                                              region=region, prefix="TUL")

        # Someone who may record a Daily Entry and nothing else.
        group = Group.objects.create(name="Transactions Only")
        GroupTabPermission.objects.create(group=group, tab_code="daily_entry",
                                          can_view=True, can_add=True)
        self.user = get_user_model().objects.create_user("driver", password="x")
        self.user.groups.add(group)
        self.client.force_login(self.user)

    def test_the_setup_is_what_the_bug_needs(self):
        self.assertTrue(user_can(self.user, "daily_entry", "view"))
        self.assertFalse(user_can(self.user, "branch_template", "view"))

    def test_the_branch_feed_answers_a_transaction_user(self):
        resp = self.client.get(reverse("branch_list"))
        self.assertEqual(resp.status_code, 200,
                         "the branch picker cannot be filled")

    def test_writing_a_master_still_needs_the_master(self):
        # Read is what a transaction needs. Creating a branch is not.
        resp = self.client.post(reverse("branch_list"), {})
        self.assertEqual(resp.status_code, 403)

    def test_the_set_covers_the_pickers_and_nothing_sensitive(self):
        from user.access import MASTER_REFERENCE_TABS

        self.assertIn("branch_list", MASTER_REFERENCE_URLS)
        self.assertIn("supervisor_list", MASTER_REFERENCE_URLS)
        # A transaction's own list is not reference data — it is the records.
        self.assertNotIn("bird_sale_api_list", MASTER_REFERENCE_URLS)
        self.assertNotIn("daily_entry_api_list", MASTER_REFERENCE_URLS)
        # "Every tab in a Master section" is the tempting rule and far too
        # wide. These stay behind their own tab, and this is what says so.
        for closed in ("sms_settings", "bank_cash", "coa", "fin_year",
                       "sales_price_master", "item_price_list", "tax_master",
                       "company_profile", "customer", "supplier"):
            self.assertNotIn(closed, MASTER_REFERENCE_TABS, closed)


class MobileMasterReferenceTests(TestCase):
    """The phone hits the same wall through a different gate.

    Daily Entry's screen needs farms, batches and supervisors to fill its
    pickers. Refusing those because the user was not also given the Broiler
    Farm master left the screen open with every dropdown empty.
    """

    def setUp(self):
        from rest_framework.test import APIClient

        region = Region.objects.create(description="East")
        self.branch = Branch.objects.create(branch_name="Bahraich",
                                            region=region, prefix="BHR")
        group = Group.objects.create(name="Transactions Only")
        GroupTabPermission.objects.create(group=group, tab_code="daily_entry",
                                          can_view=True, can_add=True)
        self.user = get_user_model().objects.create_user("driver", password="x")
        self.user.groups.add(group)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_the_pickers_answer(self):
        for path in ("/api/v1/broiler/farms/", "/api/v1/broiler/branches/",
                     "/api/v1/broiler/supervisors/", "/api/v1/broiler/batches/"):
            self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_a_master_outside_the_list_is_still_refused(self):
        # Suppliers carry contact details and credit terms, and nothing
        # reported needs them — so the matrix still governs them.
        self.assertEqual(
            self.client.get("/api/v1/purchase/suppliers/").status_code, 403)

    def test_writing_a_master_is_still_refused(self):
        self.assertEqual(
            self.client.post("/api/v1/broiler/branches/", {}, format="json")
            .status_code, 403)


class MasterReferenceScopeTests(TestCase):
    """Opening the read must not open the rows."""

    def setUp(self):
        region = Region.objects.create(description="East")
        self.akbarpur = Branch.objects.create(branch_name="Akbarpur",
                                              region=region, prefix="AKB")
        self.tulsipur = Branch.objects.create(branch_name="Tulsipur",
                                              region=region, prefix="TUL")
        self.user = get_user_model().objects.create_user("rahul", password="x")
        employee = Employee.objects.create(full_name="Rahul Singh",
                                           user=self.user)
        profile = EmployeeAccessProfile.objects.create(employee=employee,
                                                       all_branches=False)
        profile.branches.set([self.akbarpur])
        self.client.force_login(self.user)

    def names(self):
        return [b["branch_name"]
                for b in self.client.get(reverse("branch_list")).json()]

    def test_the_feed_offers_only_the_branches_in_scope(self):
        # It returned every branch to everyone, so a user limited to Akbarpur
        # was still offered the rest — the restriction was in the profile and
        # nowhere on the screen.
        self.assertEqual(self.names(), ["Akbarpur"])

    def test_an_unscoped_user_still_sees_them_all(self):
        plain = get_user_model().objects.create_user("plain", password="x")
        self.client.force_login(plain)
        self.assertEqual(sorted(self.names()), ["Akbarpur", "Tulsipur"])
