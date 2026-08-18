"""Lifting Details on the dashboard: the shape of the day, before the detail.

A lifting is the one broiler transaction nobody at the desk witnesses — the
birds leave the farm and the branch is billed for whatever the slip says. The
card answers how many went out, how many birds, what weight and across how many
farms; the register behind it has the rest.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from broiler.models import (BirdSale, Branch, BroilerFarm, Farmer, Region,
                            Supervisor)
from user.models import GroupTabPermission
from user.services.dashboard_widgets import dashboard_widgets


class LiftingWidgetTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = get_user_model().objects.create_superuser(
            "lwadmin", "lw@x.com", "Str0ngPass!")
        self.today = timezone.localdate()

        self.region = Region.objects.create(description="East")
        self.branch = Branch.objects.create(branch_name="Akbarpur",
                                            region=self.region, prefix="AKB")
        self.sup = Supervisor.objects.create(branch=self.branch, name="R. Verma")
        self.farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = self.make_farm("Yadav Farm")

    def make_farm(self, name, line="Line A", branch=None):
        return BroilerFarm.objects.create(
            branch=branch or self.branch, supervisor=self.sup, farmer=self.farmer,
            region=self.region, line=line, farm_name=name, farm_capacity=5000)

    def lift(self, birds, weight, farm=None, when=None):
        # net_weight is a Decimal field the model divides by on save, so it is
        # given as one rather than as the string a form would post.
        return BirdSale.objects.create(
            farm=farm or self.farm, date=when or self.today,
            birds=birds, net_weight=Decimal(weight))

    def card(self, user=None, filters=None):
        return next((w for w in dashboard_widgets(user or self.admin, filters,
                                                  use_cache=False)
                     if w["key"] == "liftings"), None)

    def stat(self, label, **kw):
        return next(s for s in self.card(**kw)["stats"] if s["label"] == label)

    # ---- the day's figures --------------------------------------------------

    def test_it_counts_the_day_s_liftings_birds_and_weight(self):
        self.lift(12800, "256.00")
        self.lift(15600, "312.00")
        self.assertEqual(self.stat("Liftings")["value"], "2")
        self.assertEqual(self.stat("Birds lifted")["value"], "28,400")
        self.assertEqual(self.stat("Net weight")["value"], "568 Kg")

    def test_it_counts_the_farms_covered_not_the_liftings(self):
        """Two loads off one farm is one farm covered."""
        self.lift(1000, "20.00")
        self.lift(1000, "20.00")
        self.lift(1000, "20.00", farm=self.make_farm("Second Farm"))
        self.assertEqual(self.stat("Farms covered")["value"], "2")

    def test_yesterday_is_left_out_of_today_s_figures(self):
        self.lift(500, "10.00", when=self.today - timedelta(days=1))
        self.lift(700, "14.00")
        self.assertEqual(self.stat("Liftings")["value"], "1")
        self.assertEqual(self.stat("Birds lifted")["value"], "700")

    # ---- against yesterday --------------------------------------------------

    def test_a_count_is_read_against_the_day_before(self):
        """Eighteen liftings is a busy day or a slow one; the card says which."""
        for _ in range(2):
            self.lift(100, "2.00", when=self.today - timedelta(days=1))
        for _ in range(5):
            self.lift(100, "2.00")
        self.assertEqual(self.stat("Liftings")["sub"], "3 more than yesterday")

    def test_a_quieter_day_says_so(self):
        for _ in range(4):
            self.lift(100, "2.00", when=self.today - timedelta(days=1))
        self.lift(100, "2.00")
        self.assertEqual(self.stat("Liftings")["sub"], "3 fewer than yesterday")

    def test_a_day_matching_the_one_before_says_so(self):
        self.lift(100, "2.00", when=self.today - timedelta(days=1))
        self.lift(100, "2.00")
        self.assertEqual(self.stat("Liftings")["sub"], "same as yesterday")

    def test_the_first_liftings_after_a_blank_day_are_not_called_an_increase(self):
        self.lift(100, "2.00")
        self.assertEqual(self.stat("Liftings")["sub"], "none yesterday")

    # ---- the rows -----------------------------------------------------------

    def test_the_latest_liftings_are_listed_newest_first(self):
        self.lift(1000, "20.00")
        self.lift(2000, "40.00", farm=self.make_farm("Second Farm"))
        rows = self.card()["rows"]
        self.assertEqual(rows[0]["label"], "Second Farm")
        self.assertEqual(rows[0]["value"], "2,000 birds")
        self.assertEqual(rows[0]["meta"], "40 kg")

    def test_a_quiet_day_says_when_the_last_lifting_was(self):
        """Birds go out a few times a week. A card that says nothing but nought
        reads as a card that is broken, so it says which it is."""
        self.lift(226, "512.00", when=self.today - timedelta(days=14))
        card = self.card()
        self.assertIn("No liftings on this day", card["note"])
        self.assertIn("226 birds, 14 days ago", card["note"])
        self.assertEqual(card["rows"], [])

    def test_a_farm_that_has_never_lifted_says_that_instead(self):
        self.assertEqual(self.card()["note"], "No liftings recorded here yet.")

    def test_the_last_lifting_is_read_through_the_filter_too(self):
        """Another branch's lifting is not this filter's last one."""
        far = Branch.objects.create(branch_name="Bahraich", region=self.region,
                                    prefix="BHR")
        self.lift(500, "10.00", farm=self.make_farm("Far Farm", branch=far),
                  when=self.today - timedelta(days=2))
        card = self.card(filters={"branch": self.branch.id})
        self.assertEqual(card["note"], "No liftings recorded here yet.")

    # ---- filters ------------------------------------------------------------

    def test_it_answers_the_farm_filter(self):
        other = self.make_farm("Second Farm")
        self.lift(1000, "20.00")
        self.lift(9000, "180.00", farm=other)
        self.assertEqual(self.stat("Birds lifted", filters={"farm": other.id})["value"],
                         "9,000")

    def test_it_answers_the_date_filter(self):
        self.lift(4000, "80.00", when=self.today - timedelta(days=3))
        self.assertEqual(
            self.stat("Birds lifted",
                      filters={"date": self.today - timedelta(days=3)})["value"],
            "4,000")

    def test_it_admits_no_filter_was_ignored(self):
        """Every filter reaches a lifting's farm, so none is left unapplied."""
        self.lift(1000, "20.00")
        card = self.card(filters={"branch": self.branch.id, "farm": self.farm.id})
        self.assertIsNone(card["ignored"])

    # ---- permission ---------------------------------------------------------

    def test_it_is_gated_on_the_bird_sale_register(self):
        User = get_user_model()
        clerk = User.objects.create_user("lwclerk", "c@x.com", "Str0ngPass!")
        group = Group.objects.create(name="Liftings Only")
        clerk.groups.add(group)
        GroupTabPermission.objects.create(group=group, tab_code="bird_sale_list",
                                          can_view=True)
        self.assertIsNotNone(self.card(user=clerk))

        blind = User.objects.create_user("lwblind", "b@x.com", "Str0ngPass!")
        other = Group.objects.create(name="Stock Only")
        blind.groups.add(other)
        GroupTabPermission.objects.create(group=other, tab_code="negative_stock_report",
                                          can_view=True)
        self.assertIsNone(self.card(user=blind))

    def test_a_lifting_off_another_branch_s_farm_is_not_counted(self):
        """A scoped user's card must not total farms they cannot open."""
        User = get_user_model()
        clerk = User.objects.create_user("lwscoped", "s@x.com", "Str0ngPass!")
        group = Group.objects.create(name="Akbarpur Liftings")
        clerk.groups.add(group)
        GroupTabPermission.objects.create(group=group, tab_code="bird_sale_list",
                                          can_view=True)
        from user.models import GroupAccessProfile

        # Scoped to Akbarpur alone: "all branches" off, this one selected.
        access = GroupAccessProfile.objects.create(group=group, all_branches=False)
        access.branches.add(self.branch)

        far = Branch.objects.create(branch_name="Bahraich", region=self.region,
                                    prefix="BHR")
        self.lift(1000, "20.00")
        self.lift(8000, "160.00", farm=self.make_farm("Far Farm", branch=far))
        self.assertEqual(self.stat("Birds lifted", user=clerk)["value"], "1,000")

    # ---- the chart ----------------------------------------------------------

    def test_the_chart_is_the_day_s_birds_and_weight_by_branch(self):
        far = Branch.objects.create(branch_name="Bahraich", region=self.region,
                                    prefix="BHR")
        self.lift(1000, "2000.00")
        self.lift(400, "900.00", farm=self.make_farm("Far Farm", branch=far))

        chart = self.card()["chart"]
        self.assertEqual([s["label"] for s in chart["series"]], ["Birds", "Weight"])
        self.assertEqual([(g["label"], g["values"]) for g in chart["groups"]],
                         [("Akbarpur", [1000, 2000.0]), ("Bahraich", [400, 900.0])])

    def test_a_branch_that_lifted_nothing_is_left_off_the_chart(self):
        """A bar of nought says a branch had a bad day; it had no lifting at all."""
        Branch.objects.create(branch_name="Bahraich", region=self.region, prefix="BHR")
        self.lift(1000, "2000.00")
        self.assertEqual([g["label"] for g in self.card()["chart"]["groups"]],
                         ["Akbarpur"])

    def test_a_day_with_no_liftings_has_no_chart_to_draw(self):
        self.assertIsNone(self.card()["chart"])

    def test_the_average_weight_is_the_figure_a_lifting_is_judged_on(self):
        self.lift(1000, "2100.00")
        self.assertEqual(self.stat("Avg wt")["value"], "2.10 Kg")

    def test_the_average_is_not_divided_by_a_flock_of_none(self):
        self.lift(0, "0.00")
        self.assertEqual(self.stat("Avg wt")["value"], "—")
