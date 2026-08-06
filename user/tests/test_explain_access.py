"""The diagnostic that says why a scoped user's lists are empty.

Two causes look identical from the phone — a blank list either way — and the
fix for each is the opposite of the other. One is a group configured to permit
nothing; the other is a group configured correctly whose rows have no branch or
no warehouse recorded on them, which `scope_multi` drops because `field__in`
does not match NULL.

Telling them apart by eye is not possible, and loosening the wrong one widens
access for everybody. These check the command names the right one.
"""
from datetime import date

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase

from broiler.models import Branch, BroilerFarm, Farmer, Region, Supervisor
from inventory.models import Warehouse
from user.models import GroupAccessProfile


def run(*args):
    from io import StringIO

    out = StringIO()
    call_command("explain_access", *args, stdout=out)
    return out.getvalue()


class ExplainAccessTests(TestCase):
    def setUp(self):
        self.region = Region.objects.create(description="East")
        self.branch = Branch.objects.create(branch_name="Akbarpur", region=self.region,
                                            prefix="AKB")
        self.other = Branch.objects.create(branch_name="Bahraich", region=self.region,
                                           prefix="BHR")
        self.warehouse = Warehouse.objects.create(name="Akbarpur Store")
        self.supervisor = Supervisor.objects.create(branch=self.branch, name="R. Verma")
        self.farmer = Farmer.objects.create(farmer_name="S. Yadav")

    def farm(self, name, branch):
        return BroilerFarm.objects.create(
            branch=branch, supervisor=self.supervisor, farmer=self.farmer,
            region=self.region, line="L1", farm_name=name, farm_capacity=5000)

    def scoped_user(self, name, **profile):
        from user.services.scoping import SCOPES

        group = Group.objects.create(name=name)
        p = GroupAccessProfile.objects.create(group=group)
        for key, value in profile.items():
            if key not in SCOPES:                 # the all_* flags, set directly
                setattr(p, key, value)
        p.save()
        for key in SCOPES:                        # the m2m sets, after the save
            if key in profile:
                getattr(p, key).set(profile[key])
        user = User.objects.create_user(name, f"{name}@x.com", "Str0ngPass!")
        user.groups.add(group)
        return user

    # ---- no scoping at all --------------------------------------------------

    def test_an_unscoped_user_is_told_scoping_is_not_the_cause(self):
        admin = User.objects.create_superuser("boss", "b@x.com", "Str0ngPass!")
        out = run(admin.username)
        self.assertIn("Not scoped at all", out)

    def test_an_unknown_user_is_refused_rather_than_reported_on(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            run("nobody-by-that-name")

    # ---- cause 1: the group permits nothing ---------------------------------

    def test_a_scope_with_nothing_chosen_is_called_out(self):
        """'All' off with no rows picked means nothing, not 'everything'. It is
        the easiest thing to do by accident in the editor."""
        user = self.scoped_user("empty_scope", all_farms=False)
        out = run(user.username)
        self.assertIn("NOTHING", out)
        self.assertIn("permits nothing", out)
        # And it says where to go and fix it.
        self.assertIn("Data Scope", out)

    def test_a_populated_scope_is_not_called_out(self):
        user = self.scoped_user("ok_scope", all_branches=False, branches=[self.branch])
        out = run(user.username)
        self.assertNotIn("NOTHING", out)
        self.assertIn("1 selected", out)

    # ---- cause 2: the rows have no branch on them ---------------------------

    def test_hidden_rows_are_counted(self):
        """A row in somebody else's group is genuinely restricted, and the
        report says how many."""
        from sales.models import Customer, CustomerGroup

        grp = CustomerGroup.objects.create(code="G1", description="Traders")
        other = CustomerGroup.objects.create(code="G2", description="Retail")
        Customer.objects.create(name="In Group", customer_group=grp,
                                phone="9000000001", mobile="9100000001")
        Customer.objects.create(name="Their Group", customer_group=other,
                                phone="9000000002", mobile="9100000002")

        user = self.scoped_user("group_only", all_customer_groups=False,
                                customer_groups=[grp])
        out = run(user.username, "--resource", "sales.Customer")
        self.assertIn("sales.Customer", out)
        self.assertIn("1 hidden", out)

    def test_a_row_with_no_group_is_not_hidden_at_all(self):
        """`nulls: keep` — an ungrouped customer is unassigned, not somebody
        else's, so it stays in the picker rather than vanishing for everyone."""
        from sales.models import Customer, CustomerGroup

        grp = CustomerGroup.objects.create(code="G1", description="Traders")
        Customer.objects.create(name="In Group", customer_group=grp,
                                phone="9000000003", mobile="9100000003")
        Customer.objects.create(name="No Group At All",
                                phone="9000000004", mobile="9100000004")

        user = self.scoped_user("group_keep", all_customer_groups=False,
                                customer_groups=[grp])
        out = run(user.username, "--resource", "sales.Customer")
        row = [ln for ln in out.splitlines() if "sales.Customer" in ln][0]
        self.assertNotIn("hidden", row)

    def test_a_scope_left_on_all_is_not_blamed_for_nulls(self):
        """A dimension nobody limited filters nothing, so a null in it hides
        nothing — reporting it would send the admin after the wrong column."""
        from sales.models import Customer

        Customer.objects.create(name="No Group At All", phone="9000000009", mobile="9100000009")
        user = self.scoped_user("unlimited", all_sectors=False, sectors=[self.warehouse])
        out = run(user.username, "--resource", "sales.Customer")
        self.assertNotIn("customer_group_id is empty", out)

    def test_the_resource_filter_narrows_the_report(self):
        user = self.scoped_user("narrow", all_branches=False, branches=[self.branch])
        out = run(user.username, "--resource", "Warehouse")
        self.assertIn("inventory.Warehouse", out)
        self.assertNotIn("broiler.DailyEntry", out)

    # ---- the counts themselves ---------------------------------------------

    def test_visible_and_total_are_reported_per_model(self):
        self.farm("In Branch", self.branch)
        self.farm("Other Branch", self.other)
        user = self.scoped_user("counts", all_branches=False, branches=[self.branch])
        out = run(user.username, "--resource", "broiler.BroilerFarm")
        # One of two farms visible; the header and the row both present.
        self.assertIn("visible", out)
        row = [ln for ln in out.splitlines() if "broiler.BroilerFarm" in ln][0]
        self.assertIn(" 1 ", row)
        self.assertIn(" 2 ", row)


class NullScopedRowsTests(TestCase):
    """Rows whose scope column is empty stay visible under a scope.

    Only three scoped columns are nullable at all — an employee's warehouse
    (via trips and vehicles) and a customer's group. Before `nulls: keep`,
    applying any scope made those rows invisible to every scoped user at once:
    not restricted to somebody, unreachable by anybody, which is how a
    correctly-configured group ends up with empty lists.
    """

    def setUp(self):
        from inventory.models import Warehouse

        self.w1 = Warehouse.objects.create(name="Akbarpur Store")
        self.w2 = Warehouse.objects.create(name="Bahraich Store")

    def scoped_user(self, name, **profile):
        from user.services.scoping import SCOPES

        group = Group.objects.create(name=name)
        p = GroupAccessProfile.objects.create(group=group)
        for key, value in profile.items():
            if key not in SCOPES:
                setattr(p, key, value)
        p.save()
        for key in SCOPES:
            if key in profile:
                getattr(p, key).set(profile[key])
        user = User.objects.create_user(name, f"{name}@x.com", "Str0ngPass!")
        user.groups.add(group)
        return user

    def visible(self, user, model):
        from api.viewsets import scope_api_queryset

        return set(scope_api_queryset(user, model.objects.all())
                   .values_list("id", flat=True))

    def test_a_customer_with_no_group_stays_visible(self):
        from sales.models import Customer, CustomerGroup

        grp = CustomerGroup.objects.create(code="G1", description="Traders")
        other = CustomerGroup.objects.create(code="G2", description="Retail")
        mine = Customer.objects.create(name="In My Group", customer_group=grp,
                                       phone="9000000011", mobile="9100000011")
        theirs = Customer.objects.create(name="In Their Group", customer_group=other,
                                         phone="9000000012", mobile="9100000012")
        ungrouped = Customer.objects.create(name="No Group", phone="9000000013",
                                            mobile="9100000013")

        user = self.scoped_user("cust", all_customer_groups=False, customer_groups=[grp])
        seen = self.visible(user, Customer)
        self.assertIn(mine.id, seen)
        self.assertIn(ungrouped.id, seen)          # the fix
        self.assertNotIn(theirs.id, seen)          # still restricted

    def test_a_trip_by_an_employee_with_no_warehouse_stays_visible(self):
        from hr.models import Employee, SupervisorTrip

        mine = Employee.objects.create(full_name="In My Store", warehouse=self.w1)
        theirs = Employee.objects.create(full_name="In Their Store", warehouse=self.w2)
        nowhere = Employee.objects.create(full_name="No Store Recorded")

        t1 = SupervisorTrip.objects.create(employee=mine, date=date(2026, 8, 1))
        t2 = SupervisorTrip.objects.create(employee=theirs, date=date(2026, 8, 1))
        t3 = SupervisorTrip.objects.create(employee=nowhere, date=date(2026, 8, 1))

        user = self.scoped_user("trips", all_sectors=False, sectors=[self.w1])
        seen = self.visible(user, SupervisorTrip)
        self.assertIn(t1.id, seen)
        self.assertIn(t3.id, seen)                 # the fix
        self.assertNotIn(t2.id, seen)              # still restricted

    def test_an_unscoped_user_still_sees_everything(self):
        from sales.models import Customer

        Customer.objects.create(name="No Group", phone="9000000021", mobile="9100000021")
        admin = User.objects.create_superuser("boss2", "b2@x.com", "Str0ngPass!")
        self.assertEqual(len(self.visible(admin, Customer)), Customer.objects.count())


class AppReportTests(TestCase):
    """`--app`: which phone tabs a user is served, and what closed the rest.

    Scoping decides which rows reach a screen; two gates in front of it decide
    whether the screen appears at all — the web tab matrix, and Mobile Access
    on top. A tab missing from the app and a tab full of nothing look identical
    to whoever reports it, so the report has to name the gate.
    """

    def setUp(self):
        self.admin = User.objects.create_superuser("appboss", "ab@x.com", "Str0ngPass!")

    def test_an_unrestricted_user_is_served_every_screen(self):
        out = run(self.admin.username, "--app")
        self.assertIn("Phone modules for", out)
        self.assertIn("every phone screen is available", out)

    def test_a_tab_the_matrix_withholds_is_named_with_its_reason(self):
        """The commonest cause, and the one mistaken for a removed feature."""
        from user.models import GroupTabPermission
        from user.services.mobile_access import PHONE_SCREENS

        group = Group.objects.create(name="Partial")
        # Grant every phone tab except one, so exactly one is withheld.
        withheld = PHONE_SCREENS[0][1]
        for _key, tab in PHONE_SCREENS:
            if tab == withheld:
                continue
            GroupTabPermission.objects.create(group=group, tab_code=tab, can_view=True)
        member = User.objects.create_user("partial", "p@x.com", "Str0ngPass!")
        member.groups.add(group)

        out = run(member.username, "--app")
        self.assertIn(PHONE_SCREENS[0][0], out)
        self.assertIn("the web matrix does not grant View on this tab", out)

    def test_a_module_switched_off_for_the_phone_is_reported_as_such(self):
        """Mobile Access can only narrow what the matrix allows, so a module
        off here is a different fix from a tab off in the matrix."""
        from user.models import GroupMobileAccess, GroupTabPermission
        from user.services.mobile_access import PHONE_SCREENS

        group = Group.objects.create(name="PhoneLimited")
        for _key, tab in PHONE_SCREENS:
            GroupTabPermission.objects.create(group=group, tab_code=tab, can_view=True)
        # Mobile Access is per-module and fails open: a module with no row is
        # unaffected. Switching one *off* is what narrows.
        GroupMobileAccess.objects.create(group=group, module_key="hatchery", enabled=False)
        member = User.objects.create_user("phoned", "ph@x.com", "Str0ngPass!")
        member.groups.add(group)

        out = run(member.username, "--app")
        self.assertIn("hidden by Mobile Access: hatchery", out)
        self.assertIn("Mobile Access has the hatchery module switched off", out)

    def test_the_app_report_runs_for_a_user_with_no_scoping(self):
        """It answers a different question from the scopes below it, so it must
        not be skipped by the unscoped early return."""
        out = run(self.admin.username, "--app")
        self.assertIn("Phone screens", out)
        self.assertIn("Not scoped at all", out)

    def test_without_the_flag_nothing_phone_related_is_printed(self):
        out = run(self.admin.username)
        self.assertNotIn("Phone modules", out)
