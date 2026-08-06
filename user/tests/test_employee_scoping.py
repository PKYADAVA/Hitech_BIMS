"""An employee's own data scope, and how it stands against their group's.

The rule under test: where an active profile exists it *replaces* the group
scope. Two people can share a role and not a territory, and no arrangement of
groups says that without inventing a group per person — so where an
administrator has answered for the person, that is the answer.

The other half matters just as much: an employee with no profile, or with one
switched off, must be scoped exactly as they are today. Adding this page cannot
be allowed to change what anybody already sees.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase

from broiler.models import Branch, BroilerFarm, Farmer, Region, Supervisor
from hr.models import Employee
from inventory.models import Mapping, Warehouse
from user.models import EmployeeAccessProfile, GroupAccessProfile
from user.services.scoping import allowed_ids, farms_for, is_unscoped


class EmployeeScopeTests(TestCase):
    def setUp(self):
        region = Region.objects.create(description="East")
        self.akbarpur = Branch.objects.create(branch_name="Akbarpur",
                                              region=region, prefix="AKB")
        self.tulsipur = Branch.objects.create(branch_name="Tulsipur",
                                              region=region, prefix="TUL")
        self.lucknow = Branch.objects.create(branch_name="Lucknow",
                                             region=region, prefix="LKO")
        supervisor = Supervisor.objects.create(branch=self.akbarpur, name="R. V.")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")

        def farm(name, branch):
            return BroilerFarm.objects.create(
                branch=branch, supervisor=supervisor, farmer=farmer,
                region=region, line="L1", farm_name=name, farm_capacity=1000)

        self.akb_farm = farm("Akbarpur Farm", self.akbarpur)
        self.tul_farm = farm("Tulsipur Farm", self.tulsipur)
        self.lko_farm = farm("Lucknow Farm", self.lucknow)

        self.akb_store = Warehouse.objects.create(name="Akbarpur Feed Store")
        self.tul_store = Warehouse.objects.create(name="Tulsipur Feed Store")
        self.orphan_store = Warehouse.objects.create(name="Central Warehouse")
        for store, branch in ((self.akb_store, self.akbarpur),
                              (self.tul_store, self.tulsipur)):
            Mapping.objects.create(type=Mapping.TYPE_SECTOR_BRANCH,
                                   from_id=store.id, to_id=branch.id)

        User = get_user_model()
        self.user = User.objects.create_user("rahul", password="x")
        self.employee = Employee.objects.create(full_name="Rahul Singh",
                                                user=self.user)

    def profile(self, **kw):
        branches = kw.pop("branches", None)
        farms = kw.pop("farms", None)
        warehouses = kw.pop("warehouses", None)
        p = EmployeeAccessProfile.objects.create(employee=self.employee, **kw)
        if branches is not None:
            p.branches.set(branches)
        if farms is not None:
            p.farms.set(farms)
        if warehouses is not None:
            p.warehouses.set(warehouses)
        return p

    def group_scoped_to(self, *branches):
        group = Group.objects.create(name="Branch Managers")
        self.user.groups.add(group)
        gp = GroupAccessProfile.objects.create(group=group, all_branches=False)
        gp.branches.set(branches)
        return gp

    # --- nothing changes until a profile exists -------------------------

    def test_without_a_profile_the_group_scope_still_rules(self):
        self.group_scoped_to(self.akbarpur)
        self.assertEqual(allowed_ids(self.user, "branches"), {self.akbarpur.id})

    def test_an_inactive_profile_scopes_nobody(self):
        # Switched off rather than deleted, so a scope can be lifted for a week
        # without losing what it was.
        self.group_scoped_to(self.akbarpur)
        self.profile(is_active=False, all_branches=False,
                     branches=[self.tulsipur])
        self.assertEqual(allowed_ids(self.user, "branches"), {self.akbarpur.id})

    def test_a_login_with_neither_is_unscoped(self):
        self.assertTrue(is_unscoped(self.user))
        self.assertIsNone(allowed_ids(self.user, "branches"))

    # --- the profile replaces the group scope ---------------------------

    def test_the_profile_widens_where_the_group_was_narrower(self):
        self.group_scoped_to(self.akbarpur)
        self.profile(all_branches=False, branches=[self.akbarpur, self.tulsipur])
        self.assertEqual(allowed_ids(self.user, "branches"),
                         {self.akbarpur.id, self.tulsipur.id})

    def test_the_profile_narrows_where_the_group_was_wider(self):
        group = Group.objects.create(name="Everyone")
        self.user.groups.add(group)
        GroupAccessProfile.objects.create(group=group)      # all_branches=True
        self.profile(all_branches=False, branches=[self.tulsipur])
        self.assertEqual(allowed_ids(self.user, "branches"), {self.tulsipur.id})

    def test_choosing_nothing_permits_nothing(self):
        # An empty set is a real answer and must not collapse into "no limit".
        self.profile(all_branches=False, branches=[])
        self.assertEqual(allowed_ids(self.user, "branches"), set())

    # --- the cascade ----------------------------------------------------

    def test_all_farms_means_all_farms_of_the_chosen_branches(self):
        self.profile(all_branches=False, branches=[self.akbarpur, self.tulsipur])
        self.assertEqual(allowed_ids(self.user, "farms"),
                         {self.akb_farm.id, self.tul_farm.id})

    def test_all_warehouses_follows_the_branches_through_office_mapping(self):
        self.profile(all_branches=False, branches=[self.akbarpur])
        self.assertEqual(allowed_ids(self.user, "sectors"), {self.akb_store.id})

    def test_an_unmapped_warehouse_belongs_to_no_branch(self):
        self.profile(all_branches=False, branches=[self.akbarpur, self.tulsipur])
        self.assertNotIn(self.orphan_store.id, allowed_ids(self.user, "sectors"))

    def test_all_of_everything_is_no_limit_at_all(self):
        self.profile()
        for scope in ("branches", "farms", "sectors"):
            self.assertIsNone(allowed_ids(self.user, scope), scope)

    def test_an_explicit_list_beats_the_cascade(self):
        # Farms named outright are the answer, even ones outside the branches.
        self.profile(all_branches=False, branches=[self.akbarpur],
                     all_farms=False, farms=[self.tul_farm])
        self.assertEqual(allowed_ids(self.user, "farms"), {self.tul_farm.id})

    def test_a_dimension_this_page_does_not_cover_is_unrestricted(self):
        # The profile replaces the group scope wholesale, and says nothing
        # about lines — so they are unrestricted, not empty.
        group = Group.objects.create(name="Line Limited")
        self.user.groups.add(group)
        gp = GroupAccessProfile.objects.create(group=group, all_lines=False)
        gp.lines.set([])
        self.profile(all_branches=False, branches=[self.akbarpur])
        self.assertIsNone(allowed_ids(self.user, "lines"))

    # --- and it reaches the querysets people actually read ---------------

    def test_the_farm_picker_narrows_to_the_branches_in_scope(self):
        self.profile(all_branches=False, branches=[self.tulsipur])
        self.assertEqual(list(farms_for(self.user).values_list("id", flat=True)),
                         [self.tul_farm.id])

    def test_a_named_warehouse_outside_the_branches_is_not_stored(self):
        # The picker hides it; this is the rule the picker is only the front of.
        from user.views import _drop_out_of_scope

        p = self.profile(all_branches=False, branches=[self.akbarpur],
                         all_warehouses=False,
                         warehouses=[self.akb_store, self.tul_store,
                                     self.orphan_store])
        _drop_out_of_scope(p)
        self.assertEqual(set(p.warehouses.values_list("id", flat=True)),
                         {self.akb_store.id})

    def test_a_named_farm_outside_the_branches_is_not_stored(self):
        from user.views import _drop_out_of_scope

        p = self.profile(all_branches=False, branches=[self.akbarpur],
                         all_farms=False, farms=[self.akb_farm, self.lko_farm])
        _drop_out_of_scope(p)
        self.assertEqual(set(p.farms.values_list("id", flat=True)),
                         {self.akb_farm.id})

    def test_nothing_is_pruned_when_branches_are_unrestricted(self):
        from user.views import _drop_out_of_scope

        p = self.profile(all_farms=False, farms=[self.akb_farm, self.lko_farm])
        _drop_out_of_scope(p)
        self.assertEqual(p.farms.count(), 2)

    def test_a_superuser_is_never_scoped_by_it(self):
        boss = get_user_model().objects.create_superuser("boss", password="x")
        Employee.objects.create(full_name="The Boss", user=boss)
        EmployeeAccessProfile.objects.create(
            employee=Employee.objects.get(full_name="The Boss"),
            all_branches=False)
        self.assertIsNone(allowed_ids(boss, "branches"))
