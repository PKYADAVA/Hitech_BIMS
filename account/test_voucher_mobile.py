"""The journal register on the phone.

The endpoints delegate to the web module's own views, so these are about the
delegation: that the phone reaches the same rows and figures, that a voucher
comes back with the lines that make it balance, that posting and cancelling
run the engine's rules, and that the two endings stay apart -- a draft is
deleted, a posted voucher is cancelled.
"""
from __future__ import annotations

import datetime

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APITestCase

from account.models import ChartOfAccount, FinancialYear, Voucher
from account.tests import EngineTestCase


class VoucherMobileTests(EngineTestCase, APITestCase):
    """One fixture, two front doors: these are the phone's."""

    ROWS = "/api/v1/account/vouchers/rows"
    CARDS = "/api/v1/account/vouchers/cards"

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # The year a voucher falls in has to exist before anything can post,
        # and it has to cover today as well as the dates these tests name.
        today = datetime.date.today()
        start = datetime.date(today.year if today.month >= 4 else today.year - 1, 4, 1)
        FinancialYear.objects.create(
            start_date=min(start, datetime.date(2026, 4, 1)),
            end_date=max(start.replace(year=start.year + 1) - datetime.timedelta(days=1),
                         datetime.date(2027, 3, 31)),
            is_active=True,
        )

    def setUp(self):
        self.generate()
        self.cash = ChartOfAccount.objects.get(company=self.company,
                                               system_role="CASH_IN_HAND")
        self.broiler_sales = ChartOfAccount.objects.get(company=self.company,
                                                        description="Broiler Sales")
        self.client.force_authenticate(self.user)

    def make(self, post=True, amount="1000", date="2026-05-01", **over):
        from account.services import journal

        return journal.create_voucher(
            company=self.company,
            date=date,
            lines_data=[
                {"account": self.cash.id, "debit": amount, "credit": 0},
                {"account": self.broiler_sales.id, "debit": 0, "credit": amount},
            ],
            user=self.user,
            post=post,
            **over,
        )

    # -- the register -----------------------------------------------------

    def test_the_rows_are_the_registers_rows(self):
        voucher = self.make()
        rows = self.client.get(self.ROWS).json()["data"]["results"]
        self.assertIn(voucher.voucher_no, [r["voucher_no"] for r in rows])
        row = next(r for r in rows if r["voucher_no"] == voucher.voucher_no)
        for key in ("date", "voucher_type", "narration", "total_debit", "status"):
            self.assertIn(key, row, key)

    def test_the_phone_filters_are_the_registers_filters(self):
        self.make(date="2026-05-01")
        old = self.make(date="2026-04-02")
        rows = self.client.get(self.ROWS, {
            "date_from": "2026-05-01", "date_to": "2026-05-31"}).json()["data"]["results"]
        self.assertNotIn(old.voucher_no, [r["voucher_no"] for r in rows])

    def test_the_figures_are_counted_over_the_company(self):
        """Not over whatever the register is filtered to: a figure that moves
        with the filter under it tells you nothing you could not already see."""
        today = datetime.date.today()
        self.make(post=True, amount="500", date=today.isoformat())
        self.make(post=False, amount="700", date=today.isoformat())

        cards = self.client.get(self.CARDS).json()["data"]
        self.assertEqual(cards["today"], "500.00")
        self.assertEqual(cards["drafts"], 1)
        self.assertIn("month", cards)
        self.assertIn("cancelled", cards)

    # -- one voucher ------------------------------------------------------

    def test_a_voucher_comes_back_with_the_lines_that_balance_it(self):
        voucher = self.make(amount="1200")
        data = self.client.get(f"/api/v1/account/vouchers/{voucher.pk}/full").json()["data"]
        self.assertEqual(data["voucher_no"], voucher.voucher_no)
        self.assertEqual(len(data["lines"]), 2)
        debit = sum(float(line["debit"]) for line in data["lines"])
        credit = sum(float(line["credit"]) for line in data["lines"])
        self.assertEqual(debit, credit)
        self.assertEqual(debit, 1200)

    # -- writing one ------------------------------------------------------

    def test_the_pickers_are_filled_from_one_call(self):
        masters = self.client.get("/api/v1/account/vouchers/masters").json()["data"]
        for key in ("accounts", "types", "sectors", "centres"):
            self.assertIn(key, masters, key)
        self.assertTrue(masters["accounts"])
        # Only what a line may actually be charged to: a group account offered
        # here is a refusal offered here.
        ids = {a["id"] for a in masters["accounts"]}
        groups = ChartOfAccount.objects.filter(company=self.company, is_group=True)
        self.assertFalse(ids & {g.id for g in groups})

    def test_a_voucher_written_on_the_phone_posts(self):
        body = {
            "date": "2026-05-02",
            "voucher_type": "Journal",
            "narration": "Written on the phone",
            "lines": [
                {"account": self.cash.id, "debit": "400", "credit": "0"},
                {"account": self.broiler_sales.id, "debit": "0", "credit": "400"},
            ],
            "post": True,
        }
        response = self.client.post("/api/v1/account/vouchers/save", body, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()["data"]
        self.assertEqual(data["status"], "Posted")
        self.assertTrue(data["voucher_no"])

    def test_an_unbalanced_entry_is_refused_in_the_engines_words(self):
        """The screen does not check this and must not: the engine is the one
        that knows, and its refusal is what the phone shows."""
        body = {
            "date": "2026-05-02",
            "voucher_type": "Journal",
            "narration": "Lopsided",
            "lines": [
                {"account": self.cash.id, "debit": "400", "credit": "0"},
                {"account": self.broiler_sales.id, "debit": "0", "credit": "250"},
            ],
            "post": True,
        }
        response = self.client.post("/api/v1/account/vouchers/save", body, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("balance", str(response.json()).lower())
        self.assertFalse(Voucher.objects.filter(narration="Lopsided").exists())

    def test_a_draft_can_be_rewritten_from_the_phone(self):
        draft = self.make(post=False, amount="100")
        body = {
            "date": "2026-05-03",
            "narration": "Corrected on the phone",
            "lines": [
                {"account": self.cash.id, "debit": "900", "credit": "0"},
                {"account": self.broiler_sales.id, "debit": "0", "credit": "900"},
            ],
        }
        response = self.client.post(f"/api/v1/account/vouchers/save/{draft.pk}",
                                    body, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        draft.refresh_from_db()
        self.assertEqual(draft.narration, "Corrected on the phone")
        self.assertEqual(draft.total_debit, 900)

    # -- the two endings --------------------------------------------------

    def test_posting_a_draft_from_the_phone_numbers_it(self):
        draft = self.make(post=False)
        self.assertEqual(draft.status, "Draft")
        response = self.client.post(f"/api/v1/account/vouchers/{draft.pk}/post")
        self.assertEqual(response.status_code, 200, response.content)
        draft.refresh_from_db()
        self.assertEqual(draft.status, "Posted")
        self.assertTrue(draft.voucher_no)

    def test_cancelling_a_posted_voucher_keeps_it(self):
        voucher = self.make()
        response = self.client.post(f"/api/v1/account/vouchers/{voucher.pk}/cancel",
                                    {"reason": "entered twice"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        voucher.refresh_from_db()
        self.assertEqual(voucher.status, "Cancelled")
        self.assertTrue(Voucher.objects.filter(pk=voucher.pk).exists())

    def test_a_draft_can_be_deleted(self):
        draft = self.make(post=False)
        response = self.client.delete(f"/api/v1/account/vouchers/{draft.pk}/full")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(Voucher.objects.filter(pk=draft.pk).exists())

    def test_a_posted_voucher_cannot_be_deleted(self):
        """The rule the web states in its own words, reaching the phone as a
        refusal rather than as a button that half works."""
        voucher = self.make()
        response = self.client.delete(f"/api/v1/account/vouchers/{voucher.pk}/full")
        self.assertEqual(response.status_code, 400)
        self.assertIn("cancel posted vouchers", str(response.json()).lower())
        self.assertTrue(Voucher.objects.filter(pk=voucher.pk).exists())

    # -- who may ----------------------------------------------------------

    def test_the_phone_is_held_to_the_same_matrix(self):
        from user.models import GroupTabPermission

        outsider = get_user_model().objects.create_user(username="nojournal", password="x")
        group = Group.objects.create(name="Hatchery only")
        outsider.groups.add(group)
        GroupTabPermission.objects.create(group=group, tab_code="batches", can_view=True)

        self.client.force_authenticate(outsider)
        self.assertEqual(self.client.get(self.ROWS).status_code, 403)
        self.assertEqual(self.client.get(self.CARDS).status_code, 403)

    def test_without_a_login_nothing_is_reachable(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.ROWS).status_code, 401)
