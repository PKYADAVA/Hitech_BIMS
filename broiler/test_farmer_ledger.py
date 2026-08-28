"""Farmer Ledger — a farmer's running account with the company.

A settled growing charge is a credit (we owe more), a payment is a debit (we
owe less), and the closing balance is what is still owed.
"""
import json
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from account.models import ChartOfAccount
from broiler.models import (Branch, BroilerBatch, BroilerFarm, BroilerLine,
                            Farmer, GrowingChargeSettlement, Region, Supervisor)


class FarmerLedgerTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="accounts", password="x", email="a@example.com")
        self.client.force_login(self.user)
        self.url = reverse("farmer_ledger_report")

        self.region = Region.objects.create(code="R1", description="East")
        self.branch = Branch.objects.create(code="B1", branch_name="Akbarpur",
                                            region=self.region)
        self.supervisor = Supervisor.objects.create(branch=self.branch, name="S. Kumar")
        self.line = BroilerLine.objects.create(description="Line 1", region=self.region,
                                               branch=self.branch)
        self.farmer = Farmer.objects.create(farmer_name="Abhishek Kumar Singh")
        self.farm = BroilerFarm.objects.create(
            farm_name="Akbarpur Farm", branch=self.branch, region=self.region,
            supervisor=self.supervisor, line=self.line, farmer=self.farmer,
            farm_capacity=5000)
        self.cash = ChartOfAccount.objects.create(
            code="1001", description="Cash in Hand", type="Asset", status="Active")

    def batch(self, name, start):
        return BroilerBatch.objects.create(batch_name=name, broiler_farm=self.farm,
                                           start_date=start)

    def settle(self, batch, payable, on):
        return GrowingChargeSettlement.objects.create(
            batch=batch, farm=self.farm, gc_date=on,
            farmer_payable=Decimal(payable))

    def pay(self, amount, on, batch=None, charges="0"):
        return self.client.post(reverse("farmer_gc_payment_add"), {
            "date": on.isoformat(), "narration": "",
            "lines_json": json.dumps([{
                "farm": self.farm.id, "batch": batch.id if batch else None,
                "pay_type": "GC Pay", "mode": "Cash", "pay_account": self.cash.id,
                "gc_amount": "0", "amount": amount, "bank_charges": charges,
                "reference_no": "", "remarks": "",
            }]),
        })

    def ledger(self, **params):
        params.setdefault("farmer", self.farmer.id)
        return self.client.get(self.url, params).context["data"]

    def test_a_settlement_credits_the_farmer_and_a_payment_debits_them(self):
        self.settle(self.batch("B1", date(2026, 5, 1)), "50000", date(2026, 6, 1))
        self.pay("20000", date(2026, 6, 10))
        d = self.ledger()
        self.assertEqual(d["totals"]["credit"], Decimal("50000"))
        self.assertEqual(d["totals"]["debit"], Decimal("20000"))
        self.assertEqual(d["closing"], Decimal("30000"))

    def test_paying_the_whole_charge_leaves_nothing_owed(self):
        self.settle(self.batch("B1", date(2026, 5, 1)), "50000", date(2026, 6, 1))
        self.pay("50000", date(2026, 6, 10))
        self.assertEqual(self.ledger()["closing"], Decimal("0"))

    def test_bank_charges_are_not_the_farmers_money(self):
        """They are what the transfer cost us. Putting them on the farmer's
        side would make the ledger disagree with what landed in their account."""
        self.settle(self.batch("B1", date(2026, 5, 1)), "10000", date(2026, 6, 1))
        self.pay("10000", date(2026, 6, 10), charges="250")
        d = self.ledger()
        self.assertEqual(d["totals"]["debit"], Decimal("10000"))
        self.assertEqual(d["closing"], Decimal("0"))

    def test_everything_before_the_window_folds_into_the_opening_figure(self):
        """A date-ranged statement is only readable if the history before it is
        one number rather than a hundred rows."""
        self.settle(self.batch("B1", date(2026, 1, 1)), "40000", date(2026, 2, 1))
        self.pay("15000", date(2026, 2, 10))
        self.settle(self.batch("B2", date(2026, 5, 1)), "30000", date(2026, 6, 1))
        d = self.ledger(from_date="2026-05-01")
        self.assertEqual(d["opening"], Decimal("25000"))     # 40000 - 15000
        self.assertEqual(d["totals"]["credit"], Decimal("30000"))
        self.assertEqual(d["closing"], Decimal("55000"))

    def test_a_charge_and_its_payment_on_one_day_read_in_that_order(self):
        """The charge is raised before it is paid, so a same-day pair must not
        show the payment first and a negative balance in between."""
        self.settle(self.batch("B1", date(2026, 5, 1)), "10000", date(2026, 6, 1))
        self.pay("4000", date(2026, 6, 1))
        rows = self.ledger()["groups"][0]["rows"]
        self.assertEqual([r["credit"] for r in rows], [Decimal("10000"), Decimal("0")])
        self.assertEqual([r["balance"] for r in rows],
                         [Decimal("10000"), Decimal("6000")])

    def test_rows_are_grouped_by_month(self):
        self.settle(self.batch("B1", date(2026, 5, 1)), "10000", date(2026, 6, 1))
        self.settle(self.batch("B2", date(2026, 6, 1)), "12000", date(2026, 7, 1))
        self.assertEqual([g["label"] for g in self.ledger()["groups"]],
                         ["June 2026", "July 2026"])

    def test_another_farmers_account_is_not_this_one(self):
        other = Farmer.objects.create(farmer_name="Ram Prasad")
        other_farm = BroilerFarm.objects.create(
            farm_name="Bahraich Farm", branch=self.branch, region=self.region,
            supervisor=self.supervisor, line=self.line, farmer=other,
            farm_capacity=5000)
        batch = BroilerBatch.objects.create(batch_name="OTH-1", broiler_farm=other_farm,
                                            start_date=date(2026, 5, 1))
        GrowingChargeSettlement.objects.create(batch=batch, farm=other_farm,
                                               gc_date=date(2026, 6, 1),
                                               farmer_payable=Decimal("99999"))
        self.assertEqual(self.ledger()["totals"]["credit"], Decimal("0"))

    def test_no_farmer_chosen_shows_no_account_rather_than_everyones(self):
        response = self.client.get(self.url)
        self.assertIsNone(response.context["data"])

    def test_a_querystring_is_not_a_permission(self):
        """An id that is not a visible farmer resolves to nothing, rather than
        printing an account the user may not open."""
        response = self.client.get(self.url, {"farmer": "999999"})
        self.assertIsNone(response.context["data"])
        self.assertIsNone(response.context["farmer"])

    def test_the_excel_export_comes_back_as_a_spreadsheet(self):
        self.settle(self.batch("B1", date(2026, 5, 1)), "10000", date(2026, 6, 1))
        response = self.client.get(self.url, {"farmer": self.farmer.id, "export": "excel"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("spreadsheet", response["Content-Type"])
        self.assertIn("attachment", response["Content-Disposition"])
