"""What order the GC Realization Report puts farms in.

It listed them alphabetically, which is the one order that says nothing: a
flock three days from lifting sat below one placed last week because its
farm's name starts with G. The Production Cost and Live Flock reports already
read oldest-placement-first — the flock nearest its end at the top, where the
decisions are — and a farm should sit in the same place whichever of the three
is open.

Sorting is done in Python rather than in the query because the placement is
not always ``start_date``: a batch created from a chicks placement can have it
blank, and ``_placement_date`` falls back to the transfer that filled it. An
ORDER BY on the column alone would put those wherever NULL happens to land.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from broiler.models import (Branch, BroilerBatch, BroilerFarm, Farmer, Region,
                            Supervisor)
from inventory.models import Item, ItemCategory, StockTransfer, Warehouse


class GcRealizationSortingTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.region = Region.objects.create(description="East")
        self.branch = Branch.objects.create(branch_name="Akbarpur",
                                            region=self.region, prefix="AKB")
        self.sup = Supervisor.objects.create(branch=self.branch, name="R. Verma")
        self.farmer = Farmer.objects.create(farmer_name="S. Yadav")

        chick_cat = ItemCategory.objects.create(name="Day Old Chicks")
        self.chick = Item.objects.create(item_code="CHK-1", description="Day Old Chick",
                                         category=chick_cat, standard_cost_per_unit=35)
        self.store = Warehouse.objects.create(name="Store")

        User = get_user_model()
        self.user = User.objects.create_superuser("gcsort", "gc@x.com", "Str0ngPass!")
        self.client.force_login(self.user)

    # ---- fixtures -----------------------------------------------------------

    def farm(self, name):
        return BroilerFarm.objects.create(
            branch=self.branch, supervisor=self.sup, farmer=self.farmer,
            region=self.region, line="L1", farm_name=name, farm_capacity=9000)

    def batch(self, farm, name, days_ago, *, dated=True, birds=1000):
        """A flock placed `days_ago`. With ``dated=False`` its start_date is
        left blank, the way a batch created from a placement can be."""
        placed = self.today - timedelta(days=days_ago)
        batch = BroilerBatch.objects.create(
            broiler_farm=farm, batch_name=name,
            start_date=placed if dated else None)
        StockTransfer.objects.create(
            date=placed, item=self.chick, quantity=birds,
            purchase_rate=Decimal("35"), rate=Decimal("35"),
            from_location_type="warehouse", from_warehouse=self.store,
            to_location_type="farm", to_farm=farm, to_batch=batch)
        return batch

    def order(self):
        """The batch names the report lists, in the order it lists them."""
        response = self.client.get(reverse("gc_realization_report"),
                                   {"status": "all", "submit": "1"})
        self.assertEqual(response.status_code, 200)
        grid = response.context["grid"]
        return [g["batch_name"] for g in grid["groups"]]

    # ---- the order ----------------------------------------------------------

    def test_the_oldest_placement_comes_first(self):
        """Oldest placement is also oldest flock, which is the one nearest
        lifting and nearest needing a decision."""
        late = self.farm("Aaa Farm")          # alphabetically first
        early = self.farm("Zzz Farm")         # alphabetically last
        self.batch(late, "young", 10)
        self.batch(early, "old", 40)
        self.assertEqual(self.order(), ["old", "young"])

    def test_it_is_no_longer_alphabetical_by_farm(self):
        a = self.farm("Aaa Farm")
        z = self.farm("Zzz Farm")
        self.batch(z, "oldest", 50)
        self.batch(a, "middle", 30)
        self.batch(z, "newest", 5)
        self.assertEqual(self.order(), ["oldest", "middle", "newest"])

    def test_two_flocks_placed_the_same_day_fall_back_to_farm_name(self):
        """A tie needs a stable tiebreak, or the order wobbles between loads."""
        z = self.farm("Zzz Farm")
        a = self.farm("Aaa Farm")
        self.batch(z, "z-batch", 20)
        self.batch(a, "a-batch", 20)
        self.assertEqual(self.order(), ["a-batch", "z-batch"])

    # ---- the placement the sort reads --------------------------------------

    def test_a_batch_with_no_start_date_sorts_by_the_placement_that_filled_it(self):
        """This is why the sort is not an ORDER BY on start_date: the column is
        blank here, and the flock is nonetheless the oldest on the report."""
        farm = self.farm("Bbb Farm")
        self.batch(farm, "dated", 10)
        undated = self.batch(farm, "undated", 45, dated=False)
        self.assertIsNone(undated.start_date)
        self.assertEqual(self.order(), ["undated", "dated"])

    def test_a_flock_with_no_placement_at_all_goes_last(self):
        """No placement is no age to sort by. It goes to the bottom rather than
        jumping the queue the way a null sorts by default."""
        farm = self.farm("Ccc Farm")
        BroilerBatch.objects.create(broiler_farm=farm, batch_name="ghost",
                                    start_date=None)
        self.batch(farm, "real", 15)
        self.assertEqual(self.order()[-1], "ghost")

    # ---- and the spreadsheet says the same thing ---------------------------

    def test_the_excel_export_lists_them_in_the_same_order(self):
        """The export builds from the same grid, so it cannot drift — this is
        what keeps that true."""
        a = self.farm("Aaa Farm")
        z = self.farm("Zzz Farm")
        self.batch(a, "younger", 5)
        self.batch(z, "older", 35)

        response = self.client.get(reverse("gc_realization_report"),
                                   {"status": "all", "submit": "1", "export": "excel"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("spreadsheet", response["Content-Type"])

        import io

        import openpyxl

        sheet = openpyxl.load_workbook(io.BytesIO(response.content)).active
        batches = [row[1] for row in sheet.iter_rows(min_row=2, max_col=2,
                                                     values_only=True)
                   if row[1]]
        self.assertEqual(batches[0], "older")
        self.assertEqual(batches[-1], "younger")
