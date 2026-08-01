"""Which date a Daily Entry opens on.

The reported fault: a newly placed batch offered today's date, skipping every
day between placement and whenever someone happened to open the form. Age 0 is
placement day, so the first entry belongs to the day after it — not to today.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from broiler.models import (Branch, BroilerBatch, BroilerFarm, DailyEntry,
                            Farmer, Region, Supervisor)
from broiler.views import daily_entry_lookup_payload


class DailyEntryNextDateTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region,
                                       prefix="AKB")
        self.supervisor = Supervisor.objects.create(branch=branch, name="R. Verma")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=self.supervisor, farmer=farmer, region=region,
            line="L1", farm_name="Yadav Farm", farm_capacity=5000)

    def batch(self, name, placed_days_ago, closed=False):
        return BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name=name,
            start_date=self.today - timedelta(days=placed_days_ago),
            is_closed=closed,
            end_date=self.today - timedelta(days=1) if closed else None)

    def entry(self, batch, days_ago):
        return DailyEntry.objects.create(
            farm=self.farm, batch=batch, supervisor=self.supervisor,
            date=self.today - timedelta(days=days_ago), mortality=1)

    def next_date(self):
        return daily_entry_lookup_payload(str(self.farm.id), None)["next_date"]

    # ---- a batch with no entries yet --------------------------------------

    def test_a_new_batch_starts_the_day_after_placement(self):
        """The reported case. Placed a fortnight ago and never recorded, the
        form must open on placement + 1, not on today."""
        batch = self.batch("New", placed_days_ago=14)
        expected = (batch.start_date + timedelta(days=1)).isoformat()
        self.assertEqual(self.next_date(), expected)
        self.assertNotEqual(self.next_date(), self.today.isoformat())

    def test_a_batch_placed_yesterday_opens_on_today(self):
        """Placement + 1 happens to be today, which is right rather than a
        coincidence worth special-casing."""
        self.batch("Fresh", placed_days_ago=1)
        self.assertEqual(self.next_date(), self.today.isoformat())

    # ---- a batch that has been recorded ------------------------------------

    def test_it_continues_the_day_after_the_last_entry(self):
        batch = self.batch("Running", placed_days_ago=20)
        self.entry(batch, days_ago=3)
        expected = (self.today - timedelta(days=2)).isoformat()
        self.assertEqual(self.next_date(), expected)

    def test_a_new_batch_does_not_inherit_the_previous_one(self):
        """A farm re-used for a new flock would otherwise pick up the old
        batch's last entry and start the new one weeks late."""
        old = self.batch("Old", placed_days_ago=90, closed=True)
        self.entry(old, days_ago=60)
        new = self.batch("New", placed_days_ago=5)

        expected = (new.start_date + timedelta(days=1)).isoformat()
        self.assertEqual(self.next_date(), expected)

    # ---- the age that goes with it -----------------------------------------

    def test_age_counts_from_placement_not_from_the_first_entry(self):
        batch = self.batch("Aged", placed_days_ago=10)
        payload = daily_entry_lookup_payload(str(self.farm.id), None)
        self.assertEqual(payload["next_date"],
                         (batch.start_date + timedelta(days=1)).isoformat())
        self.assertEqual(payload["age_days"], 1)     # placement day is Age 0

    def test_a_farm_with_no_batch_falls_back_to_today(self):
        self.assertEqual(self.next_date(), self.today.isoformat())


class PlacementWithoutStartDateTests(TestCase):
    """A batch can exist with no start_date, and one such batch is enough for
    every date on the form to fall back to today.

    The placement is a chick-category stock transfer into the batch — the same
    definition the Live Flock figures use — so that stands in when start_date
    is blank. This is what the first fix missed: it read start_date only, so on
    the batch that actually had the problem nothing changed.
    """

    def setUp(self):
        from inventory.models import Item, ItemCategory, StockTransfer

        self.today = timezone.localdate()
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region,
                                       prefix="AKB")
        self.supervisor = Supervisor.objects.create(branch=branch, name="R. Verma")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=self.supervisor, farmer=farmer, region=region,
            line="L1", farm_name="Yadav Farm", farm_capacity=5000)
        self.chick = Item.objects.create(
            description="Day Old Chicks",
            category=ItemCategory.objects.create(name="Chicks"),
            valuation_method="Weighted Average", standard_cost_per_unit=40,
            usage="Produced", source="Purchased", type="Raw Material",
            item_account="Expense")
        self.StockTransfer = StockTransfer

    def place(self, batch, days_ago, quantity=1000):
        return self.StockTransfer.objects.create(
            item=self.chick, to_batch=batch, quantity=quantity,
            date=self.today - timedelta(days=days_ago))

    def lookup(self):
        return daily_entry_lookup_payload(str(self.farm.id), None)

    def test_placement_is_taken_from_the_chick_transfer(self):
        batch = BroilerBatch.objects.create(broiler_farm=self.farm,
                                            batch_name="NoStart")
        self.place(batch, days_ago=11)
        expected = (self.today - timedelta(days=10)).isoformat()
        self.assertEqual(self.lookup()["next_date"], expected)
        self.assertNotEqual(self.lookup()["next_date"], self.today.isoformat())

    def test_age_is_counted_from_it_too(self):
        """Age had the same hole: without start_date it was always 0."""
        batch = BroilerBatch.objects.create(broiler_farm=self.farm,
                                            batch_name="NoStart")
        self.place(batch, days_ago=11)
        self.assertEqual(self.lookup()["age_days"], 1)

    def test_start_date_still_wins_when_it_is_set(self):
        batch = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="Both",
            start_date=self.today - timedelta(days=5))
        self.place(batch, days_ago=30)          # a stale transfer
        expected = (self.today - timedelta(days=4)).isoformat()
        self.assertEqual(self.lookup()["next_date"], expected)

    def test_the_earliest_transfer_is_the_placement(self):
        """Top-ups arrive later; the flock started with the first delivery."""
        batch = BroilerBatch.objects.create(broiler_farm=self.farm,
                                            batch_name="TopUp")
        self.place(batch, days_ago=9)
        self.place(batch, days_ago=12)
        expected = (self.today - timedelta(days=11)).isoformat()
        self.assertEqual(self.lookup()["next_date"], expected)

    def test_no_placement_at_all_still_falls_back_to_today(self):
        BroilerBatch.objects.create(broiler_farm=self.farm, batch_name="Empty")
        self.assertEqual(self.lookup()["next_date"], self.today.isoformat())
