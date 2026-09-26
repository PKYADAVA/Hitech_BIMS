"""Petty expense: what it puts on the books, and what it refuses to.

The module owns no balances of its own. Every assertion here therefore reads
the answer back out of the accounting engine -- the voucher, the ledger
balance, the cost-centre tag -- rather than out of a column this app keeps,
because that is the whole claim the module makes.
"""
import datetime
import json
import shutil
import tempfile
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from account.coa_seed import seed_coa_templates
from account.models import (BankCashMaster, ChartOfAccount, CoATemplate,
                            CompanyProfile, FinancialYear, OrganizationCentre,
                            PaymentMode, PettyExpense, PettyExpenseItem)
from account.services import CoAGeneratorService
from account.services import journal
from account.services import petty_expense as service
from account.services.bank_cash import ledger_for_bank_cash
from broiler.models import (Branch, BroilerFarm, BroilerFarmShed, Farmer,
                            Region, Supervisor)
from inventory.models import Sector

TODAY = datetime.date.today()


class PettyExpenseTestCase(TestCase):
    """One company, one chart, one cash box and one bank account."""

    @classmethod
    def setUpTestData(cls):
        seed_coa_templates()
        cls.company = CompanyProfile.get_solo()
        CoAGeneratorService(cls.company,
                            CoATemplate.objects.get(industry="Poultry")).generate()

        # The year the expenses fall in has to exist before anything can post.
        start = datetime.date(TODAY.year if TODAY.month >= 4 else TODAY.year - 1, 4, 1)
        FinancialYear.objects.create(start_date=start,
                                     end_date=start.replace(year=start.year + 1)
                                     - datetime.timedelta(days=1),
                                     is_active=True, state="Open")

        # A branch is given its own cost centre by a signal, which needs the
        # Branch Office sector to hang it on.
        Sector.objects.get_or_create(code=OrganizationCentre.CENTRE_TYPE_BRANCH,
                                     defaults={"name": "Branch Office"})

        cls.region = Region.objects.create(description="East")
        cls.branch = Branch.objects.create(branch_name="Akbarpur",
                                           region=cls.region, prefix="AKB")
        cls.other_branch = Branch.objects.create(branch_name="Jaunpur",
                                                 region=cls.region, prefix="JNP")
        cls.supervisor = Supervisor.objects.create(branch=cls.branch, name="R. Singh")
        cls.farmer = Farmer.objects.create(farmer_name="S. Yadav")
        cls.farm = BroilerFarm.objects.create(
            branch=cls.branch, supervisor=cls.supervisor, farmer=cls.farmer,
            region="East", line="L1", farm_name="Green Valley")
        cls.other_farm = BroilerFarm.objects.create(
            branch=cls.other_branch, supervisor=cls.supervisor, farmer=cls.farmer,
            region="East", line="L1", farm_name="Riverside")
        cls.shed = BroilerFarmShed.objects.create(farm=cls.farm)
        cls.other_shed = BroilerFarmShed.objects.create(farm=cls.other_farm)

        # The cash box and the bank account: each gets its ledger from the
        # Bank/Cash Master's own signal, which is the mapping this module uses.
        cls.cash = BankCashMaster.objects.create(name="Farm Cash Box", is_cash=True)
        cls.bank = BankCashMaster.objects.create(name="HDFC Current", is_cash=False)
        cls.cash_ledger = ledger_for_bank_cash(cls.cash)
        cls.bank_ledger = ledger_for_bank_cash(cls.bank)

        # A migration already seeds the usual modes.
        cls.mode, _ = PaymentMode.objects.get_or_create(
            name="Cash", defaults={"category": "Cash"})
        if cls.mode.category != "Cash":
            cls.mode.category = "Cash"
            cls.mode.save(update_fields=["category"])
        cls.user = get_user_model().objects.create_superuser(
            username="pettytester", password="x", email="p@example.com")

        # Somewhere to charge a line: a real postable expense ledger, and the
        # group above it, which a line may not post to.
        cls.expense_ledger = ChartOfAccount.objects.filter(
            company=cls.company, account_type__name="Expense",
            is_postable=True, is_group=False).order_by("code").first()
        cls.expense_group = cls.expense_ledger.parent

    # -- helpers ----------------------------------------------------------
    def make(self, lines=((300, 1),), paid_from=None, **over):
        fields = dict(
            company=self.company, expense_date=TODAY, branch=self.branch,
            farm=self.farm, paid_to_name="Tea Stall",
            payment_mode=self.mode, paid_from=paid_from or self.cash,
        )
        fields.update(over)
        expense = PettyExpense.objects.create(**fields)
        for index, (rate, qty) in enumerate(lines, start=1):
            PettyExpenseItem.objects.create(
                petty_expense=expense, line_no=index,
                account=over.get("account") or self.expense_ledger,
                description=f"Line {index}", quantity=Decimal(str(qty)),
                rate=Decimal(str(rate)))
        expense.recalculate()
        expense.save()
        return expense

    def fund_cash(self, amount):
        """Put money in the box the only way the ERP has: a posted voucher."""
        capital = ChartOfAccount.objects.filter(
            company=self.company, account_type__name="Equity",
            is_postable=True, is_group=False).order_by("code").first()
        journal.create_voucher(
            self.company, TODAY,
            [{"account": self.cash_ledger.pk, "debit": amount, "credit": 0},
             {"account": capital.pk, "debit": 0, "credit": amount}],
            user=self.user, voucher_type="Receipt", manual=False,
            system_generated=True, post=True)


class PostingTests(PettyExpenseTestCase):
    def test_posting_writes_one_voucher_that_balances(self):
        self.fund_cash(5000)
        expense = self.make(lines=((300, 1), (120, 2)))
        voucher = service.post(expense, user=self.user)

        self.assertEqual(voucher.total_debit, voucher.total_credit)
        self.assertEqual(voucher.total_debit, Decimal("540.00"))
        self.assertEqual(voucher.lines.count(), 3)   # two lines plus the credit

    def test_the_money_leaves_the_account_it_was_paid_from(self):
        """The balance is the ledger's, not a column this module keeps."""
        self.fund_cash(5000)
        before = journal.account_balance(self.cash_ledger)
        expense = self.make(lines=((300, 1),))
        service.post(expense, user=self.user)
        after = journal.account_balance(self.cash_ledger)
        self.assertEqual(before - after, Decimal("300.00"))
        self.assertEqual(journal.account_balance(self.expense_ledger), Decimal("300.00"))

    def test_every_line_carries_the_cost_centre_so_the_centre_report_sees_it(self):
        self.fund_cash(5000)
        centre = self.branch.organization_centre
        expense = self.make(lines=((300, 1), (200, 1)), cost_centre=centre)
        voucher = service.post(expense, user=self.user)
        self.assertTrue(all(line.cost_center_id == centre.pk
                            for line in voucher.lines.all()),
                        "a line without the centre is invisible to the centre report")

    def test_the_expense_is_linked_to_what_it_posted_from_both_sides(self):
        self.fund_cash(5000)
        expense = self.make()
        voucher = service.post(expense, user=self.user)
        expense.refresh_from_db()
        self.assertEqual(expense.journal_id, voucher.pk)
        self.assertEqual(list(service.vouchers_for(expense)), [voucher])
        self.assertEqual(expense.status, PettyExpense.STATUS_POSTED)
        self.assertEqual(expense.posted_by, self.user)

    def test_other_charges_and_a_discount_reach_the_books(self):
        """The net is what leaves the account, so the voucher must be the net."""
        self.fund_cash(5000)
        expense = self.make(lines=((300, 1),), other_charges=Decimal("50"),
                            adjustment=Decimal("20"))
        expense.recalculate()
        expense.save()
        voucher = service.post(expense, user=self.user)
        self.assertEqual(expense.net_amount, Decimal("330.00"))
        self.assertEqual(voucher.total_credit, Decimal("330.00"))
        self.assertEqual(voucher.total_debit, voucher.total_credit)

    def test_a_posted_expense_cannot_be_posted_twice(self):
        self.fund_cash(5000)
        expense = self.make()
        service.post(expense, user=self.user)
        with self.assertRaises(service.PettyExpenseError):
            service.post(expense, user=self.user)


class RefusalTests(PettyExpenseTestCase):
    def test_a_cash_box_cannot_go_below_zero(self):
        expense = self.make(lines=((300, 1),))       # nothing funded the box
        with self.assertRaises(service.PettyExpenseError) as caught:
            service.post(expense, user=self.user)
        self.assertIn("Not enough petty cash", str(caught.exception))
        expense.refresh_from_db()
        self.assertEqual(expense.status, PettyExpense.STATUS_DRAFT)

    def test_a_bank_account_cannot_pay_a_petty_expense(self):
        """Petty means the cash box. A bank payment carries the bank's own
        reference and belongs in a payment voucher."""
        expense = self.make(lines=((300, 1),), paid_from=self.bank)
        with self.assertRaises(service.PettyExpenseError) as caught:
            service.post(expense, user=self.user)
        self.assertIn("bank account", str(caught.exception))
        self.assertEqual(expense.status, PettyExpense.STATUS_DRAFT)

    def test_the_bank_is_not_even_offered(self):
        offered = {row["id"] for row in service.paid_from_accounts()}
        self.assertIn(self.cash.pk, offered)
        self.assertNotIn(self.bank.pk, offered)

    def test_only_a_cash_payment_mode_is_offered(self):
        """Read from the Payment Mode master's own category, not from names."""
        from account.models import PaymentMode

        card = PaymentMode.objects.create(name="Card (test)", category="Bank")
        offered = {row["id"] for row in service.cash_payment_modes()}
        self.assertIn(self.mode.pk, offered)
        self.assertNotIn(card.pk, offered)

    def test_a_bank_payment_mode_is_refused_even_on_a_cash_account(self):
        from account.models import PaymentMode

        self.fund_cash(5000)
        expense = self.make(lines=((300, 1),))
        expense.payment_mode = PaymentMode.objects.create(name="NEFT (test)",
                                                          category="Bank")
        expense.save()
        problems = service.validate(expense)
        self.assertTrue(any("not a cash payment mode" in p for p in problems), problems)

    def test_a_line_may_not_be_charged_to_a_group(self):
        self.fund_cash(5000)
        expense = self.make()
        expense.items.update(account=self.expense_group)
        problems = service.validate(expense)
        self.assertTrue(any("group" in p for p in problems), problems)

    def test_a_shed_on_another_farm_is_refused(self):
        self.fund_cash(5000)
        expense = self.make(shed=self.other_shed)
        self.assertIn("That shed is not on the chosen farm.", service.validate(expense))

    def test_a_farm_on_another_branch_is_refused(self):
        self.fund_cash(5000)
        expense = self.make(farm=self.other_farm)
        self.assertIn("That farm is not on the chosen branch.", service.validate(expense))

    def test_a_date_no_financial_year_covers_is_named_before_the_engine_refuses(self):
        self.fund_cash(5000)
        expense = self.make(expense_date=datetime.date(1999, 5, 1))
        self.assertTrue(any("financial year" in p for p in service.validate(expense)))

    def test_an_expense_with_no_lines_has_nothing_to_post(self):
        expense = self.make(lines=())
        problems = service.validate(expense)
        self.assertIn("Add at least one expense line.", problems)


class CancellationTests(PettyExpenseTestCase):
    def test_cancelling_puts_the_money_back_and_keeps_the_record(self):
        self.fund_cash(5000)
        before = journal.account_balance(self.cash_ledger)
        expense = self.make(lines=((300, 1),))
        service.post(expense, user=self.user)
        service.cancel(expense, user=self.user, reason="Wrong farm")

        expense.refresh_from_db()
        self.assertEqual(expense.status, PettyExpense.STATUS_CANCELLED)
        self.assertEqual(expense.cancel_reason, "Wrong farm")
        self.assertEqual(journal.account_balance(self.cash_ledger), before)
        # The record survives, and so does the voucher it raised.
        self.assertTrue(PettyExpense.objects.filter(pk=expense.pk).exists())
        self.assertIsNotNone(expense.journal_id)

    def test_a_cancelled_expense_cannot_be_posted_again(self):
        self.fund_cash(5000)
        expense = self.make()
        service.post(expense, user=self.user)
        service.cancel(expense, user=self.user)
        with self.assertRaises(service.PettyExpenseError):
            service.post(expense, user=self.user)

    def test_cancelling_a_draft_needs_no_voucher(self):
        expense = self.make()
        service.cancel(expense, user=self.user, reason="Entered by mistake")
        self.assertEqual(expense.status, PettyExpense.STATUS_CANCELLED)


class NumberingTests(PettyExpenseTestCase):
    def test_numbers_run_per_year_from_one(self):
        first = self.make()
        second = self.make()
        self.assertEqual(first.expense_no, f"PE-{TODAY.year}-00001")
        self.assertEqual(second.expense_no, f"PE-{TODAY.year}-00002")

    def test_the_serial_follows_the_highest_number_in_use(self):
        """Deleting a draft frees its number, as every other document number
        in this ERP behaves; what must never happen is two live rows sharing
        one, which the unique constraint is there for."""
        first = self.make()
        first.delete()
        self.assertEqual(self.make().expense_no, f"PE-{TODAY.year}-00001")
        self.assertEqual(
            PettyExpense.objects.values("expense_no").distinct().count(),
            PettyExpense.objects.count())


class ClassificationTests(PettyExpenseTestCase):
    def test_the_categories_offered_are_the_chart_s_own_expense_branch(self):
        """No second classification master: a line's category is an account."""
        groups = service.expense_categories(self.company)
        self.assertTrue(groups, "the chart has no expense ledgers to offer")
        offered = {item["id"] for group in groups for item in group["items"]}
        postable = set(ChartOfAccount.objects.filter(
            company=self.company, account_type__name="Expense", status="Active",
            is_group=False, is_postable=True).values_list("id", flat=True))
        self.assertEqual(offered, postable)

    def test_a_cash_account_reports_the_balance_of_its_own_ledger(self):
        self.fund_cash(1500)
        row = next(a for a in service.paid_from_accounts() if a["id"] == self.cash.pk)
        self.assertTrue(row["is_cash"])
        self.assertEqual(Decimal(str(row["balance"])),
                         journal.account_balance(self.cash_ledger))


# Uploads go to a directory of their own: a test must not leave a bill in the
# project's media folder.
@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="petty-test-media-"))
class SummaryTests(PettyExpenseTestCase):
    """Where the money went, grouped."""

    def all_of_them(self):
        return PettyExpense.objects.all()

    def test_only_posted_spending_counts(self):
        """A draft is not spending and a cancelled expense was undone."""
        self.fund_cash(20000)
        posted = self.make(lines=((300, 1),))
        service.post(posted, user=self.user)
        self.make(lines=((999, 1),))                       # a draft
        cancelled = self.make(lines=((777, 1),))
        service.post(cancelled, user=self.user)
        service.cancel(cancelled, user=self.user)

        report = service.summary(self.all_of_them())
        self.assertEqual(Decimal(str(report["total"])), Decimal("300.00"))
        self.assertEqual(report["expenses"], 1)

    def test_an_expense_split_across_two_categories_counts_in_both(self):
        """Counted from the lines, not from the header — or half the spend
        would land under whichever category happened to be first."""
        from account.models import ChartOfAccount, PettyExpenseItem

        other = ChartOfAccount.objects.filter(
            company=self.company, account_type__name="Expense",
            is_postable=True, is_group=False).exclude(
            pk=self.expense_ledger.pk).order_by("code").first()

        self.fund_cash(20000)
        expense = self.make(lines=((300, 1),))
        PettyExpenseItem.objects.create(petty_expense=expense, line_no=2,
                                        account=other, description="Second",
                                        quantity=1, rate=200)
        expense.recalculate()
        expense.save()
        service.post(expense, user=self.user)

        report = service.summary(self.all_of_them(), group_by="sub_category")
        by_label = {row["label"]: row["amount"] for row in report["rows"]}
        self.assertEqual(len(report["rows"]), 2)
        self.assertEqual(Decimal(str(by_label[self.expense_ledger.description])),
                         Decimal("300.00"))
        self.assertEqual(Decimal(str(by_label[other.description])), Decimal("200.00"))
        # One expense, counted once.
        self.assertEqual(report["expenses"], 1)

    def test_other_charges_reach_the_total_instead_of_vanishing(self):
        """They sit on the header, so a total built only from lines loses them."""
        self.fund_cash(20000)
        expense = self.make(lines=((300, 1),), other_charges=Decimal("50"))
        expense.recalculate()
        expense.save()
        service.post(expense, user=self.user)

        report = service.summary(self.all_of_them())
        self.assertEqual(Decimal(str(report["total"])), Decimal("350.00"))

    def test_the_shares_add_up(self):
        self.fund_cash(20000)
        for rate in (300, 700):
            expense = self.make(lines=((rate, 1),))
            service.post(expense, user=self.user)
        report = service.summary(self.all_of_them())
        self.assertAlmostEqual(sum(r["share"] for r in report["rows"]), 100.0, places=1)

    def test_months_read_in_order_and_everything_else_biggest_first(self):
        self.fund_cash(20000)
        small = self.make(lines=((100, 1),))
        big = self.make(lines=((900, 1),),
                        expense_date=TODAY - datetime.timedelta(days=40))
        service.post(small, user=self.user)
        service.post(big, user=self.user)

        months = [r["label"] for r in service.summary(self.all_of_them(),
                                                      group_by="month")["rows"]]
        self.assertEqual(months, sorted(months))

        payees = service.summary(self.all_of_them(), group_by="payee")["rows"]
        self.assertEqual(payees, sorted(payees, key=lambda r: -r["amount"]))

    def test_an_unknown_grouping_falls_back_rather_than_failing(self):
        report = service.summary(self.all_of_them(), group_by="colour")
        self.assertEqual(report["group_by"], "category")


class TypedTextTests(PettyExpenseTestCase):
    """Three spellings of one payee are one payee once stored."""

    def setUp(self):
        self.client.force_login(self.user)

    def save(self, **over):
        body = {
            "expense_date": TODAY.isoformat(), "branch": self.branch.pk,
            "paid_to_name": "Tea Stall", "payment_mode": self.mode.pk,
            "paid_from": self.cash.pk,
            "items": [{"account": self.expense_ledger.pk, "description": "Tea",
                       "quantity": "1", "rate": "60"}],
        }
        body.update(over)
        response = self.client.post("/api/petty-expenses/save/",
                                    data=json.dumps(body),
                                    content_type="application/json")
        self.assertEqual(response.status_code, 201, response.content)
        return PettyExpense.objects.get(pk=response.json()["id"])

    def test_a_payee_is_stored_in_proper_case_however_it_was_typed(self):
        self.assertEqual(self.save(paid_to_name="  ram   tea stall ").paid_to_name,
                         "Ram Tea Stall")
        self.assertEqual(self.save(paid_to_name="gupta tea stall").paid_to_name,
                         "Gupta Tea Stall")

    def test_capitals_the_typist_meant_are_left_alone(self):
        """Title-casing would turn HDFC into Hdfc, which is worse than leaving it."""
        self.assertEqual(self.save(paid_to_name="HDFC Bank").paid_to_name, "HDFC Bank")
        self.assertEqual(self.save(paid_to_name="UPPCL").paid_to_name, "UPPCL")

    def test_joining_words_stay_small_unless_they_start_the_name(self):
        self.assertEqual(self.save(paid_to_name="ram & sons of akbarpur").paid_to_name,
                         "Ram & Sons of Akbarpur")
        self.assertEqual(self.save(paid_to_name="the tea stall").paid_to_name,
                         "The Tea Stall")

    def test_a_description_is_a_sentence_not_a_headline(self):
        expense = self.save(items=[{"account": self.expense_ledger.pk,
                                    "description": "  tea for the vaccination team ",
                                    "quantity": "1", "rate": "60"}])
        self.assertEqual(expense.items.first().description,
                         "Tea for the vaccination team")

    def test_a_reference_is_stored_the_way_every_other_document_number_is(self):
        self.assertEqual(self.save(reference=" chq-77 ").reference, "CHQ-77")

    def test_tags_are_proper_cased_and_never_repeated(self):
        expense = self.save(tags="farm, local purchase, FARM ,  vehicle")
        self.assertEqual(expense.tags, "Farm, Local Purchase, Vehicle")

    def test_narration_keeps_its_own_words_but_starts_with_a_capital(self):
        expense = self.save(narration="  paid at the counter, no bill given ")
        self.assertEqual(expense.narration, "Paid at the counter, no bill given")

    def test_tidying_makes_the_duplicate_check_work_across_spellings(self):
        """The reason this is worth doing: one payee, one warning."""
        first = self.save(paid_to_name="ram tea stall")
        second = self.save(paid_to_name="  RAM TEA STALL")
        # Stored differently (capitals were meant in the second), but the
        # comparison is case-insensitive, so the repeat is still caught.
        self.assertIsNotNone(service.duplicate_of(second))
        self.assertEqual(first.paid_to_name, "Ram Tea Stall")


class CashBoxTests(PettyExpenseTestCase):
    """Money going into the box, and knowing when there is too little in it."""

    def policy(self, **fields):
        from account.models import PettyCashPolicy

        rule = PettyCashPolicy.get_solo()
        for name, value in fields.items():
            setattr(rule, name, value)
        rule.save()
        return rule

    def test_replenishing_moves_money_from_the_bank_into_the_box(self):
        before_cash = journal.account_balance(self.cash_ledger)
        before_bank = journal.account_balance(self.bank_ledger)

        voucher = service.replenish(self.cash, 10000, self.bank, user=self.user,
                                    reference="CHQ-77")
        self.assertEqual(voucher.voucher_type, "Contra")
        self.assertEqual(journal.account_balance(self.cash_ledger),
                         before_cash + Decimal("10000"))
        self.assertEqual(journal.account_balance(self.bank_ledger),
                         before_bank - Decimal("10000"))

    def test_a_remark_rides_on_the_voucher_where_the_statement_will_read_it(self):
        voucher = service.replenish(self.cash, 5000, self.bank, user=self.user,
                                    reference="chq-9",
                                    remark="Month-end top-up for the vaccination round")
        self.assertIn("Month-end top-up", voucher.narration)
        self.assertIn("Cash drawn from", voucher.narration)
        # The engine's half is kept apart from the person's.
        self.assertNotIn("Month-end", voucher.auto_narration)
        self.assertEqual(voucher.narration_source, "MANUAL")

    def test_without_a_remark_the_narration_is_the_engine_s_own(self):
        voucher = service.replenish(self.cash, 5000, self.bank, user=self.user)
        self.assertEqual(voucher.narration, voucher.auto_narration)
        self.assertEqual(voucher.narration_source, "AUTO")

    def test_a_cash_box_is_not_replenished_from_another_cash_box(self):
        with self.assertRaises(service.PettyExpenseError):
            service.replenish(self.cash, 500, self.cash, user=self.user)

    def test_nothing_is_a_refusal_not_an_empty_voucher(self):
        with self.assertRaises(service.PettyExpenseError):
            service.replenish(self.cash, 0, self.bank, user=self.user)

    def test_the_box_reports_itself_low_against_the_policy_s_float(self):
        self.policy(float_amount=Decimal("10000"), low_balance_at=Decimal("2000"))
        self.fund_cash(1500)
        row = next(r for r in service.cash_health() if r["id"] == self.cash.pk)
        self.assertTrue(row["low"])
        self.assertEqual(Decimal(str(row["top_up"])), Decimal("8500"))

        service.replenish(self.cash, 8500, self.bank, user=self.user)
        row = next(r for r in service.cash_health() if r["id"] == self.cash.pk)
        self.assertFalse(row["low"])
        self.assertEqual(Decimal(str(row["top_up"])), Decimal("0"))

    def test_the_replenish_endpoint_is_the_same_path(self):
        self.client.force_login(self.user)
        before = journal.account_balance(self.cash_ledger)
        response = self.client.post(
            "/api/petty-cash/replenish/",
            data=json.dumps({"box": self.cash.pk, "from": self.bank.pk,
                             "amount": "2500", "date": TODAY.isoformat(),
                             "reference": "Slip 12"}),
            content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["voucher_no"])
        self.assertEqual(journal.account_balance(self.cash_ledger),
                         before + Decimal("2500"))


class PolicyTests(PettyExpenseTestCase):
    def policy(self, **fields):
        from account.models import PettyCashPolicy

        rule = PettyCashPolicy.get_solo()
        for name, value in fields.items():
            setattr(rule, name, value)
        rule.save()
        return rule

    def test_a_large_expense_needs_its_bill(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.policy(bill_required_above=Decimal("500"))
        self.fund_cash(5000)
        expense = self.make(lines=((900, 1),))
        self.assertTrue(any("Attach the bill" in p for p in service.validate(expense)))

        expense.attachments.create(
            file=SimpleUploadedFile("bill.pdf", b"%PDF", content_type="application/pdf"),
            file_name="bill.pdf", file_type="application/pdf")
        self.assertFalse(any("Attach the bill" in p for p in service.validate(expense)))

    def test_a_small_one_does_not(self):
        self.policy(bill_required_above=Decimal("500"))
        self.fund_cash(5000)
        expense = self.make(lines=((300, 1),))
        self.assertFalse(any("Attach the bill" in p for p in service.validate(expense)))

    def test_the_same_payment_twice_in_a_day_is_noticed(self):
        self.fund_cash(5000)
        first = self.make(lines=((300, 1),))
        second = self.make(lines=((300, 1),))
        twin = service.duplicate_of(second)
        self.assertIsNotNone(twin)
        self.assertEqual(twin.pk, first.pk)

    def test_a_different_amount_is_not_a_duplicate(self):
        self.fund_cash(5000)
        self.make(lines=((300, 1),))
        self.assertIsNone(service.duplicate_of(self.make(lines=((400, 1),))))

    def test_the_warning_can_be_switched_off(self):
        self.policy(warn_on_duplicates=False)
        self.fund_cash(5000)
        self.make(lines=((300, 1),))
        self.assertIsNone(service.duplicate_of(self.make(lines=((300, 1),))))

    def test_a_duplicate_is_reported_on_save_but_does_not_stop_it(self):
        self.client.force_login(self.user)
        self.fund_cash(5000)
        body = json.dumps({
            "expense_date": TODAY.isoformat(), "branch": self.branch.pk,
            "paid_to_name": "Tea Stall", "payment_mode": self.mode.pk,
            "paid_from": self.cash.pk,
            "items": [{"account": self.expense_ledger.pk, "description": "Tea",
                       "quantity": "2", "rate": "60"}]})
        first = self.client.post("/api/petty-expenses/save/", data=body,
                                 content_type="application/json").json()
        self.assertEqual(first["duplicate"], "")
        second = self.client.post("/api/petty-expenses/save/", data=body,
                                  content_type="application/json").json()
        self.assertIn(first["expense_no"], second["duplicate"])
        self.assertTrue(PettyExpense.objects.filter(pk=second["id"]).exists())


class ScopeTests(PettyExpenseTestCase):
    """A user limited to one branch sees one branch.

    The limit is the ERP's own Web-Access scope, so a single setting governs
    this register and every other screen.
    """

    def setUp(self):
        from django.contrib.auth.models import Group

        from user.models import GroupAccessProfile

        self.local = get_user_model().objects.create_user(
            username="akbarpur-only", password="x")
        group = Group.objects.create(name="Akbarpur clerks")
        self.local.groups.add(group)
        profile = GroupAccessProfile.objects.create(group=group,
                                                    access_type="custom",
                                                    all_branches=False)
        profile.branches.add(self.other_branch)

        # They may work the screen; what they may not do is see another
        # branch's rows through it. The two are separate settings, and this
        # test is about the second.
        from user.models import GroupTabPermission
        GroupTabPermission.objects.create(
            group=group, tab_code="petty_expense_list", can_view=True,
            can_add=True, can_edit=True, can_delete=True)

        # One expense on each branch.
        self.here = self.make(lines=((300, 1),))
        self.there = self.make(lines=((400, 1),), branch=self.other_branch,
                               farm=self.other_farm)
        self.client.force_login(self.local)

    def test_the_register_shows_only_the_branch_they_are_given(self):
        rows = self.client.get("/api/petty-expenses/").json()["rows"]
        numbers = {r["expense_no"] for r in rows}
        self.assertIn(self.there.expense_no, numbers)
        self.assertNotIn(self.here.expense_no, numbers)

    def test_the_figures_above_it_are_scoped_too(self):
        """A total that counts branches you cannot open is a leak of its own."""
        cards = self.client.get("/api/petty-expenses/").json()["cards"]
        self.assertEqual(cards["drafts"], 1)

    def test_another_branch_s_expense_cannot_even_be_read(self):
        self.assertEqual(
            self.client.get(f"/api/petty-expenses/{self.here.pk}/").status_code, 404)
        self.assertEqual(
            self.client.get(f"/petty-expenses/{self.here.pk}/edit/").status_code, 404)

    def test_another_branch_s_expense_cannot_be_posted_or_deleted(self):
        self.assertEqual(
            self.client.post(f"/api/petty-expenses/{self.here.pk}/post/").status_code, 404)
        self.assertEqual(
            self.client.post(f"/api/petty-expenses/{self.here.pk}/delete/").status_code, 404)
        self.assertTrue(PettyExpense.objects.filter(pk=self.here.pk).exists())

    def test_the_pickers_offer_only_what_they_may_use(self):
        from account.petty_api import _masters

        masters = _masters(self.local)
        self.assertEqual([b["id"] for b in masters["branches"]],
                         [self.other_branch.pk])
        self.assertNotIn(self.farm.pk, [f["id"] for f in masters["farms"]])

    def test_a_branch_out_of_scope_is_refused_even_if_the_payload_names_it(self):
        """The picker is a convenience; the server is the rule."""
        body = json.dumps({
            "expense_date": TODAY.isoformat(),
            "branch": self.branch.pk,          # not theirs
            "paid_to_name": "Tea Stall",
            "payment_mode": self.mode.pk,
            "paid_from": self.cash.pk,
            "items": [{"account": self.expense_ledger.pk, "description": "Tea",
                       "quantity": "1", "rate": "60"}],
        })
        response = self.client.post("/api/petty-expenses/save/", data=body,
                                    content_type="application/json")
        self.assertEqual(response.status_code, 403)
        self.assertIn("not one of yours", response.json()["error"])


class NarrationTests(PettyExpenseTestCase):
    def test_the_voucher_records_what_the_engine_wrote(self):
        self.fund_cash(5000)
        expense = self.make(lines=((300, 1),))
        expense.narration = service.compose_narration(expense)
        expense.save()
        voucher = service.post(expense, user=self.user)
        self.assertEqual(voucher.auto_narration, expense.narration)
        self.assertEqual(voucher.narration_source, "AUTO")

    def test_a_narration_someone_rewrote_is_marked_as_theirs(self):
        self.fund_cash(5000)
        expense = self.make(lines=((300, 1),))
        expense.narration = "Tea for the vaccination team, as agreed with the vet."
        expense.save()
        voucher = service.post(expense, user=self.user)
        self.assertEqual(voucher.narration, expense.narration)
        self.assertEqual(voucher.narration_source, "MANUAL")
        self.assertEqual(voucher.narration_edited_by, self.user)

    def test_narration_switched_off_for_the_company_is_honoured_here(self):
        from account.models import NarrationSettings

        settings = NarrationSettings.get_solo()
        settings.enabled = False
        settings.save()

        self.fund_cash(5000)
        expense = self.make(lines=((300, 1),))
        expense.narration = ""
        expense.save()
        voucher = service.post(expense, user=self.user)
        self.assertEqual(voucher.narration, "")
        self.assertEqual(voucher.auto_narration, "")


class EndpointTests(PettyExpenseTestCase):
    @classmethod
    def tearDownClass(cls):
        from django.conf import settings
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.client.force_login(self.user)

    def payload(self, **over):
        body = {
            "expense_date": TODAY.isoformat(),
            "branch": self.branch.pk,
            "farm": self.farm.pk,
            "paid_to_name": "Tea Stall",
            "payment_mode": self.mode.pk,
            "paid_from": self.cash.pk,
            "items": [{"account": self.expense_ledger.pk, "description": "Tea",
                       "quantity": "2", "rate": "60"}],
        }
        body.update(over)
        return json.dumps(body)

    def post_json(self, url, body):
        return self.client.post(url, data=body, content_type="application/json")

    def test_save_and_post_in_one_step_puts_it_on_the_books(self):
        self.fund_cash(5000)
        response = self.post_json("/api/petty-expenses/save/", self.payload(post=True))
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["status"], "Posted")
        self.assertTrue(body["voucher_no"])
        self.assertEqual(journal.account_balance(self.expense_ledger), Decimal("120.00"))

    def test_a_refused_post_keeps_the_draft_so_nothing_is_typed_twice(self):
        response = self.post_json("/api/petty-expenses/save/", self.payload(post=True))
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertIn("Not enough petty cash", body["error"])
        self.assertEqual(PettyExpense.objects.get(pk=body["id"]).status,
                         PettyExpense.STATUS_DRAFT)

    def test_a_saved_draft_is_given_a_narration_it_did_not_have_to_type(self):
        response = self.post_json("/api/petty-expenses/save/", self.payload())
        expense = PettyExpense.objects.get(pk=response.json()["id"])
        self.assertIn("Green Valley", expense.narration)
        self.assertIn("Farm Cash Box", expense.narration)

    def test_a_farm_on_the_chosen_branch_is_not_reported_as_being_elsewhere(self):
        """The form sends its pickers as strings, and a string id compared
        with an integer one told the user their own farm was on another
        branch. Sent exactly as the browser sends it."""
        self.fund_cash(5000)
        response = self.post_json("/api/petty-expenses/save/", self.payload(
            branch=str(self.branch.pk), farm=str(self.farm.pk),
            shed=str(self.shed.pk), post=True))
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["status"], "Posted")

    def test_the_register_reports_what_is_posted_and_what_is_still_a_draft(self):
        self.fund_cash(5000)
        self.post_json("/api/petty-expenses/save/", self.payload(post=True))
        self.post_json("/api/petty-expenses/save/", self.payload())

        rows = self.client.get("/api/petty-expenses/").json()
        self.assertEqual(len(rows["rows"]), 2)
        self.assertEqual(rows["cards"]["drafts"], 1)
        # Today's figure counts only what is on the books.
        self.assertEqual(Decimal(str(rows["cards"]["today"])), Decimal("120.00"))
        cash = next(c for c in rows["cards"]["cash"] if c["label"].endswith("Farm Cash Box")
                    or "Farm Cash Box" in c["label"])
        self.assertEqual(Decimal(str(cash["balance"])), Decimal("4880.00"))

    def test_the_register_filters_by_branch_status_and_amount(self):
        self.fund_cash(5000)
        self.post_json("/api/petty-expenses/save/", self.payload(post=True))
        self.post_json("/api/petty-expenses/save/", self.payload())

        self.assertEqual(
            len(self.client.get("/api/petty-expenses/?status=Posted").json()["rows"]), 1)
        self.assertEqual(
            len(self.client.get(
                f"/api/petty-expenses/?branch={self.other_branch.pk}").json()["rows"]), 0)
        self.assertEqual(
            len(self.client.get("/api/petty-expenses/?min=500").json()["rows"]), 0)

    def test_post_and_cancel_through_the_endpoints_the_register_uses(self):
        self.fund_cash(5000)
        created = self.post_json("/api/petty-expenses/save/", self.payload()).json()
        posted = self.client.post(f"/api/petty-expenses/{created['id']}/post/")
        self.assertEqual(posted.status_code, 200, posted.content)
        self.assertTrue(posted.json()["voucher_no"])

        cancelled = self.post_json(f"/api/petty-expenses/{created['id']}/cancel/",
                                   json.dumps({"reason": "Duplicate"}))
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.json()["status"], "Cancelled")
        self.assertEqual(journal.account_balance(self.cash_ledger), Decimal("5000.00"))

    def test_both_pages_render_for_someone_allowed_to_see_them(self):
        self.fund_cash(5000)
        created = self.post_json("/api/petty-expenses/save/", self.payload()).json()
        self.assertEqual(self.client.get("/petty-expenses/").status_code, 200)
        self.assertEqual(self.client.get("/petty-expenses/new/").status_code, 200)
        self.assertEqual(
            self.client.get(f"/petty-expenses/{created['id']}/edit/").status_code, 200)

    def test_a_draft_can_be_deleted(self):
        self.fund_cash(5000)
        draft = self.post_json("/api/petty-expenses/save/", self.payload()).json()
        gone = self.client.post(f"/api/petty-expenses/{draft['id']}/delete/")
        self.assertEqual(gone.status_code, 200, gone.content)
        self.assertFalse(PettyExpense.objects.filter(pk=draft["id"]).exists())

    def test_deleting_a_posted_expense_takes_its_voucher_off_the_books(self):
        """Asked for deliberately: the voucher goes, and so does its effect.

        What it costs is that voucher's number, which cancelling would keep.
        """
        from account.models import Voucher

        self.fund_cash(5000)
        before = journal.account_balance(self.cash_ledger)
        posted = self.post_json("/api/petty-expenses/save/",
                                self.payload(post=True)).json()
        voucher_id = PettyExpense.objects.get(pk=posted["id"]).journal_id

        gone = self.client.post(f"/api/petty-expenses/{posted['id']}/delete/")
        self.assertEqual(gone.status_code, 200, gone.content)
        self.assertEqual(gone.json()["voucher_no"], posted["voucher_no"])
        self.assertFalse(PettyExpense.objects.filter(pk=posted["id"]).exists())
        self.assertFalse(Voucher.objects.filter(pk=voucher_id).exists())
        # The money is back where it was, because the voucher's lines went too.
        self.assertEqual(journal.account_balance(self.cash_ledger), before)

    def test_deleting_a_cancelled_expense_removes_its_cancelled_voucher(self):
        from account.models import Voucher

        self.fund_cash(5000)
        created = self.post_json("/api/petty-expenses/save/",
                                 self.payload(post=True)).json()
        voucher_id = PettyExpense.objects.get(pk=created["id"]).journal_id
        self.post_json(f"/api/petty-expenses/{created['id']}/cancel/",
                       json.dumps({"reason": "Wrong account"}))
        gone = self.client.post(f"/api/petty-expenses/{created['id']}/delete/")
        self.assertEqual(gone.status_code, 200)
        self.assertFalse(Voucher.objects.filter(pk=voucher_id).exists())

    def test_editing_a_posted_expense_rewrites_what_it_put_on_the_books(self):
        """The voucher is replaced, not patched, so the two cannot disagree."""
        from account.models import Voucher

        self.fund_cash(5000)
        created = self.post_json("/api/petty-expenses/save/",
                                 self.payload(post=True)).json()
        old_voucher_id = PettyExpense.objects.get(pk=created["id"]).journal_id
        self.assertEqual(journal.account_balance(self.expense_ledger),
                         Decimal("120.00"))

        # 2 x 60 was really 2 x 90.
        edited = self.post_json(
            f"/api/petty-expenses/{created['id']}/save/",
            self.payload(items=[{"account": self.expense_ledger.pk,
                                 "description": "Tea", "quantity": "2",
                                 "rate": "90"}]))
        self.assertEqual(edited.status_code, 200, edited.content)

        expense = PettyExpense.objects.get(pk=created["id"])
        self.assertEqual(expense.status, PettyExpense.STATUS_POSTED)
        self.assertEqual(expense.net_amount, Decimal("180.00"))
        self.assertNotEqual(expense.journal_id, old_voucher_id)
        self.assertFalse(Voucher.objects.filter(pk=old_voucher_id).exists())
        # One entry for one expense, at the corrected figure.
        self.assertEqual(journal.account_balance(self.expense_ledger),
                         Decimal("180.00"))
        self.assertEqual(expense.journal.total_debit, Decimal("180.00"))

    def test_an_edit_that_cannot_post_leaves_the_posted_expense_alone(self):
        """A refused correction must not quietly unpost what was there."""
        self.fund_cash(500)
        created = self.post_json("/api/petty-expenses/save/",
                                 self.payload(post=True)).json()
        voucher_id = PettyExpense.objects.get(pk=created["id"]).journal_id

        refused = self.post_json(
            f"/api/petty-expenses/{created['id']}/save/",
            self.payload(items=[{"account": self.expense_ledger.pk,
                                 "description": "Tea", "quantity": "1",
                                 "rate": "99999"}]))
        self.assertEqual(refused.status_code, 400)
        self.assertIn("Not enough petty cash", refused.json()["error"])

        expense = PettyExpense.objects.get(pk=created["id"])
        self.assertEqual(expense.status, PettyExpense.STATUS_POSTED)
        self.assertEqual(expense.journal_id, voucher_id)
        self.assertEqual(expense.net_amount, Decimal("120.00"))

    def test_a_cancelled_expense_cannot_be_edited(self):
        """It is the record of something undone; correcting it would be
        rewriting history rather than fixing it."""
        self.fund_cash(5000)
        created = self.post_json("/api/petty-expenses/save/",
                                 self.payload(post=True)).json()
        self.post_json(f"/api/petty-expenses/{created['id']}/cancel/",
                       json.dumps({"reason": "Wrong account"}))
        refused = self.post_json(f"/api/petty-expenses/{created['id']}/save/",
                                 self.payload())
        self.assertEqual(refused.status_code, 400)
        self.assertIn("cannot be edited", refused.json()["error"])

    def test_deleting_a_draft_takes_its_bills_with_it(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from account.models import PettyExpenseAttachment

        created = self.post_json("/api/petty-expenses/save/", self.payload()).json()
        bill = SimpleUploadedFile("bill.pdf", b"%PDF-1.4 x", content_type="application/pdf")
        self.client.post(f"/api/petty-expenses/{created['id']}/attach/", {"files": [bill]})
        self.client.post(f"/api/petty-expenses/{created['id']}/delete/")
        self.assertEqual(PettyExpenseAttachment.objects.count(), 0)

    def test_a_bill_can_be_attached_and_only_a_draft_can_lose_it(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.fund_cash(5000)
        created = self.post_json("/api/petty-expenses/save/", self.payload()).json()
        bill = SimpleUploadedFile("bill.pdf", b"%PDF-1.4 tea", content_type="application/pdf")
        attached = self.client.post(f"/api/petty-expenses/{created['id']}/attach/",
                                    {"files": [bill]})
        self.assertEqual(attached.status_code, 200, attached.content)
        attachment_id = attached.json()["saved"][0]["id"]

        # While it is a draft, a bill attached by mistake can be taken off.
        removed = self.client.post(
            f"/api/petty-expenses/{created['id']}/attach/{attachment_id}/delete/")
        self.assertEqual(removed.status_code, 200)

        # Once posted, the evidence stays with the entry.
        bill = SimpleUploadedFile("bill.pdf", b"%PDF-1.4 tea", content_type="application/pdf")
        again = self.client.post(f"/api/petty-expenses/{created['id']}/attach/",
                                 {"files": [bill]}).json()["saved"][0]["id"]
        self.client.post(f"/api/petty-expenses/{created['id']}/post/")
        refused = self.client.post(
            f"/api/petty-expenses/{created['id']}/attach/{again}/delete/")
        self.assertEqual(refused.status_code, 400)
        self.assertIn("keeps its attachments", refused.json()["error"])

    def test_a_file_that_is_not_a_bill_is_refused_by_name(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        created = self.post_json("/api/petty-expenses/save/", self.payload()).json()
        bad = SimpleUploadedFile("notes.exe", b"MZ", content_type="application/x-msdownload")
        response = self.client.post(f"/api/petty-expenses/{created['id']}/attach/",
                                    {"files": [bad]})
        self.assertEqual(response.status_code, 400)
        self.assertIn("notes.exe", response.json()["refused"][0])

    def test_one_expense_reads_back_whole(self):
        self.fund_cash(5000)
        created = self.post_json("/api/petty-expenses/save/", self.payload()).json()
        detail = self.client.get(f"/api/petty-expenses/{created['id']}/").json()
        self.assertEqual(detail["expense_no"], created["expense_no"])
        self.assertEqual(len(detail["items"]), 1)
        self.assertEqual(Decimal(str(detail["net_amount"])), Decimal("120.00"))
        self.assertTrue(detail["editable"])
