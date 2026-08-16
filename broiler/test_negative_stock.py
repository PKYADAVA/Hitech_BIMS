"""Neither form may take a stock balance below zero.

The Stock column has shown a shortfall for a while and it was still possible to
save straight through it. The balance then carried the error forward into every
later entry on that farm, which is how a feed ledger ends up reading minus
twenty-five kilograms — and why the figures a supervisor orders against could
not be trusted.

Both doors are shut: the web form saves through ``full_clean`` and the phone
through the serializer, and a rule enforced on one of them is a rule the other
route walks straight past.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from broiler.models import (Branch, BroilerBatch, BroilerFarm, DailyEntry,
                            Farmer, Region, Supervisor)
from inventory.models import (Item, ItemCategory, ItemPriceList, StockTransfer,
                              Warehouse)


class FeedStockGuardTests(TestCase):
    def setUp(self):
        self.today = date(2026, 7, 23)
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region, prefix="AKB")
        self.sup = Supervisor.objects.create(branch=branch, name="R. Verma")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=self.sup, farmer=farmer, region=region,
            line="L1", farm_name="Green Valley Farm", farm_capacity=9000)
        self.other_farm = BroilerFarm.objects.create(
            branch=branch, supervisor=self.sup, farmer=farmer, region=region,
            line="L1", farm_name="Second Farm", farm_capacity=5000)
        self.warehouse = Warehouse.objects.create(name="Akbarpur Store")

        feed = ItemCategory.objects.create(name="Broiler Feed")
        self.pre = Item.objects.create(item_code="ITM-0001", description="Pre-Starter Feed",
                                       category=feed, standard_cost_per_unit=0)
        self.starter = Item.objects.create(item_code="ITM-0002", description="Starter Feed",
                                           category=feed, standard_cost_per_unit=0)
        self.batch = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="B-1",
            start_date=self.today - timedelta(days=5))

    def deliver(self, item, kg, to=None, when=None):
        return StockTransfer.objects.create(
            date=when or self.today - timedelta(days=2), item=item, quantity=kg,
            from_location_type="warehouse", from_warehouse=self.warehouse,
            to_location_type="farm", to_farm=to or self.farm)

    def entry(self, **kw):
        row = dict(farm=self.farm, batch=self.batch, supervisor=self.sup,
                   date=self.today)
        row.update(kw)
        return DailyEntry(**row)

    # ---- the web path (full_clean) ------------------------------------------

    def test_feeding_more_than_was_delivered_is_refused(self):
        self.deliver(self.pre, 100)
        e = self.entry(feed_1=self.pre, feed_1_qty=Decimal("150"))
        with self.assertRaises(ValidationError) as caught:
            e.full_clean(exclude=["entry_no", "batch"])
        self.assertIn("only 100", str(caught.exception))

    def test_feeding_exactly_what_is_there_is_allowed(self):
        self.deliver(self.pre, 100)
        e = self.entry(feed_1=self.pre, feed_1_qty=Decimal("100"))
        e.full_clean(exclude=["entry_no", "batch"])          # must not raise

    def test_feeding_nothing_is_allowed_on_a_farm_with_no_feed(self):
        """A day recording only mortality must not be blocked by an empty store."""
        e = self.entry(mortality=5)
        e.full_clean(exclude=["entry_no", "batch"])

    def test_both_slots_are_weighed_together_when_they_carry_one_feed(self):
        """Checked separately, a farm with 100 kg could feed 60 twice."""
        self.deliver(self.pre, 100)
        e = self.entry(feed_1=self.pre, feed_1_qty=Decimal("60"),
                       feed_2=self.pre, feed_2_qty=Decimal("60"))
        with self.assertRaises(ValidationError):
            e.full_clean(exclude=["entry_no", "batch"])

    def test_two_different_feeds_are_weighed_against_their_own_stock(self):
        self.deliver(self.pre, 100)
        self.deliver(self.starter, 100)
        e = self.entry(feed_1=self.pre, feed_1_qty=Decimal("80"),
                       feed_2=self.starter, feed_2_qty=Decimal("80"))
        e.full_clean(exclude=["entry_no", "batch"])

    def test_an_earlier_entry_eats_into_what_is_left(self):
        self.deliver(self.pre, 100)
        DailyEntry.objects.create(farm=self.farm, batch=self.batch, supervisor=self.sup,
                                  date=self.today - timedelta(days=1),
                                  feed_1=self.pre, feed_1_qty=Decimal("70"))
        e = self.entry(feed_1=self.pre, feed_1_qty=Decimal("50"))
        with self.assertRaises(ValidationError):
            e.full_clean(exclude=["entry_no", "batch"])

    def test_editing_a_saved_entry_is_not_measured_against_itself(self):
        """The row's own consumption is already in the balance; counting it
        again would make every saved entry uneditable."""
        self.deliver(self.pre, 100)
        saved = DailyEntry.objects.create(
            farm=self.farm, batch=self.batch, supervisor=self.sup,
            date=self.today, feed_1=self.pre, feed_1_qty=Decimal("90"))
        saved.feed_1_qty = Decimal("95")
        saved.full_clean(exclude=["entry_no", "batch"])      # must not raise

    def test_another_farm_s_feed_does_not_count(self):
        self.deliver(self.pre, 500, to=self.other_farm)
        e = self.entry(feed_1=self.pre, feed_1_qty=Decimal("10"))
        with self.assertRaises(ValidationError):
            e.full_clean(exclude=["entry_no", "batch"])

    # ---- the phone path (serializer) ---------------------------------------

    def test_the_api_refuses_it_too(self):
        from broiler.api import DailyEntrySerializer

        self.deliver(self.pre, 100)
        ser = DailyEntrySerializer(data={
            "farm": self.farm.id, "supervisor": self.sup.id,
            "date": self.today.isoformat(),
            "feed_1": self.pre.id, "feed_1_qty": "150",
        })
        self.assertFalse(ser.is_valid())
        self.assertIn("feed_1_qty", ser.errors)

    def test_the_api_allows_what_fits(self):
        from broiler.api import DailyEntrySerializer

        self.deliver(self.pre, 100)
        ser = DailyEntrySerializer(data={
            "farm": self.farm.id, "supervisor": self.sup.id,
            "date": self.today.isoformat(),
            "feed_1": self.pre.id, "feed_1_qty": "80",
        })
        self.assertTrue(ser.is_valid(), ser.errors)

    # ---- the two entry pages (the endpoint they post to) --------------------

    def _post(self, qty):
        """What Daily Entry and Add Day Record both submit."""
        from django.contrib.auth import get_user_model
        import json

        user = get_user_model().objects.create_superuser(
            username="entry-clerk", email="clerk@test.local", password="pw")
        self.client.force_login(user)
        return self.client.post("/daily_entry_api/", data=json.dumps({
            "supervisor": self.sup.id, "farm": self.farm.id,
            "rows": [{"date": self.today.isoformat(), "batch": self.batch.id,
                      "feed_1": self.pre.id, "feed_1_qty": qty}],
        }), content_type="application/json")

    def test_the_page_s_own_endpoint_refuses_it_and_saves_nothing(self):
        """The grid checks as you type, but the page is not the guard.

        Both entry pages post here, and so does anything else that learns the
        url. A row refused in the browser must be refused again on arrival, or
        the rule only holds for people using the form as intended.
        """
        self.deliver(self.pre, 100)
        resp = self._post("150")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("only 100", resp.json()["error"])
        self.assertEqual(DailyEntry.objects.count(), 0)

    def test_the_page_s_own_endpoint_takes_what_fits(self):
        self.deliver(self.pre, 100)
        self.assertEqual(self._post("80").status_code, 201)
        self.assertEqual(DailyEntry.objects.count(), 1)

    # ---- the balance the registers' edit dialog shows -----------------------

    def _lookup(self, item, **extra):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.filter(username="looker").first()
        if not user:
            user = get_user_model().objects.create_superuser(
                username="looker", email="look@test.local", password="pw")
        self.client.force_login(user)
        params = {"farm": self.farm.id, "item": item.id,
                  "date": self.today.isoformat(), **extra}
        return Decimal(self.client.get("/daily-entry/stock-lookup/",
                                       params).json()["stock"])

    def test_the_dialog_leaves_the_row_being_edited_out_of_the_balance(self):
        """Or every saved entry opens looking like a shortfall.

        The row's own Kgs are already out of the farm's balance. Counted again
        they would be subtracted twice, and a 90 kg entry against a 100 kg
        delivery would open saying 10 kg left and refuse its own quantity.
        """
        self.deliver(self.pre, 100)
        saved = DailyEntry.objects.create(
            farm=self.farm, batch=self.batch, supervisor=self.sup,
            date=self.today, feed_1=self.pre, feed_1_qty=Decimal("90"))
        self.assertEqual(self._lookup(self.pre, entry=saved.id), Decimal("100"))
        # Without the id it is the balance for a *new* row on that day, which
        # is what the Add pages ask for and correctly has the 90 taken out.
        self.assertEqual(self._lookup(self.pre), Decimal("10"))

    def test_a_junk_entry_id_is_ignored_rather_than_erroring(self):
        self.deliver(self.pre, 100)
        self.assertEqual(self._lookup(self.pre, entry="abc"), Decimal("100"))


class TransferStockGuardTests(TestCase):
    """A transfer out of a farm could not go negative either.

    Warehouses have been guarded since the column existed; farms were left out
    on the grounds that feed is eaten there rather than dispatched. It is still
    moved out — farm to farm, or back to a store — and those movements could
    take the balance below zero exactly as a warehouse's could.
    """

    def setUp(self):
        self.today = date(2026, 7, 23)
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region, prefix="AKB")
        sup = Supervisor.objects.create(branch=branch, name="R. Verma")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=sup, farmer=farmer, region=region,
            line="L1", farm_name="Green Valley Farm", farm_capacity=9000)
        self.other = BroilerFarm.objects.create(
            branch=branch, supervisor=sup, farmer=farmer, region=region,
            line="L1", farm_name="Second Farm", farm_capacity=5000)
        self.warehouse = Warehouse.objects.create(name="Akbarpur Store")
        feed = ItemCategory.objects.create(name="Broiler Feed")
        self.item = Item.objects.create(item_code="ITM-0001", description="Pre-Starter Feed",
                                        category=feed, standard_cost_per_unit=0)
        # A transfer is priced from the Item Price Master, and that check runs
        # before this one — without a price the row never reaches the stock rule.
        ItemPriceList.objects.create(item=self.item, price=Decimal("30"),
                                     effective_date=self.today - timedelta(days=30))

    def deliver(self, kg):
        return StockTransfer.objects.create(
            date=self.today - timedelta(days=2), item=self.item, quantity=kg,
            from_location_type="warehouse", from_warehouse=self.warehouse,
            to_location_type="farm", to_farm=self.farm)

    def moving_out(self, kg):
        return StockTransfer(
            date=self.today, item=self.item, quantity=kg,
            from_location_type="farm", from_farm=self.farm,
            to_location_type="farm", to_farm=self.other)

    def test_moving_more_off_a_farm_than_it_holds_is_refused(self):
        self.deliver(100)
        with self.assertRaises(ValidationError) as caught:
            self.moving_out(150).full_clean(exclude=["trnum", "stock"])
        self.assertIn("Not enough stock", str(caught.exception))

    def test_moving_what_the_farm_holds_is_allowed(self):
        self.deliver(100)
        self.moving_out(100).full_clean(exclude=["trnum", "stock"])

    def test_a_farm_with_nothing_cannot_send_anything(self):
        with self.assertRaises(ValidationError):
            self.moving_out(1).full_clean(exclude=["trnum", "stock"])

    def test_editing_a_saved_transfer_is_not_measured_against_itself(self):
        self.deliver(100)
        out = self.moving_out(90)
        out.save()
        out.quantity = Decimal("95")
        out.full_clean(exclude=["trnum", "stock"])           # must not raise

    def test_the_warehouse_guard_still_holds(self):
        with self.assertRaises(ValidationError):
            StockTransfer(
                date=self.today, item=self.item, quantity=10,
                from_location_type="warehouse", from_warehouse=self.warehouse,
                to_location_type="farm", to_farm=self.farm,
            ).full_clean(exclude=["trnum", "stock"])
