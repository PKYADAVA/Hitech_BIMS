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
        cls.mode, _ = PaymentMode.objects.get_or_create(name="Cash")
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

    def test_a_bank_account_may_go_overdrawn_where_a_cash_box_may_not(self):
        """There is no overdraft in a cash box; a bank account is the bank's
        business, not this screen's."""
        expense = self.make(lines=((300, 1),), paid_from=self.bank)
        service.post(expense, user=self.user)
        self.assertEqual(expense.status, PettyExpense.STATUS_POSTED)

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
