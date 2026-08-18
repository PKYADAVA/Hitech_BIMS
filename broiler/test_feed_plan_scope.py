"""What the feed table's figures are actually *of*.

Three columns were reading across scopes that do not meet:

* ``BALANCE`` was this farm's receipts less *this batch's* feeding, so on a
  farm that had reared more than one flock it reported a store nobody had —
  2,237 kg of Starter on a farm 60 kg in deficit, the previous flock's 2,297 kg
  nowhere in the sum.
* The head count was read through the entry date while the feed and the
  departure charge were read up to it, so a day that already had an entry
  showed an opening already net of its own mortality — which the form then took
  off a second time as it was typed.
* ``required_kg`` — the flock's remaining allowance plus what the departed
  actually ate — was computed here, sent to both clients, and recomputed by
  each of them as cap x live. A flock that had sold out showed a requirement of
  nought against tonnes it had really eaten.

The clients' half is tested in ``mobile/src/domain/dailyEntry.test.ts``; this
is the payload they read.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase

from broiler.models import (BirdSale, Branch, Breed, BroilerBatch, BroilerFarm,
                            DailyEntry, Farmer, FeedPhaseLine, FeedPhaseMaster,
                            Region, Supervisor)
from broiler.views import daily_entry_lookup_payload
from inventory.models import Item, ItemCategory, StockTransfer, Warehouse


class FeedPlanScopeTests(TestCase):
    def setUp(self):
        self.today = date(2026, 7, 23)
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region, prefix="AKB")
        self.sup = Supervisor.objects.create(branch=branch, name="R. Verma")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=self.sup, farmer=farmer, region=region,
            line="L1", farm_name="Green Valley Farm", farm_capacity=9000)
        self.warehouse = Warehouse.objects.create(name="Akbarpur Store")

        feed_cat = ItemCategory.objects.create(name="Broiler Feed")
        chick_cat = ItemCategory.objects.create(name="Day Old Chicks")
        self.pre = Item.objects.create(item_code="ITM-0001", description="Pre-Starter Feed",
                                       category=feed_cat, standard_cost_per_unit=0)
        self.chick = Item.objects.create(item_code="CHK-001", description="Day Old Chick",
                                         category=chick_cat, standard_cost_per_unit=0)

        self.breed = Breed.objects.create(description="Cobb 500")
        master = FeedPhaseMaster.objects.create(program="Standard", breed=self.breed,
                                                status="active")
        FeedPhaseLine.objects.create(master=master, seq_no=1, from_age=1, to_age=40,
                                     feed_item=self.pre, phase_code="PS",
                                     max_feed_qty=Decimal("0.400"), status="active")

        self.batch = self.place("B-1", 1000, self.today - timedelta(days=10))

    # ---- fixtures -----------------------------------------------------------

    def place(self, name, chicks, when):
        batch = BroilerBatch.objects.create(broiler_farm=self.farm, batch_name=name,
                                            breed=self.breed, start_date=when)
        StockTransfer.objects.create(
            date=when, item=self.chick, quantity=chicks,
            from_location_type="warehouse", from_warehouse=self.warehouse,
            to_location_type="farm", to_farm=self.farm, to_batch=batch)
        return batch

    def send(self, kg, when=None):
        StockTransfer.objects.create(
            date=when or self.today - timedelta(days=10), item=self.pre, quantity=kg,
            from_location_type="warehouse", from_warehouse=self.warehouse,
            to_location_type="farm", to_farm=self.farm)

    def entry(self, batch, when, kg=0, mortality=0):
        return DailyEntry.objects.create(
            farm=self.farm, batch=batch, supervisor=self.sup, date=when,
            feed_1=self.pre if kg else None, feed_1_qty=kg, mortality=mortality)

    def plan(self, batch=None, on=None):
        payload = daily_entry_lookup_payload(
            self.farm.id, (on or self.today).isoformat(), (batch or self.batch).id)
        row = next((r for r in payload["feed_plan"]
                    if r["name"] == "Pre-Starter Feed"), None)
        return row, payload

    # ---- the balance is the farm's store ------------------------------------

    def test_the_balance_counts_what_the_farm_s_other_flock_ate(self):
        """One store, two flocks. The feed does not know which shed it is for."""
        self.send(1000)
        older = self.place("B-0", 500, self.today - timedelta(days=40))
        self.entry(older, self.today - timedelta(days=20), kg=600)
        self.entry(self.batch, self.today - timedelta(days=1), kg=100)

        row, _ = self.plan()
        # 1,000 delivered, 600 eaten by the other flock, 100 by this one.
        self.assertEqual(row["balance_kg"], "300.00")
        # SENT stays farm-level and unchanged — a delivery is booked to a farm.
        self.assertEqual(row["sent_kg"], "1000.00")
        # FED stays this flock's own.
        self.assertEqual(row["fed_kg"], "100.00")

    def test_the_balance_agrees_with_the_panel_s_own_stock_line(self):
        """The card used to contradict itself: the table said one figure for
        the store and the line under it said another."""
        self.send(1000)
        older = self.place("B-0", 500, self.today - timedelta(days=40))
        self.entry(older, self.today - timedelta(days=20), kg=600)

        row, payload = self.plan()
        line = next(s for s in payload["farm_feed_stock"] if s["item"] == self.pre.id)
        self.assertEqual(row["balance_kg"], line["kg"])

    def test_the_row_being_edited_is_left_out_of_the_store(self):
        """The form adds the kilos in the box; counting the saved row as well
        would take the same feed off twice."""
        self.send(1000)
        self.entry(self.batch, self.today, kg=250)          # the row being edited
        row, _ = self.plan(on=self.today)
        self.assertEqual(row["balance_kg"], "1000.00")

    def test_a_sister_flock_s_entry_on_the_same_day_still_counts(self):
        """It is not the row being written, and its feed has gone."""
        self.send(1000)
        older = self.place("B-0", 500, self.today - timedelta(days=40))
        self.entry(older, self.today, kg=400)
        row, _ = self.plan(on=self.today)
        self.assertEqual(row["balance_kg"], "600.00")

    # ---- the head count is the start of the day -----------------------------

    def test_the_count_is_the_flock_at_the_start_of_the_day(self):
        """Editing a saved day must not show an opening already net of it."""
        self.entry(self.batch, self.today, mortality=40)
        _row, payload = self.plan(on=self.today)
        self.assertEqual(payload["live_birds"], 1000)
        self.assertEqual(payload["mortality_to_date"], 0)

    def test_yesterday_s_losses_are_in_the_count(self):
        self.entry(self.batch, self.today - timedelta(days=1), mortality=40)
        _row, payload = self.plan(on=self.today)
        self.assertEqual(payload["live_birds"], 960)
        self.assertEqual(payload["mortality_to_date"], 40)

    def test_birds_lifted_on_the_day_are_still_owed_their_allowance(self):
        """They were in the shed that morning; the day's feed was theirs too.

        Counted through the sale, the requirement quietly dropped by their cap
        and their real consumption was never charged either — the feed they had
        eaten came off the survivors' allowance instead.
        """
        BirdSale.objects.create(farm=self.farm, batch=self.batch, date=self.today,
                                birds=600)
        row, payload = self.plan(on=self.today)
        self.assertEqual(payload["live_birds"], 1000)
        self.assertEqual(row["required_kg"], "400.00")

    def test_chicks_placed_that_morning_are_in_the_shed(self):
        """The losses move to the start of the day; the placement does not."""
        fresh = self.place("B-2", 800, self.today)
        _row, payload = self.plan(batch=fresh, on=self.today)
        self.assertEqual(payload["live_birds"], 800)

    # ---- what the clients need to work the requirement out ------------------

    def test_the_row_carries_the_feed_each_bird_has_had(self):
        """So a bird booked as lost on this row gives back the allowance it had
        not eaten, and keeps the rest."""
        self.send(1000)
        self.entry(self.batch, self.today - timedelta(days=1), kg=100)
        row, _ = self.plan()
        # 100 kg across 1,000 birds.
        self.assertEqual(Decimal(row["per_bird_fed_kg"]), Decimal("0.1000"))

    def test_a_flock_that_has_gone_still_has_a_requirement(self):
        """cap x live is nought once the shed is empty. What they ate is not."""
        self.send(1000)
        self.entry(self.batch, self.today - timedelta(days=3), kg=300)
        BirdSale.objects.create(farm=self.farm, batch=self.batch,
                                date=self.today - timedelta(days=2),
                                birds=1000)
        row, payload = self.plan()
        self.assertEqual(payload["live_birds"], 0)
        self.assertEqual(row["required_kg"], "300.00")
