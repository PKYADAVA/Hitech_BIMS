"""What a flock still needs of each feed, and whether enough has been sent.

The Daily Entry panel could say what had been eaten, but not what it was
measured against. A supervisor standing at the shed asks three things — how
much more of this feed does the batch need, has it arrived, and is any of it
sitting unused — and the form answered none of them.

`required` is the phase's kg/bird cap times the live flock. `sent` is what has
been delivered to the *farm*, because a delivery is booked to a farm and not to
a flock. The difference between sent and fed is the balance in the store; the
difference between sent and required is feed nobody will use in this phase.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from broiler.models import (Branch, BroilerBatch, BroilerFarm, DailyEntry,
                            Farmer, FeedPhaseLine, FeedPhaseMaster, Region,
                            Supervisor)
from broiler.views import daily_entry_lookup_payload
from inventory.models import Item, ItemCategory, StockTransfer, Warehouse


class FeedPlanTests(TestCase):
    def setUp(self):
        self.today = date(2026, 7, 23)
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region, prefix="AKB")
        sup = self.supervisor = Supervisor.objects.create(branch=branch, name="R. Verma")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=sup, farmer=farmer, region=region,
            line="L1", farm_name="Green Valley Farm", farm_capacity=9000)
        self.warehouse = Warehouse.objects.create(name="Akbarpur Store")

        feed_cat = ItemCategory.objects.create(name="Broiler Feed")
        chick_cat = ItemCategory.objects.create(name="Day Old Chicks")
        self.pre = Item.objects.create(item_code="ITM-0001", description="Pre-Starter Feed",
                                       category=feed_cat, standard_cost_per_unit=0)
        self.starter = Item.objects.create(item_code="ITM-0002", description="Starter Feed",
                                           category=feed_cat, standard_cost_per_unit=0)
        self.chick = Item.objects.create(item_code="CHK-001", description="Day Old Chick",
                                         category=chick_cat, standard_cost_per_unit=0)

        from broiler.models import Breed

        self.breed = Breed.objects.create(description="Cobb 500")
        self.batch = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="B-1", breed=self.breed,
            start_date=self.today - timedelta(days=2))

        master = FeedPhaseMaster.objects.create(program="Standard", breed=self.breed,
                                                status="active")
        FeedPhaseLine.objects.create(master=master, seq_no=1, from_age=1, to_age=12,
                                     feed_item=self.pre, phase_code="PS",
                                     max_feed_qty=Decimal("0.400"), status="active")
        FeedPhaseLine.objects.create(master=master, seq_no=2, from_age=13, to_age=26,
                                     feed_item=self.starter, phase_code="ST",
                                     max_feed_qty=Decimal("1.200"), status="active")

        # 1,000 chicks placed.
        StockTransfer.objects.create(
            date=self.today - timedelta(days=2), item=self.chick, quantity=1000,
            from_location_type="warehouse", from_warehouse=self.warehouse,
            to_location_type="farm", to_farm=self.farm, to_batch=self.batch)

        User = get_user_model()
        self.user = User.objects.create_superuser("fp_user", "fp@x.com", "Str0ngPass!")

    def send(self, item, kg, when=None):
        return StockTransfer.objects.create(
            date=when or self.today - timedelta(days=1), item=item, quantity=kg,
            from_location_type="warehouse", from_warehouse=self.warehouse,
            to_location_type="farm", to_farm=self.farm)

    def feed(self, item, kg, when=None):
        return DailyEntry.objects.create(
            farm=self.farm, batch=self.batch, supervisor=self.supervisor,
            date=when or self.today - timedelta(days=1),
            feed_1=item, feed_1_qty=kg)

    def plan(self, name="Pre-Starter Feed"):
        payload = daily_entry_lookup_payload(self.farm.id, self.today.isoformat())
        return next((r for r in payload["feed_plan"] if r["name"] == name), None), payload

    # ---- the requirement ----------------------------------------------------

    def test_required_is_the_phase_cap_times_the_live_flock(self):
        row, payload = self.plan()
        self.assertEqual(payload["live_birds"], 1000)
        # 0.400 kg/bird cap x 1,000 birds.
        self.assertEqual(row["required_kg"], "400.00")

    def test_every_feed_in_the_program_is_reported_not_only_the_current_one(self):
        """A supervisor ordering next week's feed needs the phase after this
        one, not just the one being fed today."""
        _row, payload = self.plan()
        self.assertEqual(sorted(r["name"] for r in payload["feed_plan"]),
                         ["Pre-Starter Feed", "Starter Feed"])

    def test_the_requirement_follows_the_flock_down(self):
        """Birds that have died do not eat. The requirement is against what is
        alive, so it falls as the flock does."""
        DailyEntry.objects.create(farm=self.farm, batch=self.batch,
                                  supervisor=self.supervisor,
                                  date=self.today - timedelta(days=1), mortality=100)
        row, payload = self.plan()
        self.assertEqual(payload["live_birds"], 900)
        self.assertEqual(row["required_kg"], "360.00")

    # ---- sent, fed, balance -------------------------------------------------

    def test_sent_is_what_reached_the_farm(self):
        self.send(self.pre, 500)
        row, _ = self.plan()
        self.assertEqual(row["sent_kg"], "500.00")

    def test_balance_is_what_was_sent_less_what_was_fed(self):
        self.send(self.pre, 500)
        self.feed(self.pre, 120)
        row, _ = self.plan()
        self.assertEqual(row["fed_kg"], "120.00")
        self.assertEqual(row["balance_kg"], "380.00")

    def test_remaining_is_the_requirement_less_what_was_fed(self):
        self.feed(self.pre, 120)
        row, _ = self.plan()
        self.assertEqual(row["remaining_kg"], "280.00")

    def test_feeding_past_the_cap_shows_as_a_negative_remainder(self):
        """The phase should have changed over and did not."""
        self.feed(self.pre, 450)
        row, _ = self.plan()
        self.assertEqual(row["remaining_kg"], "-50.00")

    def test_feeding_more_than_arrived_shows_as_a_negative_balance(self):
        """Either a delivery was never booked, or the feed came from somewhere
        nobody recorded — the case the form's Stock column already hinted at."""
        self.feed(self.pre, 25)
        row, _ = self.plan()
        self.assertEqual(row["sent_kg"], "0.00")
        self.assertEqual(row["balance_kg"], "-25.00")

    # ---- excess -------------------------------------------------------------

    def test_sending_more_than_the_phase_can_use_is_reported(self):
        self.send(self.pre, 600)                      # requirement is 400
        row, _ = self.plan()
        self.assertEqual(row["excess_kg"], "200.00")

    def test_sending_exactly_enough_is_not_excess(self):
        self.send(self.pre, 400)
        row, _ = self.plan()
        self.assertIsNone(row["excess_kg"])

    def test_sending_less_than_needed_is_not_excess(self):
        self.send(self.pre, 100)
        row, _ = self.plan()
        self.assertIsNone(row["excess_kg"])

    # ---- what is actually on the farm ---------------------------------------

    def test_farm_stock_lists_feed_on_hand_whatever_phase_it_belongs_to(self):
        self.send(self.starter, 800)                  # for a phase not yet reached
        _row, payload = self.plan()
        names = {r["name"]: r["kg"] for r in payload["farm_feed_stock"]}
        self.assertEqual(names.get("Starter Feed"), "800.00")

    def test_farm_stock_leaves_out_what_is_not_there(self):
        _row, payload = self.plan()
        self.assertEqual(payload["farm_feed_stock"], [])

    # ---- a farm with no flock ----------------------------------------------

    def test_a_farm_with_no_batch_reports_no_plan_rather_than_failing(self):
        other = BroilerFarm.objects.create(
            branch=self.farm.branch, supervisor=self.farm.supervisor,
            farmer=self.farm.farmer, region=self.farm.region, line="L1",
            farm_name="Empty Farm", farm_capacity=1000)
        payload = daily_entry_lookup_payload(other.id, self.today.isoformat())
        self.assertEqual(payload["feed_plan"], [])
        self.assertEqual(payload["farm_feed_stock"], [])
