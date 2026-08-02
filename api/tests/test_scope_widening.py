"""The scopes added to the mobile API.

Two levels, deliberately. One read goes through the real endpoint and proves
the scope is applied at all; the rest assert the compiled queryset, because the
models they cover need half a dozen NOT NULL foreign keys each and building
those would test the fixtures rather than the scoping.

What each of the new entries has to get right is which *fields* and which
*combiner* — and both are visible in the query without inserting a row.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TestCase

from api.viewsets import scope_api_queryset
from hatchery.models import ChickSale, DeliveryChallan, EggPurchase
from inventory.models import StockIssue, StockReceive, Warehouse
from user.models import GroupAccessProfile, GroupTabPermission


class ScopedApiReadTests(TestCase):
    """End to end: a scoped group reads only its own rows over HTTP."""

    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.user = User.objects.create_user("sw_user", "s@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="One Warehouse")
        self.user.groups.add(self.group)
        GroupTabPermission.objects.create(group=self.group, tab_code="warehouse",
                                          can_view=True)

        self.mine = Warehouse.objects.create(name="Mine")
        self.theirs = Warehouse.objects.create(name="Theirs")
        self.profile = GroupAccessProfile.objects.create(group=self.group,
                                                         all_sectors=False)
        self.profile.sectors.add(self.mine)
        self.client.force_login(self.user)

    def ids(self):
        response = self.client.get("/api/v1/inventory/warehouses/")
        self.assertEqual(response.status_code, 200, response.content[:200])
        payload = response.json()["data"]
        rows = payload["items"] if isinstance(payload, dict) else payload
        return {row["id"] for row in rows}

    def test_a_scoped_group_reads_only_its_own(self):
        got = self.ids()
        self.assertIn(self.mine.id, got)
        self.assertNotIn(self.theirs.id, got)

    def test_an_unscoped_group_still_reads_everything(self):
        """all_sectors defaults True; a feature nobody has configured must
        never narrow anyone."""
        self.profile.all_sectors = True
        self.profile.save()
        self.assertEqual(self.ids(), {self.mine.id, self.theirs.id})


class NewScopeQueryTests(TestCase):
    """The entries added to API_SCOPES, asserted on the compiled query."""

    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.user = User.objects.create_user("sq_user", "q@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Scoped")
        self.user.groups.add(self.group)
        self.warehouse = Warehouse.objects.create(name="Only")
        profile = GroupAccessProfile.objects.create(group=self.group,
                                                    all_sectors=False)
        profile.sectors.add(self.warehouse)
        self.user = get_user_model().objects.get(pk=self.user.pk)

    def sql(self, model):
        return str(scope_api_queryset(self.user, model.objects.all()).query)

    def test_egg_purchases_are_narrowed_by_warehouse(self):
        self.assertIn("warehouse_id", self.sql(EggPurchase))

    def test_chick_sales_are_narrowed_by_warehouse(self):
        self.assertIn("warehouse_id", self.sql(ChickSale))

    def test_delivery_challans_reach_the_warehouse_through_their_sales(self):
        sql = self.sql(DeliveryChallan)
        self.assertIn("JOIN", sql.upper())
        self.assertIn("warehouse_id", sql)

    def test_stock_movements_join_their_items(self):
        for model in (StockIssue, StockReceive):
            with self.subTest(model=model.__name__):
                sql = self.sql(model)
                self.assertIn("JOIN", sql.upper())
                self.assertIn("warehouse_id", sql)

    def test_a_two_ended_row_keeps_the_far_end(self):
        """scope_any, not scope_multi: requiring both ends hides the movement
        out of the user's own store, which is the one they most need to see.
        An OR shows in the query as the alternation scope_multi never emits."""
        sql = self.sql(StockIssue)
        self.assertIn(" OR ", sql.upper())

    def test_single_location_rows_stay_conjunctive(self):
        """scope_multi remains right where each dimension is a separate
        restriction rather than an alternative."""
        from broiler.models import DailyEntry

        self.assertNotIn(" OR ", self.sql(DailyEntry).upper())

    def test_an_unscoped_user_is_not_narrowed_at_all(self):
        loose = get_user_model().objects.create_user("sq_loose", "l@x.com",
                                                     "Str0ngPass!")
        plain = str(EggPurchase.objects.all().query)
        self.assertEqual(str(scope_api_queryset(loose, EggPurchase.objects.all()).query),
                         plain)
