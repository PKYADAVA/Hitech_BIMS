"""Telling a chicks placement from a feed dispatch.

Both are a stock transfer onto a farm — the same model, the same destination —
and the only thing separating them is what is being moved. The phone's Chicks
Placement tab asked for farm-bound transfers and got the farm's feed as well,
because the destination alone was never enough to answer the question.

The rule these pin is the one the web register already applies in the browser:
a placement is a *chick-category* transfer onto a farm. Two conditions, and the
tests here exist so that dropping either one fails rather than quietly widening
the register again.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from broiler.models import Branch, BroilerFarm, BroilerLine, Farmer, Region, Supervisor
from inventory.item_families import chick_items, feed_items, filter_by_item_family
from inventory.models import Item, ItemCategory, StockTransfer, Warehouse

MOBILE_URL = "/api/v1/inventory/stock-transfers/"
WEB_URL = "/stock_transfer_api/"


class TransferFixture(TestCase):
    """One farm, one warehouse, and one movement of each kind onto the farm."""

    def setUp(self):
        self.today = timezone.localdate()
        self.warehouse = Warehouse.objects.create(name="Main Warehouse")

        region = Region.objects.create(code="R1", description="East")
        branch = Branch.objects.create(code="B1", branch_name="Akbarpur", region=region)
        self.farm = BroilerFarm.objects.create(
            farm_name="Akbarpur Farm", branch=branch, region=region,
            supervisor=Supervisor.objects.create(branch=branch, name="S. Kumar"),
            line=BroilerLine.objects.create(description="Line 1", region=region,
                                            branch=branch),
            farmer=Farmer.objects.create(farmer_name="Abhishek Kumar Singh"),
            farm_capacity=5000)

        self.chick = self.item("Day Old Chicks", "Day Old Chicks")
        self.feed = self.item("Pre-Starter Feed", "Broiler Feed")

        self.placement = self.transfer(self.chick, 5000, to_farm=True)
        self.dispatch = self.transfer(self.feed, 40, to_farm=True)
        # A warehouse-to-warehouse feed move, which is neither.
        self.restock = self.transfer(self.feed, 10, to_farm=False)

        self.user = get_user_model().objects.create_superuser(
            "cp_user", "cp@example.com", "Str0ngPass!")
        self.api = APIClient()
        self.api.force_authenticate(self.user)
        self.client.force_login(self.user)

    def item(self, description, category):
        return Item.objects.create(
            description=description,
            category=ItemCategory.objects.create(name=category),
            valuation_method="Weighted Average", standard_cost_per_unit=30,
            usage="Produced", source="Purchased", type="Raw Material",
            item_account="Expense")

    def transfer(self, item, quantity, to_farm):
        return StockTransfer.objects.create(
            item=item, quantity=quantity, rate=30, date=self.today,
            from_location_type="warehouse", from_warehouse=self.warehouse,
            to_location_type="farm" if to_farm else "warehouse",
            to_farm=self.farm if to_farm else None,
            to_warehouse=None if to_farm else self.warehouse)

    def mobile_ids(self, query=""):
        resp = self.api.get(MOBILE_URL + query)
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        body = body.get("data", body)
        rows = body.get("results", body) if isinstance(body, dict) else body
        return {row["id"] for row in rows}

    def web_ids(self, query=""):
        resp = self.client.get(WEB_URL + query)
        self.assertEqual(resp.status_code, 200, resp.content)
        return {row["id"] for row in resp.json()}


class ItemFamilyTests(TransferFixture):
    """The shared definition both clients now filter through."""

    def test_a_chick_item_is_not_a_feed_item(self):
        """The whole distinction rests on this, and a category named for both
        would collapse it."""
        self.assertEqual(list(chick_items()), [self.chick])
        self.assertEqual(list(feed_items()), [self.feed])

    def test_the_family_is_matched_by_category_name_not_by_id(self):
        """Categories are created by whoever sets up Inventory, so there is no
        fixed id to hold on to — a second site would filter on a number that
        means something else there."""
        other = self.item("Layer Chicks", "Parent Chick Stock")
        self.assertIn(other, list(chick_items()))

    def test_filtering_narrows_to_the_family(self):
        qs = filter_by_item_family(StockTransfer.objects.all(), "chicks")
        self.assertEqual(set(qs), {self.placement})

    def test_an_unknown_family_narrows_to_nothing(self):
        """Failing closed. A filter that silently does not apply is exactly
        how this register came to list feed: the caller asked for chicks and
        was handed everything, with nothing to say so."""
        qs = filter_by_item_family(StockTransfer.objects.all(), "poultry")
        self.assertEqual(list(qs), [])


class MobileChicksPlacementTests(TransferFixture):
    """The register the report was about."""

    def test_the_destination_alone_still_lets_the_farms_feed_through(self):
        """Not a regression guard — the reason the fix is a second condition
        rather than a correction to the first."""
        self.assertEqual(self.mobile_ids("?to_location_type=farm"),
                         {self.placement.id, self.dispatch.id})

    def test_a_placement_is_farm_bound_and_chicks(self):
        self.assertEqual(
            self.mobile_ids("?to_location_type=farm&item_family=chicks"),
            {self.placement.id})

    def test_the_feed_dispatched_to_the_farm_is_not_a_placement(self):
        ids = self.mobile_ids("?to_location_type=farm&item_family=chicks")
        self.assertNotIn(self.dispatch.id, ids)

    def test_the_general_stock_transfer_register_still_lists_everything(self):
        """The filter is opt-in. Narrowing the endpoint itself would have
        emptied the register this one shares a model with."""
        self.assertEqual(self.mobile_ids(),
                         {self.placement.id, self.dispatch.id, self.restock.id})

    def test_the_family_filter_works_on_its_own(self):
        """It is a filter on the resource, not a special case of the
        destination one."""
        self.assertEqual(self.mobile_ids("?item_family=feed"),
                         {self.dispatch.id, self.restock.id})


class WebStockTransferFilterTests(TransferFixture):
    """The web API behind both the Chicks Placement and Stock Transfer pages."""

    def test_a_destination_type_narrows_without_a_particular_destination(self):
        """It used to be ignored unless an id came with it, so a page asking
        for everything farm-bound was handed every transfer there is and left
        to discard the rest in the browser."""
        self.assertEqual(self.web_ids("?to_location_type=farm"),
                         {self.placement.id, self.dispatch.id})

    def test_a_destination_id_still_narrows_further(self):
        self.assertEqual(
            self.web_ids("?to_location_type=farm&to_location_id=%s" % self.farm.id),
            {self.placement.id, self.dispatch.id})

    def test_the_web_can_ask_for_the_same_family(self):
        """Same question, same answer, whichever client is asking."""
        self.assertEqual(
            self.web_ids("?to_location_type=farm&item_family=chicks"),
            {self.placement.id})

    def test_no_filters_still_lists_everything(self):
        self.assertEqual(self.web_ids(),
                         {self.placement.id, self.dispatch.id, self.restock.id})


class MobileCatalogTests(TestCase):
    """The phone's list path is where the two conditions actually meet."""

    def test_the_chicks_placement_tab_asks_for_both(self):
        """A guard on the config rather than the code: the filter exists and
        is correct, and the tab simply has to use it."""
        import os

        catalog = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "mobile", "src", "config", "catalog.ts")
        with open(catalog, encoding="utf-8") as fh:
            source = fh.read()
        entry = source.split('key: "broiler-chicks-placement"')[1].split("},")[0]
        self.assertIn("to_location_type=farm", entry)
        self.assertIn("item_family=chicks", entry)
