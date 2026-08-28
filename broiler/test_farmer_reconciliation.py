"""Farmer Reconciliation — the records against the accounts.

The Farmer Ledger reads settlements and payments; the farmer's account in the
chart reads what was posted. Two routes to the same number, and the report
exists to catch the day they stop arriving at the same place.
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
                            Farmer, FarmerGCPayment, FarmerGCPaymentLine,
                            GrowingChargeSettlement, Region, Supervisor)
from broiler.services import gc_posting


class ReconciliationTests(TestCase):
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
        cls.farmer = Farmer.objects.create(farmer_name="Abhishek Kumar Singh")
        cls.farm = BroilerFarm.objects.create(
            farm_name="Akbarpur Farm", branch=cls.branch, region=cls.region,
            supervisor=cls.supervisor, line=cls.line, farmer=cls.farmer,
            farm_capacity=5000)
        cls.batch = BroilerBatch.objects.create(batch_name="AKB-1109-1",
                                                broiler_farm=cls.farm,
                                                start_date=date(2026, 5, 1))
        cash_group = ChartOfAccount.objects.get(company=cls.company, system_role="CASH")
        cls.cash = ChartOfAccount.objects.create(
            company=cls.company, parent=cash_group, code="111101",
            description="Cash in Hand", account_type=cash_group.account_type,
            currency=cash_group.currency, is_group=False, is_postable=True)

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="accounts", password="x", email="a@example.com")
        self.client.force_login(self.user)
        self.url = reverse("farmer_reconciliation_report")

    def settle(self, payable="50000"):
        return GrowingChargeSettlement.objects.create(
            batch=self.batch, farm=self.farm, gc_date=date(2026, 6, 1),
            farmer_payable=Decimal(payable))

    def pay(self, amount="20000"):
        payment = FarmerGCPayment.objects.create(date=date(2026, 6, 10))
        FarmerGCPaymentLine.objects.create(
            payment=payment, farm=self.farm, batch=self.batch, pay_type="GC Pay",
            mode="Cash", pay_account=self.cash, amount=Decimal(amount))
        return payment

    def row(self, **params):
        rows = self.client.get(self.url, params).context["rows"]
        return rows[0] if rows else None

    def test_a_farmer_with_nothing_on_either_side_agrees(self):
        row = self.row()
        self.assertEqual(row["operational"], Decimal("0"))
        self.assertEqual(row["posted"], Decimal("0"))
        self.assertEqual(row["difference"], Decimal("0"))

    def test_a_settlement_that_was_never_posted_shows_as_a_difference(self):
        """This is the state the whole system is in today, and the report has to
        say so rather than looking healthy."""
        self.settle("50000")
        row = self.row()
        self.assertEqual(row["operational"], Decimal("50000"))
        self.assertEqual(row["posted"], Decimal("0"))
        self.assertEqual(row["difference"], Decimal("50000"))

    def test_once_posted_the_two_sides_agree(self):
        settlement = self.settle("50000")
        gc_posting.post_settlement(settlement)
        row = self.row()
        self.assertEqual(row["operational"], Decimal("50000"))
        self.assertEqual(row["posted"], Decimal("50000"))
        self.assertEqual(row["difference"], Decimal("0"))

    def test_a_settlement_and_its_payment_both_posted_still_agree(self):
        gc_posting.post_settlement(self.settle("50000"))
        gc_posting.post_payment(self.pay("20000"))
        row = self.row()
        self.assertEqual(row["operational"], Decimal("30000"))
        self.assertEqual(row["posted"], Decimal("30000"))
        self.assertEqual(row["difference"], Decimal("0"))

    def test_a_reversal_puts_both_sides_back_to_nothing(self):
        settlement = self.settle("50000")
        gc_posting.post_settlement(settlement)
        gc_posting.reverse(settlement)
        settlement.delete()
        row = self.row()
        self.assertEqual(row["operational"], Decimal("0"))
        self.assertEqual(row["posted"], Decimal("0"))

    def test_posting_only_the_payment_is_caught(self):
        """The failure mode phase three exists to avoid: the money leaves the
        accounts with no charge behind it, and the farmer's account goes the
        wrong way. The report must not call that agreement."""
        self.settle("50000")
        gc_posting.post_payment(self.pay("20000"))
        row = self.row()
        self.assertEqual(row["operational"], Decimal("30000"))
        self.assertEqual(row["posted"], Decimal("-20000"))
        self.assertEqual(row["difference"], Decimal("50000"))

    def test_the_filter_hides_farmers_who_agree(self):
        self.assertIsNotNone(self.row())
        self.assertIsNone(self.row(only_diff="1"))
        self.settle("50000")
        self.assertIsNotNone(self.row(only_diff="1"))

    def test_a_farmer_with_no_ledger_is_shown_rather_than_skipped(self):
        """No ledger means nothing can be posted for them, which is the fault
        worth seeing, not a row worth hiding."""
        gc_posting.farmer_ledger(self.farmer).delete()
        row = self.row()
        self.assertIsNone(row["ledger"])
        self.assertEqual(row["posted"], Decimal("0"))
