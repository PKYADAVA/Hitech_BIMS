"""Sale Overview: one day's sales, and the money taken that day against them.

The sale sheet for a trading day — what went out, at what weight and rate, and
what was collected while it went. The Difference is that day's billing less
that day's receipts, so it is what is still to come in on this lot rather than
the ledger's outstanding balance, which is what Receivables is for.

With no date chosen it stands at the last day that had a sale: the trade is a
few days a week, and a card dated to a morning nothing happened on invites the
reader to think nothing has happened at all.

Date and Branch. A receipt is booked at an *office*, and the Office → Branch
master (inventory.Mapping, type sector_branch) says which branch an office
belongs to — so both halves narrow to the same branch and the difference
between them still means something. Line, Supervisor and Farm have no such
bridge, and the card says it could not apply them.
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
from inventory.models import Item, ItemCategory, StockTransfer, Warehouse
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

    def test_a_batch_with_no_start_date_still_ages_off_its_placement(self):
        """A batch created straight from a chicks placement carries no
        start_date at all (see broiler.views._placement_date) — one such
        lifting used to blank the whole card's Mean age rather than falling
        back to the placement that actually dates it."""
        chick_cat = ItemCategory.objects.create(name="Day Old Chicks")
        chick = Item.objects.create(item_code="CHK-1", description="Day Old Chick",
                                    category=chick_cat, standard_cost_per_unit=35)
        placed = self.today - timedelta(days=40)
        batch = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="B-UNDATED", start_date=None)
        StockTransfer.objects.create(
            date=placed, item=chick, quantity=4000,
            purchase_rate=Decimal("35"), rate=Decimal("35"),
            from_location_type="warehouse", from_warehouse=self.counter,
            to_location_type="farm", to_farm=self.farm, to_batch=batch)
        BirdSale.objects.create(farm=self.farm, batch=batch, date=self.today,
                                birds=4000, net_weight=Decimal("8000"), rate=Decimal("90"))
        self.assertEqual(self.stat("Mean age")["value"], "40.00 d")

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
        the difference between them an arithmetic accident. Branch is the one
        that does apply — an office knows its branch, see the branch tests."""
        self.sell(100, "200.00", "90")
        card = self.card(filters={"farm": self.farm.id, "branch": self.branch.id})
        self.assertIn("Farm", card["ignored"])
        self.assertNotIn("Branch", card["ignored"])

    # ---- who may see it -----------------------------------------------------

    def scoped_user(self, *branches, name="soclerk"):
        """A login that may see the bird sale register and only these branches."""
        User = get_user_model()
        clerk = User.objects.create_user(name, f"{name}@x.com", "Str0ngPass!")
        group = Group.objects.create(name=f"{name} scope")
        clerk.groups.add(group)
        GroupTabPermission.objects.create(group=group, tab_code="bird_sale_list",
                                          can_view=True)
        access = GroupAccessProfile.objects.create(group=group, all_branches=False)
        for branch in branches:
            access.branches.add(branch)
        return clerk

    def test_a_user_limited_to_one_branch_sees_that_branch_s_sheet(self):
        """It used to refuse them the card outright, because scoping the sales
        and leaving the receipts whole would have handed a branch manager the
        rest of the country's money. The offices are mapped now, so both halves
        narrow together and they get their own branch's sheet."""
        self.sell(419, "775.50", "89")
        card = self.card(user=self.scoped_user(self.branch))
        self.assertEqual(next(s for s in card["stats"]
                              if s["label"] == "Sold birds")["value"], "419")
        self.assertIsNone(card["ignored"])

    def test_a_user_permitted_no_branch_at_all_sees_nothing(self):
        """An empty scope is a real limit that permits nothing, and must not be
        collapsed into "no limit"."""
        self.sell(419, "775.50", "89")
        card = self.card(user=self.scoped_user())
        self.assertEqual([s["value"] for s in card["stats"]], ["0"])
        self.assertIn("does not include a branch", card["note"])

    def test_it_is_gated_on_the_bird_sale_register(self):
        User = get_user_model()
        blind = User.objects.create_user("soblind", "b@x.com", "Str0ngPass!")
        group = Group.objects.create(name="Stock Only")
        blind.groups.add(group)
        GroupTabPermission.objects.create(group=group, tab_code="negative_stock_report",
                                          can_view=True)
        self.assertIsNone(self.card(user=blind))


class SaleOverviewBranchTests(SaleOverviewTests):
    """Branch-wise, through the Office → Branch master.

    The card used to answer "Branch does not apply here", because a receipt
    carries an office and no farm. The office knows its branch — it is a row in
    inventory.Mapping, edited from the Office → Branch master — so both halves
    can be narrowed to the same branch after all.
    """

    def setUp(self):
        super().setUp()
        from inventory.models import Mapping

        self.far = Branch.objects.create(branch_name="Bahraich",
                                         region=self.region, prefix="BHR")
        self.far_farm = BroilerFarm.objects.create(
            branch=self.far, supervisor=self.sup, farmer=self.farmer,
            region=self.region, line="Line B", farm_name="Far Farm",
            farm_capacity=9000)
        self.far_counter = Warehouse.objects.create(name="Bahraich Store")
        self.orphan = Warehouse.objects.create(name="Main Warehouse")
        # The mapping the master writes: this office belongs to that branch.
        Mapping.objects.create(type=Mapping.TYPE_SECTOR_BRANCH,
                               from_id=self.counter.id, to_id=self.branch.id)
        Mapping.objects.create(type=Mapping.TYPE_SECTOR_BRANCH,
                               from_id=self.far_counter.id, to_id=self.far.id)
        # self.orphan is deliberately left unmapped.

    def sell_at(self, farm, birds, weight, rate, when=None):
        when = when or self.today
        batch = BroilerBatch.objects.create(
            broiler_farm=farm, batch_name=f"F-{BroilerBatch.objects.count() + 1}",
            start_date=when - timedelta(days=38))
        return BirdSale.objects.create(farm=farm, batch=batch, date=when,
                                       birds=birds, net_weight=Decimal(weight),
                                       rate=Decimal(rate))

    def receipt_at(self, office, amount, when=None):
        return BirdSaleReceipt.objects.create(
            date=when or self.today, mode="Cash", amount=Decimal(amount),
            location=office, receipt_account=self.till)

    def test_the_sales_narrow_to_the_branch(self):
        self.sell_at(self.farm, 100, "200.00", "90")
        self.sell_at(self.far_farm, 900, "1800.00", "90")
        self.assertEqual(self.stat("Sold birds", filters={"branch": self.branch.id})["value"],
                         "100")
        self.assertEqual(self.stat("Sold birds", filters={"branch": self.far.id})["value"],
                         "900")

    def test_the_money_follows_the_office_it_was_taken_at(self):
        self.sell_at(self.farm, 100, "200.00", "90")
        self.sell_at(self.far_farm, 100, "200.00", "90")
        self.receipt_at(self.counter, "5000")
        self.receipt_at(self.far_counter, "7000")
        self.assertEqual(self.stat("Cash received", filters={"branch": self.branch.id})["value"],
                         "₹5,000")
        self.assertEqual(self.stat("Cash received", filters={"branch": self.far.id})["value"],
                         "₹7,000")

    def test_branch_is_no_longer_reported_as_inapplicable(self):
        self.sell_at(self.farm, 100, "200.00", "90")
        self.assertIsNone(self.card(filters={"branch": self.branch.id})["ignored"])

    def test_the_farm_side_filters_still_say_they_do_not_apply(self):
        """Line, Supervisor and Farm have no bridge to a receipt."""
        self.sell_at(self.farm, 100, "200.00", "90")
        card = self.card(filters={"branch": self.branch.id, "line": "Line A"})
        self.assertIn("Line", card["ignored"])

    def test_money_at_an_unmapped_office_is_named_not_dropped(self):
        """A total that silently loses a receipt is worse than one that admits
        what it left out."""
        self.sell_at(self.farm, 100, "200.00", "90")
        self.receipt_at(self.orphan, "9000")
        note = self.card(filters={"branch": self.branch.id})["note"]
        self.assertIn("9,000", note)
        self.assertIn("no branch mapped", note)

    def test_nothing_is_said_about_orphans_when_there_are_none(self):
        self.sell_at(self.farm, 100, "200.00", "90")
        self.receipt_at(self.counter, "5000")
        self.assertNotIn("no branch mapped",
                         self.card(filters={"branch": self.branch.id})["note"] or "")

    def test_a_branch_lands_on_its_own_last_selling_day(self):
        """Picking Akbarpur and landing on the day Bahraich last sold is a card
        full of noughts about the wrong place."""
        self.sell_at(self.far_farm, 500, "1000.00", "90")                     # today
        self.sell_at(self.farm, 100, "200.00", "90",
                     when=self.today - timedelta(days=6))
        card = self.card(filters={"branch": self.branch.id})
        self.assertEqual(next(s for s in card["stats"]
                              if s["label"] == "Sold birds")["value"], "100")
        self.assertIn((self.today - timedelta(days=6)).strftime("%d %b %Y"), card["note"])

    def test_money_on_a_day_with_no_lifting_is_still_shown(self):
        """A payment against an earlier lifting is not an empty day — hiding it
        was how a 2,00,000 receipt showed up nowhere at all."""
        self.receipt_at(self.counter, "200000")
        card = self.card(filters={"date": self.today})
        vals = {s["label"]: s["value"] for s in card["stats"]}
        self.assertEqual(vals["Cash received"], "₹2,00,000")
        self.assertEqual(vals["Difference"], "₹-2,00,000")

    def test_a_branch_with_no_office_mapped_receives_nothing(self):
        """Varanasi has no office of its own, so no receipt can be its."""
        lone = Branch.objects.create(branch_name="Varanasi", region=self.region,
                                     prefix="VNS")
        farm = BroilerFarm.objects.create(
            branch=lone, supervisor=self.sup, farmer=self.farmer,
            region=self.region, line="L", farm_name="Lone Farm", farm_capacity=100)
        self.sell_at(farm, 50, "100.00", "90")
        self.receipt_at(self.counter, "5000")
        self.assertEqual(self.stat("Cash received", filters={"branch": lone.id})["value"],
                         "₹0")

    def test_a_scoped_user_sees_only_their_own_branch_s_sales(self):
        self.sell_at(self.farm, 100, "200.00", "90")
        self.sell_at(self.far_farm, 900, "1800.00", "90")
        card = self.card(user=self.scoped_user(self.branch))
        self.assertEqual(next(s for s in card["stats"]
                              if s["label"] == "Sold birds")["value"], "100")

    def test_a_scoped_user_sees_only_the_money_taken_at_their_own_offices(self):
        """The half the old gate could not narrow, and the reason it refused
        them the card at all."""
        self.sell_at(self.farm, 100, "200.00", "90")
        self.receipt_at(self.counter, "5000")
        self.receipt_at(self.far_counter, "7000")
        self.assertEqual(self.stat("Cash received", user=self.scoped_user(self.branch))
                         ["value"], "₹5,000")

    def test_asking_for_a_branch_outside_the_scope_yields_nothing(self):
        """Not that branch's figures, and not everything either — the filter is
        a request, and their access is what answers it."""
        self.sell_at(self.far_farm, 900, "1800.00", "90")
        card = self.card(user=self.scoped_user(self.branch),
                         filters={"branch": self.far.id})
        self.assertEqual([s["value"] for s in card["stats"]], ["0"])
        # Not the same empty as having no branch at all — that one says to ask
        # an administrator, this one says to pick another branch.
        self.assertIn("outside your access", card["note"])

    def test_money_at_an_unmapped_office_is_not_named_to_a_scoped_user(self):
        """Money outside every branch is outside their access too."""
        self.sell_at(self.farm, 100, "200.00", "90")
        self.receipt_at(self.orphan, "9000")
        note = self.card(user=self.scoped_user(self.branch))["note"] or ""
        self.assertNotIn("9,000", note)

    def test_a_scoped_user_lands_on_their_own_branch_s_last_selling_day(self):
        self.sell_at(self.far_farm, 500, "1000.00", "90")
        self.sell_at(self.farm, 100, "200.00", "90",
                     when=self.today - timedelta(days=6))
        card = self.card(user=self.scoped_user(self.branch))
        self.assertEqual(next(s for s in card["stats"]
                              if s["label"] == "Sold birds")["value"], "100")

    def test_two_branches_in_scope_are_added_together(self):
        self.sell_at(self.farm, 100, "200.00", "90")
        self.sell_at(self.far_farm, 900, "1800.00", "90")
        self.receipt_at(self.counter, "5000")
        self.receipt_at(self.far_counter, "7000")
        user = self.scoped_user(self.branch, self.far)
        self.assertEqual(self.stat("Sold birds", user=user)["value"], "1,000")
        self.assertEqual(self.stat("Cash received", user=user)["value"], "₹12,000")
