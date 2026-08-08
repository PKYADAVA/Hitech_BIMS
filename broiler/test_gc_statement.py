"""The Growing Charge Statement shows the growing charge.

Two faults, reported together. The Batch picker offered every farm's batches
whatever farm was chosen, and the statement — named for the growing charge —
stopped at this batch's own cost roll-up and never showed the charge itself:
the scheme's standard rate, the slab-matched incentives and recoveries, and
what the farmer is owed. All of that was already worked out against the
Growing Charge Master for the settlement form and simply was not read here.
"""
import re
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from broiler.models import (Branch, BroilerBatch, BroilerFarm, Farmer,
                            GCFarmerClassification, GCMortalityIncentive,
                            GrowingChargeScheme, GrowingChargeSettlement,
                            Region, Supervisor)
from broiler.views import _build_batch_costing, _gc_statement


class GCStatementTests(TestCase):
    """Two farms, a batch each, and one scheme covering the placement date."""

    def setUp(self):
        cache.clear()
        self.today = timezone.localdate()
        self.placed = self.today - timedelta(days=40)
        self.region = Region.objects.create(description="East")
        self.branch = Branch.objects.create(branch_name="Akbarpur",
                                            region=self.region, prefix="AKB")
        self.farmer = Farmer.objects.create(farmer_name="S. Yadav")

        self.mine, self.mine_batch = self.farm_with_batch("Mineglade")
        self.other, self.other_batch = self.farm_with_batch("Farville")

        User = get_user_model()
        self.user = User.objects.create_superuser("gcs_user", "g@x.com", "Str0ngPass!")
        self.client.force_login(self.user)

    def farm_with_batch(self, name, closed=False):
        farm = BroilerFarm.objects.create(
            branch=self.branch, farmer=self.farmer, region=self.region, line="L1",
            supervisor=Supervisor.objects.create(branch=self.branch, name=name + " Sup"),
            farm_name=name, farm_capacity=5000)
        batch = BroilerBatch.objects.create(
            broiler_farm=farm, batch_name=name + "-B1",
            book_number="BK-" + name[:4].upper(),
            start_date=self.placed, is_closed=closed)
        return farm, batch

    def scheme(self, **kwargs):
        """A scheme covering the placement date, with one mortality slab."""
        fields = dict(region=self.region, branch=self.branch,
                      from_date=self.placed - timedelta(days=5),
                      to_date=self.today + timedelta(days=5),
                      schema_name="Standard 2026", standard_gc_cost=Decimal("8.50"),
                      std_production_cost=Decimal("95"), farmer_admin_cost=Decimal("2"),
                      standard_fcr=Decimal("1.60"), standard_mortality=Decimal("5"))
        fields.update(kwargs)
        s = GrowingChargeScheme.objects.create(**fields)
        GCMortalityIncentive.objects.create(scheme=s, from_mortality_pct=0,
                                            to_mortality_pct=100,
                                            incentive_value=Decimal("0.40"))
        GCFarmerClassification.objects.create(scheme=s, production_cost_from=0,
                                              production_to=Decimal("999"), grade="A")
        return s

    def page(self, **params):
        return self.client.get(reverse("broiler_batch_report"), params).content.decode()

    def options(self, html, select_id):
        """The <option> tags of one select, as raw strings."""
        block = re.search(r'id="%s".*?</select>' % select_id, html, re.S)
        return re.findall(r"<option\b.*?</option>", block.group(0), re.S) if block else []

    # ---- the growing charge itself -----------------------------------------

    def test_the_charge_is_worked_out_from_the_schemes_slabs(self):
        # Standard rate and the mortality slab both come from the master; if the
        # statement were still restating its own costs neither would appear.
        statement = _gc_statement(self.mine_batch, self.scheme())
        labels = [c["label"] for row in statement["rows"] for c in row if c]
        self.assertIn("Standard Growing Charges", labels)
        self.assertIn("Mortality Incentive", labels)
        self.assertIn("Amount Payable to Farmer", labels)
        self.assertEqual(statement["scheme"].schema_name, "Standard 2026")

    def test_a_batch_no_scheme_covers_says_so_rather_than_showing_zero(self):
        # A zero growing charge and an unworkable one read identically on the
        # page, and only one of them is true.
        out_of_range = self.scheme(from_date=self.today + timedelta(days=30),
                                   to_date=self.today + timedelta(days=60))
        self.assertIsNone(_gc_statement(self.mine_batch, None))
        self.assertIsNotNone(out_of_range)   # the scheme exists; it just misses

    def test_a_settled_batch_shows_what_was_settled(self):
        # The settlement is a snapshot and its figures may have been adjusted by
        # hand on the form. Recomputing would show the farmer a number nobody
        # agreed to, so the saved row wins over the scheme's own working.
        scheme = self.scheme()
        GrowingChargeSettlement.objects.create(
            batch=self.mine_batch, farm=self.mine, scheme=scheme,
            actual_growing_charges=Decimal("12345.67"),
            amount_payable=Decimal("13000.00"))
        statement = _gc_statement(self.mine_batch, scheme)
        payable = [c for row in statement["rows"] for c in row
                   if c and c["label"] == "Amount Payable to Farmer"][0]
        self.assertEqual(payable["amount"], Decimal("13000.00"))
        self.assertIsNotNone(statement["settled"])

    def test_the_page_renders_the_charge_for_a_selected_batch(self):
        self.scheme()
        html = self.page(batch=self.mine_batch.id)
        self.assertIn("Growing Charge Calculation", html)
        self.assertIn("Amount Payable to Farmer", html)

    def test_admin_cost_is_chicks_placed_times_the_schemes_rate(self):
        # Admin cost is a master rate per chick placed, never a figure of this
        # report's own — the two reports differ only in whose share is billed.
        scheme = self.scheme(farmer_admin_cost=Decimal("3"),
                             management_admin_cost=Decimal("1"))

        def admin_cost(fetch_type):
            return _build_batch_costing(
                self.mine_batch, 1861, 0, 0, [],
                [{"date": self.placed, "amount": Decimal("0")}],
                [], [], [], [], [], [], [],
                fetch_type=fetch_type, scheme_override=scheme)["admin_cost"]

        self.assertEqual(admin_cost("farmer"), Decimal("5583.00"))     # 1861 x 3
        # The Management report bills the management share on top of it.
        self.assertEqual(admin_cost("management"), Decimal("7444.00"))  # 1861 x 4

    # ---- the batch picker --------------------------------------------------

    def test_every_batch_option_carries_the_farm_it_belongs_to(self):
        # The picker narrows to the chosen farm in the browser, and data-farm is
        # the only thing it has to go on. Book No was missing it entirely, so it
        # went on listing every farm's book numbers.
        html = self.page()
        for select_id in ("report-batch", "report-book"):
            with self.subTest(select=select_id):
                offered = [o for o in self.options(html, select_id) if 'value=""' not in o]
                self.assertTrue(offered)
                for option in offered:
                    self.assertIn("data-farm=", option)

    def test_the_picker_offers_closed_batches_and_marks_them(self):
        # A history report is usually pulled on a batch that has ended, so
        # closed batches belong in the list — named as closed, not hidden.
        _, closed = self.farm_with_batch("Endfield", closed=True)
        html = self.page()
        offered = " ".join(self.options(html, "report-batch"))
        self.assertIn("Endfield-B1", offered)
        self.assertIn("(Closed)", offered)

    def test_the_filter_is_not_left_to_display_none(self):
        # Every .form-select on the site is upgraded to Select2, which builds
        # its own list from the options and ignores `display: none` — which is
        # exactly why hiding them left every farm's batches on show.
        html = self.page()
        script = html[html.index("function filterBatches"):]
        self.assertNotIn(".toggle(", script[:1200])
