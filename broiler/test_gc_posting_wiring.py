"""Posting wired to the documents that cause it.

Settlement and payment reach the ledger through the same switch, and go live
together: posting only the payment would drop Cash against nothing and put the
Trial Balance out in a way nobody could trace back.

The switch is off by default, so every one of these tests has to turn it on.
That is the point — deploying this code changes no figure anyone sees until
someone decides it should.
"""
import json
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse as url_for

from account.coa_seed import seed_coa_templates
from account.models import (ChartOfAccount, CoATemplate, CompanyProfile,
                            FinancialYear, Voucher)
from account.services import CoAGeneratorService
from broiler.models import (Branch, BroilerBatch, BroilerFarm, BroilerLine,
                            Farmer, FarmerGCPayment, GCPostingSettings,
                            GrowingChargeSettlement, Region, Supervisor)
from broiler.services import gc_posting


class WiringTestCase(TestCase):
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
        cash_group = ChartOfAccount.objects.get(company=cls.company, system_role="CASH")
        cls.cash = ChartOfAccount.objects.create(
            company=cls.company, parent=cash_group, code="111101",
            description="Cash in Hand", account_type=cash_group.account_type,
            currency=cash_group.currency, is_group=False, is_postable=True)

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="cashier", password="x", email="c@example.com")
        self.client.force_login(self.user)
        self.batch = BroilerBatch.objects.create(
            batch_name="AKB-1109-1", broiler_farm=self.farm, start_date=date(2026, 5, 1))

    def enable(self, cutoff=None):
        s = GCPostingSettings.get_solo()
        s.enabled = True
        s.cutoff_date = cutoff
        s.save()
        return s

    def settle(self, payable="50000", on=date(2026, 6, 1)):
        return GrowingChargeSettlement.objects.create(
            batch=self.batch, farm=self.farm, gc_date=on,
            farmer_payable=Decimal(payable))

    def pay(self, amount="20000", on=date(2026, 6, 10)):
        return self.client.post(url_for("farmer_gc_payment_add"), {
            "date": on.isoformat(), "narration": "",
            "lines_json": json.dumps([{
                "farm": self.farm.id, "batch": self.batch.id, "pay_type": "GC Pay",
                "mode": "Cash", "pay_account": self.cash.id, "gc_amount": "0",
                "amount": amount, "bank_charges": "0",
                "reference_no": "", "remarks": ""}]),
        })


class TheSwitchTests(WiringTestCase):
    def test_posting_is_off_until_someone_turns_it_on(self):
        """Deploying this must change nothing anyone sees."""
        self.assertFalse(GCPostingSettings.get_solo().enabled)
        gc_posting.post_settlement_if_enabled(self.settle())
        self.assertFalse(Voucher.objects.exists())

    def test_switched_on_a_settlement_posts(self):
        self.enable()
        gc_posting.post_settlement_if_enabled(self.settle("50000"))
        self.assertEqual(Voucher.objects.count(), 1)

    def test_a_payment_before_the_cutoff_is_left_alone(self):
        """History from before posting existed stays where it is — much of it
        sits in years that are closed, and post_voucher refuses those anyway."""
        self.enable(cutoff=date(2026, 6, 1))
        gc_posting.post_settlement_if_enabled(self.settle("50000", on=date(2026, 5, 1)))
        self.assertFalse(Voucher.objects.exists())

    def test_on_the_cutoff_day_itself_it_posts(self):
        self.enable(cutoff=date(2026, 6, 1))
        gc_posting.post_settlement_if_enabled(self.settle("50000", on=date(2026, 6, 1)))
        self.assertEqual(Voucher.objects.count(), 1)


class PaymentWiringTests(WiringTestCase):
    def test_saving_a_payment_posts_it(self):
        self.enable()
        self.pay("20000")
        payment = FarmerGCPayment.objects.get()
        self.assertEqual(gc_posting.vouchers_for(payment).filter(status="Posted").count(), 1)

    def test_deleting_a_payment_takes_it_off_the_books(self):
        self.enable()
        self.pay("20000")
        payment = FarmerGCPayment.objects.get()
        self.client.post(url_for("farmer_gc_payment_delete", args=[payment.id]))
        self.assertFalse(FarmerGCPayment.objects.exists())
        self.assertEqual(Voucher.objects.filter(status="Posted").count(), 0)
        self.assertEqual(Voucher.objects.filter(status="Cancelled").count(), 1)

    def test_a_payment_deleted_after_posting_was_switched_off_still_reverses(self):
        """Otherwise the money stays on the books for a payment that is gone."""
        self.enable()
        self.pay("20000")
        settings = GCPostingSettings.get_solo()
        settings.enabled = False
        settings.save()
        payment = FarmerGCPayment.objects.get()
        self.client.post(url_for("farmer_gc_payment_delete", args=[payment.id]))
        self.assertEqual(Voucher.objects.filter(status="Cancelled").count(), 1)


class SettlementWiringTests(WiringTestCase):
    def settle_through_the_api(self, on=date(2026, 6, 1)):
        return self.client.post(
            url_for("gc_settlement_list"),
            data=json.dumps({"batch": self.batch.id, "gc_date": on.isoformat()}),
            content_type="application/json")

    def test_deleting_a_settlement_reverses_before_the_batch_reopens(self):
        """The reopen path is the one most likely to be forgotten. Missing it
        leaves an expense and a liability for a settlement that is gone."""
        self.enable()
        settlement = self.settle("50000")
        gc_posting.post_settlement_if_enabled(settlement)
        self.batch.is_closed = True
        self.batch.save(update_fields=["is_closed"])

        self.client.delete(url_for("gc_settlement_detail", args=[settlement.id]))

        self.assertFalse(GrowingChargeSettlement.objects.exists())
        self.assertEqual(Voucher.objects.filter(status="Posted").count(), 0)
        self.batch.refresh_from_db()
        self.assertFalse(self.batch.is_closed)

    def test_a_failure_to_post_takes_the_document_with_it(self):
        """A settlement that exists without its voucher is the silent
        divergence this whole exercise removes, so the save is refused."""
        self.enable()
        gc_posting.farmer_ledger(self.farmer).delete()
        with self.assertRaises(Exception):
            gc_posting.post_settlement_if_enabled(self.settle("50000"))
