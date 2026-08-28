"""Tax withheld from a growing charge.

Deducted at settlement, which is where the credit arises and therefore where
Indian practice puts it. The farmer is owed the charge less the tax; the tax is
owed to the department.

The thing these tests really guard is that the voucher and the Farmer Ledger
work the deduction out the same way. If they ever diverge, the reconciliation
report starts calling every farmer out by exactly their own TDS, which is a
false alarm in the one report meant to be trusted.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from account.coa_seed import seed_coa_templates
from account.models import (ChartOfAccount, CoATemplate, CompanyProfile,
                            FinancialYear)
from account.services import CoAGeneratorService
from broiler.models import (Branch, BroilerBatch, BroilerFarm, BroilerLine,
                            Farmer, GCPostingSettings, GrowingChargeSettlement,
                            Region, Supervisor, tds_on)
from broiler.services import gc_posting


class TdsTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_coa_templates()
        cls.company = CompanyProfile.get_solo()
        CoAGeneratorService(cls.company,
                            CoATemplate.objects.get(industry="Poultry")).generate()
        FinancialYear.objects.create(start_date=date(2026, 4, 1),
                                     end_date=date(2027, 3, 31), state="Open")
        cls.region = Region.objects.create(code="R1", description="East")
        cls.branch = Branch.objects.create(code="B1", branch_name="Akbarpur",
                                           region=cls.region)
        cls.supervisor = Supervisor.objects.create(branch=cls.branch, name="S. Kumar")
        cls.line = BroilerLine.objects.create(description="Line 1", region=cls.region,
                                              branch=cls.branch)
        cls.farmer = Farmer.objects.create(farmer_name="Abhishek Kumar Singh",
                                           tds_percent=Decimal("2"))
        cls.farm = BroilerFarm.objects.create(
            farm_name="Akbarpur Farm", branch=cls.branch, region=cls.region,
            supervisor=cls.supervisor, line=cls.line, farmer=cls.farmer,
            farm_capacity=5000)

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="accounts", password="x", email="a@example.com")
        self.client.force_login(self.user)
        self.batch = BroilerBatch.objects.create(
            batch_name="AKB-1109-1", broiler_farm=self.farm, start_date=date(2026, 5, 1))

    def settle(self, payable="50000", percent="2"):
        return GrowingChargeSettlement.objects.create(
            batch=self.batch, farm=self.farm, gc_date=date(2026, 6, 1),
            farmer_payable=Decimal(payable), tds_percent=Decimal(percent))

    def lines_of(self, voucher):
        return {(l.account.system_role or l.account.description): (l.debit, l.credit)
                for l in voucher.lines.select_related("account")}


class TheAmountTests(TdsTestCase):
    def test_two_percent_of_fifty_thousand(self):
        self.assertEqual(tds_on(self.settle("50000", "2")), Decimal("1000.00"))

    def test_no_rate_means_no_deduction(self):
        self.assertEqual(tds_on(self.settle("50000", "0")), Decimal("0.00"))

    def test_nothing_owed_means_nothing_withheld(self):
        self.assertEqual(tds_on(self.settle("0", "2")), Decimal("0.00"))

    def test_the_rate_is_snapshotted_not_looked_up_later(self):
        """Changing a farmer's rate must not restate a deduction already made."""
        settlement = self.settle("50000", "2")
        self.farmer.tds_percent = Decimal("10")
        self.farmer.save()
        settlement.refresh_from_db()
        self.assertEqual(tds_on(settlement), Decimal("1000.00"))


class TheEntryTests(TdsTestCase):
    def test_the_farmer_is_credited_net_and_the_department_the_rest(self):
        voucher = gc_posting.post_settlement(self.settle("50000", "2"))
        lines = self.lines_of(voucher)
        ledger = gc_posting.farmer_ledger(self.farmer)
        self.assertEqual(lines["GROWING_CHARGES"], (Decimal("50000"), Decimal("0")))
        self.assertEqual(lines[ledger.description], (Decimal("0"), Decimal("49000")))
        self.assertEqual(lines["TDS_PAYABLE"], (Decimal("0"), Decimal("1000")))

    def test_the_whole_charge_is_still_the_expense(self):
        """Withholding tax does not make the charge cheaper."""
        voucher = gc_posting.post_settlement(self.settle("50000", "2"))
        self.assertEqual(self.lines_of(voucher)["GROWING_CHARGES"][0], Decimal("50000"))

    def test_a_farmer_with_no_rate_gets_the_two_line_entry(self):
        voucher = gc_posting.post_settlement(self.settle("50000", "0"))
        self.assertEqual(voucher.lines.count(), 2)

    def test_an_odd_split_still_balances(self):
        """A rate that does not divide cleanly rounds on the tax side; the
        farmer's credit is the remainder, so gross always splits exactly."""
        voucher = gc_posting.post_settlement(self.settle("33333.33", "2.5"))
        self.assertEqual(voucher.total_debit, voucher.total_credit)
        self.assertEqual(voucher.total_debit, Decimal("33333.33"))


class LedgerAgreesTests(TdsTestCase):
    def ledger(self):
        return self.client.get(reverse("farmer_ledger_report"),
                               {"farmer": self.farmer.id}).context["data"]

    def test_the_ledger_shows_the_deduction_as_its_own_row(self):
        self.settle("50000", "2")
        rows = self.ledger()["groups"][0]["rows"]
        self.assertEqual([r["credit"] for r in rows], [Decimal("50000"), Decimal("0")])
        self.assertEqual([r["debit"] for r in rows], [Decimal("0"), Decimal("1000.00")])
        self.assertIn("TDS", rows[1]["particulars"])

    def test_the_ledger_closes_at_what_the_farmer_is_actually_owed(self):
        self.settle("50000", "2")
        self.assertEqual(self.ledger()["closing"], Decimal("49000.00"))

    def test_the_deduction_reads_under_the_charge_it_came_out_of(self):
        """Never above it, or the balance would show money withheld from a
        charge that had not been raised yet."""
        self.settle("50000", "2")
        rows = self.ledger()["groups"][0]["rows"]
        self.assertEqual([r["balance"] for r in rows],
                         [Decimal("50000"), Decimal("49000.00")])


class ReconciliationAgreesTests(TdsTestCase):
    def test_the_two_sides_still_agree_once_tds_is_in_play(self):
        """The whole point of one shared calculation. If the voucher withholds
        and the ledger does not, every farmer reads as out by their own TDS."""
        settings = GCPostingSettings.get_solo()
        settings.enabled = True
        settings.save()
        settlement = self.settle("50000", "2")
        gc_posting.post_settlement_if_enabled(settlement)

        row = self.client.get(reverse("farmer_reconciliation_report")).context["rows"][0]
        self.assertEqual(row["operational"], Decimal("49000.00"))
        self.assertEqual(row["posted"], Decimal("49000.00"))
        self.assertEqual(row["difference"], Decimal("0"))
