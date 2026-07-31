"""The v1 API is held to the same matrix and the same data scope as the web app.

Before this it authenticated but never authorised: any valid token could write
to every module regardless of the group matrix governing the same data.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TestCase

from broiler.models import Branch, Farmer, Region, Supervisor, BroilerFarm
from inventory.models import Item, ItemCategory
from user.models import GroupAccessProfile, GroupTabPermission


class ApiMatrixPermissionTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.clerk = User.objects.create_user("api_clerk", "a@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Item Readers")
        self.clerk.groups.add(self.group)
        # View only, on Items alone.
        GroupTabPermission.objects.create(group=self.group, tab_code="items",
                                          can_view=True)

        self.category = ItemCategory.objects.create(name="Feed")
        self.item = Item.objects.create(
            description="Pre Starter", category=self.category,
            valuation_method="Weighted Average", standard_cost_per_unit=50,
            usage="Produced", source="Purchased", type="Raw Material",
            item_account="Expense")
        self.client.force_login(self.clerk)

    def test_a_permitted_resource_can_be_read(self):
        response = self.client.get("/api/v1/inventory/items/")
        self.assertEqual(response.status_code, 200)

    def test_a_forbidden_resource_is_refused(self):
        """Suppliers belong to a tab this group has no rights on."""
        response = self.client.get("/api/v1/purchase/suppliers/")
        self.assertEqual(response.status_code, 403)

    def test_view_rights_do_not_grant_writes(self):
        """The reported hole: any token could write anywhere."""
        response = self.client.post("/api/v1/inventory/items/",
                                    {"description": "Sneaked In",
                                     "category": self.category.id},
                                    content_type="application/json")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Item.objects.filter(description="Sneaked In").exists())

    def test_add_rights_allow_a_write(self):
        """On a writable resource — /inventory/items/ is read-only, so a POST
        there is 405 whatever the matrix says."""
        GroupTabPermission.objects.create(group=self.group, tab_code="region",
                                          can_view=True, can_add=True)
        response = self.client.post("/api/v1/broiler/regions/",
                                    {"description": "Allowed In"},
                                    content_type="application/json")
        self.assertIn(response.status_code, (200, 201), response.content[:200])

    def test_the_same_write_without_the_add_right_is_refused(self):
        GroupTabPermission.objects.create(group=self.group, tab_code="region",
                                          can_view=True)
        response = self.client.post("/api/v1/broiler/regions/",
                                    {"description": "Sneaked In"},
                                    content_type="application/json")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Region.objects.filter(description="Sneaked In").exists())

    def test_delete_needs_its_own_right(self):
        """Edit is not delete — the matrix keeps them apart and so must this."""
        GroupTabPermission.objects.create(group=self.group, tab_code="region",
                                          can_view=True, can_edit=True)
        region = Region.objects.create(description="Doomed")
        response = self.client.delete(f"/api/v1/broiler/regions/{region.id}/")
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Region.objects.filter(id=region.id).exists())

    def test_a_superuser_is_unaffected(self):
        User = get_user_model()
        boss = User.objects.create_superuser("api_boss", "b@x.com", "Str0ngPass!")
        self.client.force_login(boss)
        self.assertEqual(
            self.client.get("/api/v1/purchase/suppliers/").status_code, 200)

    def test_an_unmapped_resource_is_recorded_not_refused(self):
        """Same policy as the middleware: filling the map in blind would break
        the mobile client for endpoints nobody has claimed."""
        from api.permissions import MODEL_TABS
        from user.models import WebAccessAudit

        self.assertNotIn("hatchery.Hatchery", MODEL_TABS)
        response = self.client.get("/api/v1/hatchery/hatcheries/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(WebAccessAudit.objects.filter(
            verdict="unmapped", url_name__startswith="api:").exists())

    def test_every_mapped_tab_code_is_real(self):
        """A wrong entry refuses a request the web app allows, which is worse
        than an unmapped one."""
        from api.permissions import MODEL_TABS
        from user.access import ALL_TAB_CODES

        for key, tab in MODEL_TABS.items():
            with self.subTest(model=key):
                self.assertIn(tab, ALL_TAB_CODES)


class ApiScopingTests(TestCase):
    """A token must not be a way round the data scope either."""

    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.user = User.objects.create_user("api_scope", "s@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Akbarpur API")
        self.user.groups.add(self.group)
        GroupTabPermission.objects.create(group=self.group, tab_code="branch_farm",
                                          can_view=True)
        GroupTabPermission.objects.create(group=self.group,
                                          tab_code="branch_template", can_view=True)

        region = Region.objects.create(description="East")
        self.mine = Branch.objects.create(branch_name="Akbarpur", region=region,
                                          prefix="AKB")
        self.theirs = Branch.objects.create(branch_name="Bahraich", region=region,
                                            prefix="BHR")
        farmer = Farmer.objects.create(farmer_name="F")
        for branch, name in ((self.mine, "MineFarm"), (self.theirs, "TheirFarm")):
            supervisor = Supervisor.objects.create(branch=branch, name=f"S{name}")
            BroilerFarm.objects.create(branch=branch, supervisor=supervisor,
                                       farmer=farmer, region=region, line="L1",
                                       farm_name=name, farm_capacity=100)

        profile = GroupAccessProfile.objects.create(group=self.group,
                                                    all_branches=False)
        profile.branches.add(self.mine)
        self.client.force_login(self.user)

    def test_the_farm_list_is_scoped(self):
        body = self.client.get("/api/v1/broiler/farms/").content.decode()
        self.assertIn("MineFarm", body)
        self.assertNotIn("TheirFarm", body)

    def test_the_branch_list_is_scoped(self):
        body = self.client.get("/api/v1/broiler/branches/").content.decode()
        self.assertIn("Akbarpur", body)
        self.assertNotIn("Bahraich", body)

    def test_an_out_of_scope_row_cannot_be_fetched_by_id(self):
        theirs = BroilerFarm.objects.get(farm_name="TheirFarm")
        response = self.client.get(f"/api/v1/broiler/farms/{theirs.id}/")
        self.assertEqual(response.status_code, 404)

    def test_an_unscoped_user_sees_everything(self):
        User = get_user_model()
        boss = User.objects.create_superuser("api_sboss", "sb@x.com", "Str0ngPass!")
        self.client.force_login(boss)
        body = self.client.get("/api/v1/broiler/farms/").content.decode()
        self.assertIn("MineFarm", body)
        self.assertIn("TheirFarm", body)
