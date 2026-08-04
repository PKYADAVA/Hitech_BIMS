"""Mobile API v1 — Daily Entry write path (``/api/v1/broiler/daily-entries``).

The web form derives a Daily Entry's batch, age and running feed stock in
``broiler.views._apply_daily_entry_row``; the API has to reach the same result
or the two clients disagree about the same row. ``age_days``, ``feed_1_stock``
and ``feed_2_stock`` are ``editable=False``, so DRF never accepts them from the
request — before ``DailyEntrySerializer`` they saved as 0, and because
``DailyEntry.previous_stock`` chains each row's opening balance off the previous
row's closing balance, one zeroed row corrupted every later entry on that farm.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from broiler.models import (
    Branch, BroilerBatch, BroilerFarm, DailyEntry, Farmer, Region, Supervisor,
)
from inventory.models import Item, ItemCategory

ENDPOINT = "/api/v1/broiler/daily-entries/"


class DailyEntryApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            "field", "f@x.com", "Str0ngPass!")
        self.client.force_authenticate(self.user)

        self.region = Region.objects.create(description="East")
        self.branch = Branch.objects.create(
            branch_name="Gorakhpur", region=self.region, prefix="GKP")
        self.supervisor = Supervisor.objects.create(name="Ramesh", branch=self.branch)
        self.farmer = Farmer.objects.create(farmer_name="Suresh Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=self.branch, supervisor=self.supervisor, farmer=self.farmer,
            region="East", line="L1", farm_name="Lacchipur Farm", farm_capacity=5000)
        # Placement day is Age 0, so an entry on the 10th is Age 9.
        self.batch = BroilerBatch.objects.create(
            broiler_farm=self.farm, start_date=date(2026, 7, 1))

        cat = ItemCategory.objects.create(name="Feed")
        self.feed = Item.objects.create(
            description="Pre Starter Feed", category=cat,
            valuation_method="Weighted Average", standard_cost_per_unit=Decimal("50"),
            usage="Produced", source="Purchased", type="Raw Material",
            item_account="Expense")

    def post(self, **over):
        payload = {
            "date": "2026-07-10",
            "supervisor": self.supervisor.id,
            "farm": self.farm.id,
            "mortality": 3,
            "culls": 1,
            "avg_weight_gms": "850.00",
        }
        payload.update(over)
        return self.client.post(ENDPOINT, payload)

    # -------------------------------------------------------------- derived

    def test_age_is_computed_from_the_batch_start_date(self):
        resp = self.post()
        self.assertEqual(resp.status_code, 201, resp.content)
        entry = DailyEntry.objects.get()
        # 2026-07-01 placement → 2026-07-10 is day 9.
        self.assertEqual(entry.age_days, 9)

    def test_client_cannot_forge_age_or_stock(self):
        """The computed fields are read-only — a client sending them is ignored
        rather than trusted."""
        resp = self.post(age_days=999, feed_1_stock="500", feed_2_stock="500")
        self.assertEqual(resp.status_code, 201, resp.content)
        entry = DailyEntry.objects.get()
        self.assertEqual(entry.age_days, 9)
        self.assertEqual(entry.feed_1_stock, Decimal("0"))

    def test_batch_is_derived_from_the_farm_not_the_client(self):
        other_farm = BroilerFarm.objects.create(
            branch=self.branch, supervisor=self.supervisor, farmer=self.farmer,
            region="East", line="L1", farm_name="Other Farm", farm_capacity=100)
        stray = BroilerBatch.objects.create(
            broiler_farm=other_farm, start_date=date(2026, 1, 1))

        resp = self.post(batch=stray.id)
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(DailyEntry.objects.get().batch_id, self.batch.id)

    def test_age_uses_the_placement_transfer_when_start_date_is_blank(self):
        """A batch created from a chicks placement has no ``start_date``.

        The web form resolves the placement day through ``_placement_date``,
        which falls back to the chick-category transfer into the batch. Reading
        ``batch.start_date`` here instead meant the phone stored age 0 for such
        a flock while the register showed its real age — the same row, two
        different ages, depending on which client saved it.
        """
        from broiler.views import _placement_date
        from inventory.models import StockTransfer

        placed = BroilerFarm.objects.create(
            branch=self.branch, supervisor=self.supervisor, farmer=self.farmer,
            region="East", line="L1", farm_name="Placement Farm", farm_capacity=900)
        batch = BroilerBatch.objects.create(broiler_farm=placed, start_date=None)
        chicks = Item.objects.create(
            description="Day Old Chick", category=ItemCategory.objects.create(name="Chicks"),
            valuation_method="Weighted Average", standard_cost_per_unit=Decimal("30"),
            usage="Produced", source="Purchased", type="Raw Material",
            item_account="Expense")
        StockTransfer.objects.create(
            item=chicks, to_batch=batch, date=date(2026, 7, 1), quantity=Decimal("500"))
        self.assertEqual(_placement_date(batch), date(2026, 7, 1))

        resp = self.post(farm=placed.id, batch=batch.id, date="2026-07-10")
        self.assertEqual(resp.status_code, 201, resp.content)
        entry = DailyEntry.objects.get(farm=placed)
        self.assertEqual(entry.age_days, 9)

    def test_a_chosen_batch_on_the_farm_is_honoured(self):
        """Two open flocks on one farm: the entry belongs to the one picked.

        The web form's ``_resolve_batch`` takes the chosen batch when it is on
        that farm. Replacing it with "the farm's active batch" regardless filed
        the entry against whichever flock sorted first."""
        second = BroilerBatch.objects.create(
            broiler_farm=self.farm, start_date=date(2026, 7, 5))
        resp = self.post(batch=second.id)
        self.assertEqual(resp.status_code, 201, resp.content)
        entry = DailyEntry.objects.get()
        self.assertEqual(entry.batch_id, second.id)
        # ...and its age comes from *that* batch: 2026-07-05 → 2026-07-10 is 5.
        self.assertEqual(entry.age_days, 5)

    def test_entry_by_is_stamped_from_the_request_user(self):
        self.post()
        self.assertEqual(DailyEntry.objects.get().entry_by_id, self.user.id)

    def test_age_is_never_negative_before_placement(self):
        resp = self.post(date="2026-06-20")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(DailyEntry.objects.get().age_days, 0)

    # ---------------------------------------------------------- stock chain

    def test_feed_stock_runs_down_across_successive_entries(self):
        self.post(date="2026-07-10", feed_1=self.feed.id, feed_1_qty="40")
        self.post(date="2026-07-11", feed_1=self.feed.id, feed_1_qty="25")

        first, second = DailyEntry.objects.order_by("date", "id")
        # Opening balance 0, so closing stock goes negative as feed is issued —
        # same convention as the web form (stock is fed in via other modules).
        self.assertEqual(first.feed_1_stock, Decimal("-40"))
        self.assertEqual(second.feed_1_stock, Decimal("-65"))

    def test_editing_an_earlier_row_recomputes_every_later_row(self):
        self.post(date="2026-07-10", feed_1=self.feed.id, feed_1_qty="40")
        self.post(date="2026-07-11", feed_1=self.feed.id, feed_1_qty="25")
        first, second = DailyEntry.objects.order_by("date", "id")

        resp = self.client.patch(f"{ENDPOINT}{first.id}/", {"feed_1_qty": "10"})
        self.assertEqual(resp.status_code, 200, resp.content)

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.feed_1_stock, Decimal("-10"))
        # The later row's opening balance moved with it — this is the chain
        # that silently went stale before.
        self.assertEqual(second.feed_1_stock, Decimal("-35"))

    def test_backfilled_row_slots_into_the_chain_in_date_order(self):
        self.post(date="2026-07-12", feed_1=self.feed.id, feed_1_qty="30")
        self.post(date="2026-07-10", feed_1=self.feed.id, feed_1_qty="20")

        early, late = DailyEntry.objects.order_by("date", "id")
        self.assertEqual(early.date, date(2026, 7, 10))
        self.assertEqual(early.feed_1_stock, Decimal("-20"))
        self.assertEqual(late.feed_1_stock, Decimal("-50"))

    def test_second_feed_slot_keeps_its_own_balance(self):
        other = Item.objects.create(
            description="Starter Feed", category=self.feed.category,
            valuation_method="Weighted Average", standard_cost_per_unit=Decimal("55"),
            usage="Produced", source="Purchased", type="Raw Material",
            item_account="Expense")
        self.post(date="2026-07-10", feed_1=self.feed.id, feed_1_qty="40",
                  feed_2=other.id, feed_2_qty="15")

        entry = DailyEntry.objects.get()
        self.assertEqual(entry.feed_1_stock, Decimal("-40"))
        self.assertEqual(entry.feed_2_stock, Decimal("-15"))

    # ------------------------------------------------------- field capture

    def test_gps_coordinates_are_accepted_from_the_field(self):
        resp = self.post(entry_latitude="26.7606", entry_longitude="83.3732")
        self.assertEqual(resp.status_code, 201, resp.content)
        entry = DailyEntry.objects.get()
        self.assertAlmostEqual(entry.entry_latitude, 26.7606, places=4)
        self.assertAlmostEqual(entry.entry_longitude, 83.3732, places=4)


class DailyEntryFarmLookupTests(APITestCase):
    """``/api/v1/broiler/farm-lookup`` — the age it reports has to match the
    age the write path will compute, or the form shows one number and saves
    another."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            "look", "l@x.com", "Str0ngPass!")
        self.client.force_authenticate(self.user)
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(
            branch_name="Gorakhpur", region=region, prefix="GKP")
        supervisor = Supervisor.objects.create(name="Ramesh", branch=branch)
        farmer = Farmer.objects.create(farmer_name="Suresh Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=supervisor, farmer=farmer,
            region="East", line="L1", farm_name="Lacchipur Farm", farm_capacity=5000)
        self.batch = BroilerBatch.objects.create(
            broiler_farm=self.farm, start_date=date(2026, 7, 1))

    def test_age_is_resolved_as_of_the_requested_date(self):
        resp = self.client.get(
            "/api/v1/broiler/farm-lookup",
            {"farm": self.farm.id, "date": "2026-07-10"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["age_days"], 9)
        self.assertEqual(data["batch"], self.batch.id)

    def test_next_date_continues_the_day_after_the_last_entry(self):
        DailyEntry.objects.create(
            date=date(2026, 7, 10), supervisor=self.farm.supervisor,
            farm=self.farm, batch=self.batch)
        resp = self.client.get("/api/v1/broiler/farm-lookup", {"farm": self.farm.id})
        self.assertEqual(resp.json()["data"]["next_date"], "2026-07-11")


class DailyEntryLookupTests(APITestCase):
    """``/api/v1/broiler/daily-entry-lookup`` and ``/daily-entry-stock`` — the
    advisory payload behind the form's warnings.

    Both delegate to the same functions the web form uses, so these assert the
    wiring and the shape the mobile client destructures, not the arithmetic
    (``broiler.views`` owns that).
    """

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            "advise", "a@x.com", "Str0ngPass!")
        self.client.force_authenticate(self.user)
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(
            branch_name="Gorakhpur", region=region, prefix="GKP")
        supervisor = Supervisor.objects.create(name="Ramesh", branch=branch)
        farmer = Farmer.objects.create(farmer_name="Suresh Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=supervisor, farmer=farmer,
            region="East", line="L1", farm_name="Lacchipur Farm", farm_capacity=5000)
        self.batch = BroilerBatch.objects.create(
            broiler_farm=self.farm, start_date=date(2026, 7, 1))
        category = ItemCategory.objects.create(name="Feed")
        self.feed = Item.objects.create(
            description="Pre Starter", category=category,
            valuation_method="Weighted Average", standard_cost_per_unit=Decimal("50"),
            usage="Produced", source="Purchased", type="Raw Material",
            item_account="Expense")

    def test_lookup_carries_the_advisory_fields_the_form_needs(self):
        resp = self.client.get(
            "/api/v1/broiler/daily-entry-lookup",
            {"farm": self.farm.id, "date": "2026-07-10"})
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()["data"]
        # Same age rule as farm-lookup and the write path.
        self.assertEqual(data["age_days"], 9)
        self.assertEqual(data["batch"], self.batch.id)
        # The keys every warning on the form reads.
        for key in ("feed_phase", "std_feed_kg", "std_weight_g", "std_note",
                    "bs_curve", "cum_feed_before_kg", "consumed_by_item",
                    "consumed_total_kg", "consumed_per_bird_actual_g", "live_birds"):
            self.assertIn(key, data)

    def test_lookup_matches_the_web_form_payload(self):
        """The endpoint must not drift from what the web form renders."""
        from broiler.views import daily_entry_lookup_payload

        resp = self.client.get(
            "/api/v1/broiler/daily-entry-lookup",
            {"farm": self.farm.id, "date": "2026-07-10"})
        expected = daily_entry_lookup_payload(str(self.farm.id), "2026-07-10")
        self.assertEqual(resp.json()["data"]["age_days"], expected["age_days"])
        self.assertEqual(resp.json()["data"]["live_birds"], expected["live_birds"])

    def test_lookup_survives_a_batch_whose_breed_has_no_standard(self):
        """Regression: the live-bird walk needs ``Sum`` for any batch, but the
        import sat inside the breed-standard branch, so a batch with no breed
        (or no standard for it) raised UnboundLocalError and 500'd — on the web
        form as much as the API."""
        resp = self.client.get(
            "/api/v1/broiler/daily-entry-lookup",
            {"farm": self.farm.id, "date": "2026-07-10"})
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()["data"]
        self.assertIsNone(data["std_feed_kg"])
        self.assertEqual(data["bs_curve"], [])

    def test_stock_lookup_returns_the_prior_closing_balance(self):
        DailyEntry.objects.create(
            date=date(2026, 7, 10), supervisor=self.farm.supervisor,
            farm=self.farm, batch=self.batch,
            feed_1=self.feed, feed_1_qty=Decimal("40"), feed_1_stock=Decimal("160"))
        resp = self.client.get(
            "/api/v1/broiler/daily-entry-stock",
            {"farm": self.farm.id, "item": self.feed.id, "date": "2026-07-11"})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["data"]["stock"], "160.00")

    def test_stock_lookup_is_zero_without_the_required_params(self):
        resp = self.client.get("/api/v1/broiler/daily-entry-stock", {"farm": self.farm.id})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["stock"], "0")
