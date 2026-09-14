"""The sales incentive, and the two limits the master defines for it.

The Growing Charge master offers three things under Sales Incentives: the rate
bands, a Maximum Prod. Cost, and a Maximum Rate Incentive. Only the bands were
read. The other two were captured by the form, saved to the scheme and used by
nothing, so a scheme could be configured with both and neither changed a rupee
of what a farmer was paid — the quietest kind of wrong, because the screen
shows the limit sitting there being obeyed.

The reported batch: a sale rate of 106.62 against a 105-130 band at 0.10, and a
production cost of 93.06 against a Maximum Prod. Cost of 90.00. It was paid the
incentive. Under the limit it should have earned none.

Both limits are optional and both store as 0 when nobody fills them in, which
is the trap in applying them: read literally, a blank Maximum Prod. Cost means
no batch ever qualifies, and every scheme that never set one would stop paying
the incentive it does define. That case has its own tests below.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from broiler.models import (Branch, GCSalesIncentive, GrowingChargeScheme,
                            Region)
from broiler.views import _sales_incentive_per_kg


class SalesIncentiveTests(TestCase):

    def setUp(self):
        self.region = Region.objects.create(description="East")
        self.branch = Branch.objects.create(branch_name="Akbarpur",
                                            region=self.region, prefix="AKB")

    def scheme(self, bands=((105, 130, "0.10"),), **limits):
        today = timezone.localdate()
        s = GrowingChargeScheme.objects.create(
            region=self.region, branch=self.branch, schema_name="Test",
            from_date=today - timedelta(days=365), to_date=today + timedelta(days=365),
            **limits)
        for lo, hi, rate in bands:
            GCSalesIncentive.objects.create(
                scheme=s, sale_rate_from=lo, sale_rate_to=hi,
                sales_incentive=Decimal(rate))
        return s

    def rate(self, scheme, sale_rate, prod_cost=None):
        return _sales_incentive_per_kg(scheme, Decimal(str(sale_rate)),
                                       None if prod_cost is None else Decimal(str(prod_cost)))

    # --- the bands themselves --------------------------------------------

    def test_it_accrues_per_rupee_above_the_band_floor(self):
        """The master's own example: 105-130 at 0.10, sold at 115."""
        self.assertEqual(self.rate(self.scheme(), 115), Decimal("1.00"))

    def test_below_the_floor_there_is_nothing(self):
        self.assertEqual(self.rate(self.scheme(), 104), Decimal("0"))
        self.assertEqual(self.rate(self.scheme(), 105), Decimal("0"))

    def test_above_the_ceiling_it_stops_accruing(self):
        """A sale rate past the top of the bands earns the bands' whole span
        and no more — 130 is as far as this scheme rewards."""
        self.assertEqual(self.rate(self.scheme(), 130), Decimal("2.50"))
        self.assertEqual(self.rate(self.scheme(), 200), Decimal("2.50"))

    def test_it_carries_across_bands(self):
        """Progressive, like tax brackets: the second band pays on what is
        above its own floor, not on the whole sale rate."""
        scheme = self.scheme(bands=((100, 110, "0.10"), (110, 120, "0.20")))
        # (110-100)*0.10 + (115-110)*0.20
        self.assertEqual(self.rate(scheme, 115), Decimal("2.00"))

    # --- Maximum Prod. Cost ----------------------------------------------

    def test_a_batch_that_cost_too_much_earns_nothing(self):
        """The reported case. 93.06 against a limit of 90.00 — a good sale
        rate on a flock that cost too much to grow is not the farmer's to
        share in."""
        scheme = self.scheme(maximum_prod_cost=Decimal("90"))
        self.assertEqual(self.rate(scheme, "106.62", "93.06"), Decimal("0"))

    def test_a_batch_within_the_limit_is_paid_in_full(self):
        scheme = self.scheme(maximum_prod_cost=Decimal("90"))
        self.assertEqual(self.rate(scheme, 115, "88.00"), Decimal("1.00"))

    def test_the_limit_itself_still_qualifies(self):
        """It is a maximum, so reaching it is allowed. Off-by-one here is a
        farmer losing an incentive for hitting the number exactly."""
        scheme = self.scheme(maximum_prod_cost=Decimal("90"))
        self.assertEqual(self.rate(scheme, 115, "90.00"), Decimal("1.00"))

    def test_an_unset_limit_does_not_bar_everything(self):
        """Blank stores as 0. Read literally that is "no batch may cost
        anything", which would silently switch off the incentive on every
        scheme that never filled the field in."""
        scheme = self.scheme()                       # maximum_prod_cost = 0
        self.assertEqual(self.rate(scheme, 115, "93.06"), Decimal("1.00"))

    def test_a_missing_production_cost_does_not_bar_it_either(self):
        """A caller with no cost to hand gets the bands, not a silent zero."""
        scheme = self.scheme(maximum_prod_cost=Decimal("90"))
        self.assertEqual(self.rate(scheme, 115), Decimal("1.00"))

    # --- Maximum Rate Incentive ------------------------------------------

    def test_the_per_kg_incentive_is_capped(self):
        """However far the sale rate climbs through the bands."""
        scheme = self.scheme(bands=((100, 200, "0.10"),),
                             maximum_rate_incentive=Decimal("3.00"))
        self.assertEqual(self.rate(scheme, 200), Decimal("3.00"))   # 10.00 uncapped

    def test_under_the_cap_it_is_left_alone(self):
        scheme = self.scheme(maximum_rate_incentive=Decimal("3.00"))
        self.assertEqual(self.rate(scheme, 115), Decimal("1.00"))

    def test_an_unset_cap_does_not_zero_the_incentive(self):
        """The same trap as the other limit, and the worse of the two: a cap
        of 0 taken literally pays nothing, ever."""
        scheme = self.scheme(bands=((100, 200, "0.10"),))
        self.assertEqual(self.rate(scheme, 200), Decimal("10.00"))

    def test_both_limits_together(self):
        """The cost gate is checked first: a batch that does not qualify earns
        nothing, which is not the same as earning the capped amount."""
        scheme = self.scheme(bands=((100, 200, "0.10"),),
                             maximum_prod_cost=Decimal("90"),
                             maximum_rate_incentive=Decimal("3.00"))
        self.assertEqual(self.rate(scheme, 200, "95.00"), Decimal("0"))
        self.assertEqual(self.rate(scheme, 200, "85.00"), Decimal("3.00"))

    def test_no_scheme_means_no_incentive(self):
        self.assertEqual(_sales_incentive_per_kg(None, Decimal("115")), Decimal("0"))
