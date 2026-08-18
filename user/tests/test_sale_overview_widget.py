"""Sale Overview: one day's sales, and the money taken that day against them.

The sale sheet for a trading day — what went out, at what weight and rate, and
what was collected while it went. The Difference is that day's billing less
that day's receipts, so it is what is still to come in on this lot rather than
the ledger's outstanding balance, which is what Receivables is for.

With no date chosen it stands at the last day that had a sale: the trade is a
few days a week, and a card dated to a morning nothing happened on invites the
reader to think nothing has happened at all.

Date only, and unfiltered otherwise: a receipt is booked against a customer and
a location, never against a farm, so a farm filter would narrow the sales and
leave the receipts whole. The card says so rather than showing the figure.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from broiler.models import (BirdSale, BirdSaleReceipt, Branch, BroilerBatch,
                            BroilerFarm, Farmer, Region, Supervisor)
from account.models import AccountType, ChartOfAccount, CompanyProfile
from inventory.models import Warehouse
from user.models import GroupAccessProfile, GroupTabPermission
from user.services.dashboard_widgets import dashboard_widgets


class SaleOverviewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = get_user_model().objects.create_superuser(
            "soadmin", "so@x.com", "Str0ngPass!")
        self.today = timezone.localdate()

        self.region = Region.objects.create(description="East")
        self.branch = Branch.objects.create(branch_name="Akbarpur",
                                            region=self.region, prefix="AKB")
        self.sup = Supervisor.objects.create(branch=self.branch, name="R. Verma")
        self.farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=self.branch, supervisor=self.sup, farmer=self.farmer,
            region=self.region, line="Line A", farm_name="Yadav Farm",
            farm_capacity=9000)
        self.counter = Warehouse.objects.create(name="Akbarpur Store")
        kind = AccountType.objects.create(name="Cash", code_range_start=100000,
                                         code_range_end=199999, report="BS")
        self.till = ChartOfAccount.objects.create(
            company=CompanyProfile.get_solo(), code="100001",
            description="Cash in Hand", account_type=kind)

    # ---- fixtures -----------------------------------------------------------

    def sell(self, birds, weight, rate, age=38, when=None):
        """A lifting off a flock that was `age` days old on the day it went."""
        when = when or self.today
        batch = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name=f"B-{BroilerBatch.objects.count() + 1}",
            start_date=when - timedelta(days=age))
        return BirdSale.objects.create(
            farm=self.farm, batch=batch, date=when, birds=birds,
            net_weight=Decimal(weight), rate=Decimal(rate))

    def receipt(self, amount, mode="Cash", when=None):
        # A receipt is booked at a location, never at a farm — which is the
        # whole reason this card cannot answer the farm filter.
        return BirdSaleReceipt.objects.create(
            date=when or self.today, mode=mode, amount=Decimal(amount),
            location=self.counter, receipt_account=self.till)

    def card(self, user=None, filters=None):
        return next((w for w in dashboard_widgets(user or self.admin, filters,
                                                  use_cache=False)
                     if w["key"] == "sale_overview"), None)

    def stat(self, label, **kw):
        return next(s for s in self.card(**kw)["stats"] if s["label"] == label)

    # ---- what was sold ------------------------------------------------------

    def test_it_totals_the_birds_the_weight_and_the_value(self):
        self.sell(419, "775.50", "89")
        self.assertEqual(self.stat("Sold birds")["value"], "419")
        self.assertEqual(self.stat("Sold weight")["value"], "775.50 Kg")
        # 775.50 kg at ₹89 — the model works the amount out itself.
        self.assertEqual(self.stat("Sale value")["value"], "₹69,020")

    def test_the_sale_rate_is_the_value_over_the_weight(self):
        self.sell(419, "775.50", "89")
        self.assertEqual(self.stat("Avg sale rate")["value"], "₹89.00")

    def test_the_body_weight_is_the_weight_over_the_birds(self):
        self.sell(400, "800.00", "90")
        self.assertEqual(self.stat("Mean body wt")["value"], "2.000 Kg")

    def test_the_mean_age_is_weighted_by_the_birds_that_went(self):
        """A 4,000-bird lifting and a 100-bird one are not two equal opinions
        about the age a flock leaves at."""
        self.sell(4000, "8000.00", "90", age=40)
        self.sell(100, "150.00", "90", age=20)
        # (40 x 4000 + 20 x 100) / 4100
        self.assertEqual(self.stat("Mean age")["value"], "39.51 d")

    def test_a_flock_with_no_placement_date_is_left_out_of_the_age(self):
        sale = self.sell(1000, "2000.00", "90", age=35)
        BirdSale.objects.create(farm=self.farm, date=self.today, birds=500,
                                net_weight=Decimal("900"), rate=Decimal("90"))
        self.assertEqual(self.stat("Mean age")["value"], "35.00 d")
        self.assertEqual(self.stat("Sold birds")["value"], "1,500")   # still counted
        self.assertTrue(sale.batch_id)

    # ---- what came back -----------------------------------------------------

    def test_cash_and_bank_are_split_and_everything_banked_counts_as_bank(self):
        self.sell(400, "800.00", "90")
        self.receipt("5000", mode="Cash")
        self.receipt("20000", mode="Bank Transfer")
        self.receipt("18000", mode="Cheque")
        self.receipt("5000", mode="UPI")
        self.assertEqual(self.stat("Cash received")["value"], "₹5,000")
        self.assertEqual(self.stat("Bank received")["value"], "₹43,000")

    def test_the_difference_is_what_is_still_to_come_in_on_the_day(self):
        self.sell(419, "775.50", "89")            # ₹69,020
        self.receipt("43000", mode="Bank Transfer")
        self.assertEqual(self.stat("Difference")["value"], "₹26,020")
        self.assertEqual(self.stat("Difference")["tone"], "bad")

    def test_money_in_ahead_of_the_bill_is_not_a_shortfall(self):
        self.sell(100, "200.00", "90")            # ₹18,000
        self.receipt("20000", mode="Cash")
        self.assertEqual(self.stat("Difference")["tone"], "good")

    # ---- the day the card is showing ----------------------------------------

    def test_it_shows_one_day_not_a_running_total(self):
        """The sale sheet for a trading day: what went out, and what was
        collected while it went."""
        self.sell(300, "600.00", "90", when=self.today - timedelta(days=20))
        self.sell(100, "200.00", "90", when=self.today - timedelta(days=9))
        self.assertEqual(self.stat("Sold birds")["value"], "100")

    def test_with_no_date_chosen_it_stands_at_the_last_day_that_had_a_sale(self):
        self.sell(100, "200.00", "90", when=self.today - timedelta(days=9))
        note = self.card()["note"]
        self.assertIn((self.today - timedelta(days=9)).strftime("%d %b %Y"), note)
        self.assertIn("the last day with a sale", note)

    def test_the_receipts_are_that_day_s_too(self):
        """Both sides of the difference are cut at the same day, or the card
        would put money against a sale it is not showing."""
        self.sell(100, "200.00", "90", when=self.today - timedelta(days=9))
        self.receipt("5000", mode="Cash", when=self.today - timedelta(days=9))
        self.receipt("7000", mode="Cash", when=self.today - timedelta(days=2))
        self.assertEqual(self.stat("Cash received")["value"], "₹5,000")

    def test_a_chosen_day_with_no_sale_says_when_the_last_one_was(self):
        self.sell(100, "200.00", "90", when=self.today - timedelta(days=9))
        card = self.card(filters={"date": self.today})
        self.assertIn("No bird sales on this day", card["note"])
        self.assertIn((self.today - timedelta(days=9)).strftime("%d %b %Y"), card["note"])

    def test_a_business_that_has_never_sold_says_that_instead(self):
        self.assertEqual(self.card()["note"], "No bird sales recorded yet.")

    def test_a_chosen_day_needs_no_explaining(self):
        self.sell(100, "200.00", "90")
        self.assertIsNone(self.card(filters={"date": self.today})["note"])

    # ---- honesty about the filters -----------------------------------------

    def test_it_says_the_farm_filter_does_not_apply(self):
        """A receipt carries no farm, so narrowing the sales alone would make
        the difference between them an arithmetic accident."""
        self.sell(100, "200.00", "90")
        card = self.card(filters={"farm": self.farm.id, "branch": self.branch.id})
        self.assertIn("Farm", card["ignored"])
        self.assertIn("Branch", card["ignored"])

    # ---- who may see it -----------------------------------------------------

    def test_a_user_limited_to_part_of_the_business_is_told_why_it_is_empty(self):
        User = get_user_model()
        clerk = User.objects.create_user("soclerk", "c@x.com", "Str0ngPass!")
        group = Group.objects.create(name="Akbarpur Only")
        clerk.groups.add(group)
        GroupTabPermission.objects.create(group=group, tab_code="bird_sale_list",
                                          can_view=True)
        access = GroupAccessProfile.objects.create(group=group, all_branches=False)
        access.branches.add(self.branch)

        self.sell(419, "775.50", "89")
        card = self.card(user=clerk)
        self.assertEqual(card["stats"], [])
        self.assertIn("every branch", card["note"])

    def test_it_is_gated_on_the_bird_sale_register(self):
        User = get_user_model()
        blind = User.objects.create_user("soblind", "b@x.com", "Str0ngPass!")
        group = Group.objects.create(name="Stock Only")
        blind.groups.add(group)
        GroupTabPermission.objects.create(group=group, tab_code="negative_stock_report",
                                          can_view=True)
        self.assertIsNone(self.card(user=blind))
