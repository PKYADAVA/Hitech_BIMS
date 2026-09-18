"""Growing Charges list: the Branch filter and the Year options.

The list filtered by date alone, so one branch's settlements in a busy month
meant reading past every other branch's. The page now sends ?branch= like the
other registers, and offers years from the first settlement to this one.
"""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from broiler.models import (Branch, BroilerBatch, BroilerFarm, Farmer,
                            GrowingChargeSettlement, Region, Supervisor)


class GCListFilterTests(TestCase):

    def setUp(self):
        region = Region.objects.create(description="East")
        self.akbarpur = Branch.objects.create(branch_name="Akbarpur", region=region, prefix="AKB")
        self.basti = Branch.objects.create(branch_name="Basti", region=region, prefix="BST")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.gc_date = date(2024, 3, 15)
        for branch, name in ((self.akbarpur, "Green Valley Farm"), (self.basti, "Maa Durga Farm")):
            farm = BroilerFarm.objects.create(
                branch=branch, supervisor=Supervisor.objects.create(branch=branch, name="R. Verma"),
                farmer=farmer, region="East", line="L1", farm_name=name, farm_capacity=9000)
            batch = BroilerBatch.objects.create(broiler_farm=farm,
                                                start_date=self.gc_date - timedelta(days=40))
            GrowingChargeSettlement.objects.create(batch=batch, farm=farm, gc_date=self.gc_date)
        self.client.force_login(get_user_model().objects.create_superuser(
            "gcadmin", "g@x.com", "Str0ngPass!"))

    def farms(self, **params):
        rows = self.client.get("/gc_settlement_list/", params).json()
        return sorted(r["farm_name"] for r in rows)

    def test_no_branch_lists_every_branch(self):
        self.assertEqual(self.farms(), ["Green Valley Farm", "Maa Durga Farm"])

    def test_a_branch_lists_only_its_own_settlements(self):
        self.assertEqual(self.farms(branch=self.basti.id), ["Maa Durga Farm"])

    def test_branch_combines_with_the_dates(self):
        self.assertEqual(self.farms(branch=self.akbarpur.id,
                                    from_date="2024-03-01", to_date="2024-03-31"),
                         ["Green Valley Farm"])
        self.assertEqual(self.farms(branch=self.akbarpur.id,
                                    from_date="2024-04-01", to_date="2024-04-30"), [])

    def test_the_page_offers_branches_and_years_from_the_first_settlement(self):
        html = self.client.get("/gc-settlement/").content.decode()
        self.assertIn('id="flt-branch"', html)
        self.assertIn(">Basti</option>", html)
        this_year = timezone.localdate().year
        for year in range(2024, this_year + 1):
            self.assertIn('<option value="%d">%d</option>' % (year, year), html)
        self.assertNotIn('<option value="2023">', html)


class GCListScopeTests(GCListFilterTests):
    """A user limited to Akbarpur sees Akbarpur's settlements and no others —
    in the list under "All Branches", and by id on every route that takes one."""

    def setUp(self):
        super().setUp()
        from django.contrib.auth.models import Group
        from user.models import GroupAccessProfile, GroupTabPermission

        user = get_user_model().objects.create_user("gcscoped", "s@x.com", "Str0ngPass!")
        group = Group.objects.create(name="Akbarpur Team")
        user.groups.add(group)
        GroupTabPermission.objects.create(group=group, tab_code="gc_settlement", can_view=True,
                                          can_add=True, can_edit=True, can_delete=True)
        profile = GroupAccessProfile.objects.create(group=group, access_type="sub_admin",
                                                    all_branches=False, all_farms=False)
        profile.branches.add(self.akbarpur)
        profile.farms.add(*BroilerFarm.objects.filter(branch=self.akbarpur))
        self.client.force_login(user)
        self.other = GrowingChargeSettlement.objects.get(farm__branch=self.basti)

    def test_no_branch_lists_every_branch(self):
        # Every branch *this user may see*: Basti's settlement stays out.
        self.assertEqual(self.farms(), ["Green Valley Farm"])

    def test_a_branch_lists_only_its_own_settlements(self):
        self.assertEqual(self.farms(branch=self.basti.id), [])

    def test_the_page_offers_branches_and_years_from_the_first_settlement(self):
        html = self.client.get("/gc-settlement/").content.decode()
        self.assertIn(">Akbarpur</option>", html)
        self.assertNotIn(">Basti</option>", html)

    def test_another_branchs_settlement_is_not_found_by_id(self):
        base = "/gc_settlement/%d/" % self.other.id
        self.assertEqual(self.client.get(base).status_code, 404)
        self.assertEqual(self.client.get(base + "print/").status_code, 404)
        self.assertEqual(self.client.get(base + "recalculate/").status_code, 404)
        self.assertEqual(self.client.put(base, "{}", content_type="application/json").status_code, 404)
        self.assertEqual(self.client.delete(base + "delete/").status_code, 404)
        self.assertTrue(GrowingChargeSettlement.objects.filter(id=self.other.id).exists())
