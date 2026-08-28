"""Farmer GC Payment — paying a farmer what the settlement said they were owed.

A header per voucher with a line per farmer, so a day's payments written up
together stay one row in the register and the Farm / Farmer / Mode / Method
columns are summaries over the lines.
"""
import json
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from account.models import ChartOfAccount
from broiler.models import (Branch, BroilerBatch, BroilerFarm, BroilerLine, Farmer,
                            FarmerGCPayment, FarmerGCPaymentLine, Region, Supervisor)


class FarmerGCPaymentTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="cashier", password="x", email="cashier@example.com")
        self.client.force_login(self.user)

        self.region = Region.objects.create(code="R1", description="East")
        self.branch = Branch.objects.create(code="B1", branch_name="Akbarpur",
                                            region=self.region)
        self.supervisor = Supervisor.objects.create(branch=self.branch, name="S. Kumar")
        self.line_master = BroilerLine.objects.create(
            description="Line 1", region=self.region, branch=self.branch)
        self.farmer = Farmer.objects.create(farmer_name="Abhishek Kumar Singh")
        self.other_farmer = Farmer.objects.create(farmer_name="Ram Prasad")
        self.farm = self.make_farm("Akbarpur Farm", self.farmer)
        self.other_farm = self.make_farm("Bahraich Farm", self.other_farmer)
        self.batch = BroilerBatch.objects.create(
            batch_name="AKB-1109-1", broiler_farm=self.farm, start_date=date(2026, 5, 1))
        self.cash = ChartOfAccount.objects.create(
            code="1001", description="Cash in Hand", type="Asset", status="Active")

    def make_farm(self, name, farmer):
        return BroilerFarm.objects.create(
            farm_name=name, branch=self.branch, region=self.region,
            supervisor=self.supervisor, line=self.line_master, farmer=farmer,
            farm_capacity=5000)

    def line(self, **over):
        row = {"farm": self.farm.id, "batch": self.batch.id, "pay_type": "GC Pay",
               "mode": "Cash", "pay_account": self.cash.id, "gc_amount": "5000",
               "amount": "2000", "bank_charges": "0", "reference_no": "",
               "remarks": ""}
        row.update(over)
        return row

    def post(self, lines, url=None, **header):
        data = {"date": header.pop("date", "2026-08-28"),
                "narration": header.pop("narration", ""),
                "lines_json": json.dumps(lines)}
        return self.client.post(url or reverse("farmer_gc_payment_add"), data)

    # -- saving ------------------------------------------------------------

    def test_a_payment_is_saved_with_its_lines_and_numbered(self):
        self.post([self.line()])
        payment = FarmerGCPayment.objects.get()
        self.assertEqual(payment.lines.count(), 1)
        self.assertEqual(payment.total_amount, Decimal("2000"))
        self.assertTrue(payment.payment_no.startswith("FGP-2627-"),
                        payment.payment_no)

    def test_the_voucher_number_runs_on_the_financial_year_not_the_calendar(self):
        """April starts the Indian financial year, so January to March belongs
        to the year before it."""
        self.assertEqual(FarmerGCPayment._next_payment_no(date(2026, 4, 1)),
                         "FGP-2627-0001")
        self.assertEqual(FarmerGCPayment._next_payment_no(date(2027, 3, 31)),
                         "FGP-2627-0001")
        self.assertEqual(FarmerGCPayment._next_payment_no(date(2027, 4, 1)),
                         "FGP-2728-0001")

    def test_a_voucher_with_no_usable_line_is_refused(self):
        """A line with no farm or no account cannot be paid, so a voucher made
        only of those is not a voucher."""
        self.post([{"farm": "", "pay_account": "", "amount": "500"}])
        self.assertFalse(FarmerGCPayment.objects.exists())

    def test_a_string_date_still_numbers_the_voucher(self):
        """The form posts its date as text. Django only coerces a field on
        full_clean or on the way to the database, so the numbering has to cope
        with a str — the trap SupervisorTrip._next_no already documents."""
        self.assertEqual(FarmerGCPayment._next_payment_no("2026-08-28"),
                         "FGP-2627-0001")

    # -- summaries ---------------------------------------------------------

    def test_one_farmer_reads_by_name_and_several_read_multiple(self):
        self.post([self.line(), self.line(farm=self.other_farm.id, batch=None)])
        payment = FarmerGCPayment.objects.get()
        self.assertEqual(payment.farmer_summary, "Multiple")
        self.assertEqual(payment.mode_summary, "Cash")      # both lines agree
        self.assertEqual(payment.total_amount, Decimal("4000"))

        payment.lines.filter(farm=self.other_farm).delete()
        self.assertEqual(payment.farmer_summary, "Abhishek Kumar Singh")

    # -- narration ---------------------------------------------------------

    def test_a_voucher_left_blank_is_given_a_narration(self):
        """The form asks only for remarks, but the voucher still needs a
        sentence an accountant can read."""
        self.post([self.line()])
        payment = FarmerGCPayment.objects.get()
        self.assertIn("payment", payment.narration.lower())
        self.assertIn("Abhishek Kumar Singh", payment.narration)

    def test_a_narration_typed_by_hand_is_never_overwritten(self):
        self.post([self.line()], narration="Paid at the farm gate.")
        self.assertEqual(FarmerGCPayment.objects.get().narration,
                         "Paid at the farm gate.")

    # -- editing and deleting ---------------------------------------------

    def test_editing_replaces_the_lines_rather_than_adding_to_them(self):
        self.post([self.line()])
        payment = FarmerGCPayment.objects.get()
        self.post([self.line(amount="3500")],
                  url=reverse("farmer_gc_payment_edit", args=[payment.id]))
        payment.refresh_from_db()
        self.assertEqual(payment.lines.count(), 1)
        self.assertEqual(payment.total_amount, Decimal("3500"))

    def test_deleting_takes_the_lines_with_it(self):
        self.post([self.line()])
        payment = FarmerGCPayment.objects.get()
        self.client.post(reverse("farmer_gc_payment_delete", args=[payment.id]))
        self.assertFalse(FarmerGCPayment.objects.exists())
        self.assertFalse(FarmerGCPaymentLine.objects.exists())

    # -- the register ------------------------------------------------------

    def test_the_register_is_filtered_by_the_date_range(self):
        self.post([self.line()], date="2026-08-28")
        self.post([self.line()], date="2026-09-15")
        rows = self.client.get(reverse("farmer_gc_payment_api"),
                               {"from_date": "2026-09-01", "to_date": "2026-09-30"}).json()
        self.assertEqual([r["date"] for r in rows["data"]], ["15-09-2026"])

    # -- what is still owed ------------------------------------------------

    def test_an_unsettled_batch_owes_nothing_and_says_so(self):
        d = self.client.get(reverse("farmer_gc_payment_gc_amount"),
                            {"batch": self.batch.id}).json()
        self.assertEqual(d["gc_amount"], "0.00")
        self.assertFalse(d["settled"])

    def test_payments_already_made_are_netted_off_what_is_outstanding(self):
        self.post([self.line(amount="2000")])
        d = self.client.get(reverse("farmer_gc_payment_gc_amount"),
                            {"batch": self.batch.id}).json()
        self.assertEqual(d["paid"], "2000.00")

    def test_a_voucher_being_edited_does_not_count_against_itself(self):
        """Its own previous amount would otherwise read as money already paid,
        and the outstanding figure would drop by it twice."""
        self.post([self.line(amount="2000")])
        payment = FarmerGCPayment.objects.get()
        d = self.client.get(reverse("farmer_gc_payment_gc_amount"),
                            {"batch": self.batch.id, "exclude": payment.id}).json()
        self.assertEqual(d["paid"], "0.00")

    def test_a_missing_or_junk_batch_is_answered_not_raised(self):
        for bad in ("", "abc", "0x1"):
            d = self.client.get(reverse("farmer_gc_payment_gc_amount"),
                                {"batch": bad}).json()
            self.assertEqual(d["outstanding"], "0.00", bad)

    def test_the_batch_dropdown_lists_the_farms_batches(self):
        rows = self.client.get(reverse("farmer_gc_payment_batches"),
                               {"farm": self.farm.id}).json()
        self.assertEqual([r["batch_name"] for r in rows], ["AKB-1109-1"])
        self.assertEqual(self.client.get(reverse("farmer_gc_payment_batches"),
                                         {"farm": ""}).json(), [])
