"""Posting growing charges and farmer payments.

Phase two: the service is exercised directly here. Nothing calls it from a
save yet — settlement and payment are wired together in phase three, because
posting only the payment would make Cash fall against nothing.
"""
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from account.coa_seed import seed_coa_templates
from account.models import (ChartOfAccount, CoATemplate, CompanyProfile,
                            FinancialYear, Voucher)
from account.services import CoAGeneratorService, journal
from broiler.models import (Branch, BroilerBatch, BroilerFarm, BroilerLine,
                            Farmer, FarmerGCPayment, FarmerGCPaymentLine,
                            GrowingChargeSettlement, Region, Supervisor)
from broiler.services import gc_posting


class PostingTestCase(TestCase):
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

        # Money leaves a cash or bank ledger, never the Bank Charges expense.
        cash_group = ChartOfAccount.objects.get(company=cls.company, system_role="CASH")
        cls.cash = ChartOfAccount.objects.create(
            company=cls.company, parent=cash_group, code="111101",
            description="Cash in Hand", account_type=cash_group.account_type,
            currency=cash_group.currency, is_group=False, is_postable=True)

    def account(self, role):
        return ChartOfAccount.objects.get(company=self.company, system_role=role)

    def settlement(self, payable="50000", on=date(2026, 6, 1)):
        return GrowingChargeSettlement.objects.create(
            batch=self.batch, farm=self.farm, gc_date=on,
            farmer_payable=Decimal(payable))

    def payment(self, amount="20000", charges="0", on=date(2026, 6, 10)):
        payment = FarmerGCPayment.objects.create(date=on)
        FarmerGCPaymentLine.objects.create(
            payment=payment, farm=self.farm, batch=self.batch, pay_type="GC Pay",
            mode="Bank Transfer", pay_account=self.cash,
            amount=Decimal(amount), bank_charges=Decimal(charges))
        return payment

    def lines_of(self, voucher):
        return {(l.account.system_role or l.account.description): (l.debit, l.credit)
                for l in voucher.lines.select_related("account")}


class SettlementPostingTests(PostingTestCase):
    def test_a_settled_charge_debits_the_expense_and_credits_the_farmer(self):
        voucher = gc_posting.post_settlement(self.settlement("50000"))
        lines = self.lines_of(voucher)
        self.assertEqual(lines["GROWING_CHARGES"], (Decimal("50000"), Decimal("0")))
        ledger = gc_posting.farmer_ledger(self.farmer)
        self.assertEqual(lines[ledger.description], (Decimal("0"), Decimal("50000")))

    def test_the_voucher_is_balanced_and_posted(self):
        voucher = gc_posting.post_settlement(self.settlement("50000"))
        self.assertEqual(voucher.total_debit, voucher.total_credit)
        self.assertEqual(voucher.status, "Posted")
        self.assertTrue(voucher.system_generated)

    def test_the_voucher_points_back_at_the_settlement(self):
        """Without the link nothing could find the voucher to reverse it."""
        settlement = self.settlement()
        voucher = gc_posting.post_settlement(settlement)
        self.assertEqual(list(gc_posting.vouchers_for(settlement)), [voucher])

    def test_a_settlement_worth_nothing_posts_nothing(self):
        """A one-sided voucher is not a voucher, and zero is a real outcome."""
        self.assertIsNone(gc_posting.post_settlement(self.settlement("0")))
        self.assertFalse(Voucher.objects.exists())

    def test_posting_twice_cancels_the_first_rather_than_doubling_the_charge(self):
        settlement = self.settlement("50000")
        first = gc_posting.post_settlement(settlement)
        second = gc_posting.post_settlement(settlement)
        first.refresh_from_db()
        self.assertEqual(first.status, "Cancelled")
        self.assertEqual(second.status, "Posted")

    def test_a_farmer_with_no_ledger_is_refused_rather_than_posted_elsewhere(self):
        ledger = gc_posting.farmer_ledger(self.farmer)
        ledger.delete()
        with self.assertRaises(ValidationError) as caught:
            gc_posting.post_settlement(self.settlement())
        self.assertIn("no ledger", str(caught.exception))


class PaymentPostingTests(PostingTestCase):
    def test_a_payment_debits_the_farmer_and_credits_the_account_it_left(self):
        voucher = gc_posting.post_payment(self.payment("20000"))
        lines = self.lines_of(voucher)
        ledger = gc_posting.farmer_ledger(self.farmer)
        self.assertEqual(lines[ledger.description], (Decimal("20000"), Decimal("0")))
        self.assertEqual(lines["Cash in Hand"], (Decimal("0"), Decimal("20000")))
        self.assertEqual(voucher.total_debit, voucher.total_credit)
        self.assertEqual(voucher.voucher_type, "Payment")

    def test_bank_charges_are_our_cost_and_never_touch_the_farmer(self):
        """The farmer is debited what they were paid; the fee is an expense of
        ours. The Farmer Ledger report follows the same rule, and the two have
        to agree or the reconciliation is meaningless."""
        voucher = gc_posting.post_payment(self.payment("20000", charges="250"))
        ledger = gc_posting.farmer_ledger(self.farmer)
        lines = self.lines_of(voucher)
        self.assertEqual(lines[ledger.description][0], Decimal("20000"))
        self.assertEqual(lines["BANK_CHARGES"], (Decimal("250"), Decimal("0")))
        self.assertEqual(lines["Cash in Hand"], (Decimal("0"), Decimal("20250")))
        self.assertEqual(voucher.total_debit, Decimal("20250"))
        self.assertEqual(voucher.total_credit, Decimal("20250"))

    def test_a_payment_with_no_lines_posts_nothing(self):
        self.assertIsNone(gc_posting.post_payment(FarmerGCPayment.objects.create(
            date=date(2026, 6, 10))))


class ReversalTests(PostingTestCase):
    def test_reversing_cancels_what_the_document_posted(self):
        settlement = self.settlement("50000")
        gc_posting.post_settlement(settlement)
        self.assertEqual(gc_posting.reverse(settlement), 1)
        self.assertEqual(gc_posting.vouchers_for(settlement).get().status, "Cancelled")

    def test_reversing_something_that_never_posted_is_not_an_error(self):
        """The delete path cannot know whether a document posted, and must not
        fail because it did not."""
        self.assertEqual(gc_posting.reverse(self.settlement()), 0)

    def test_a_cancelled_voucher_leaves_the_accounts_flat(self):
        settlement = self.settlement("50000")
        gc_posting.post_settlement(settlement)
        gc_posting.reverse(settlement)
        expense = self.account("GROWING_CHARGES")
        self.assertEqual(journal.account_balance(expense), Decimal("0"))


class MissingAccountTests(PostingTestCase):
    def test_a_missing_account_says_which_command_fixes_it(self):
        """The message has to be actionable — whoever hits this is mid-save and
        needs to know what to run, not that a lookup returned None."""
        self.account("GROWING_CHARGES").delete()
        with self.assertRaises(ValidationError) as caught:
            gc_posting.post_settlement(self.settlement())
        self.assertIn("backfill_farmer_accounts", str(caught.exception))
