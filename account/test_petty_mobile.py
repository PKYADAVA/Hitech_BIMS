"""The petty expense register on the phone.

The endpoints delegate to the web module's own views, so these tests are
about the delegation: that the phone reaches the same rows, the same figures
and the same posting, that a refusal comes back as a refusal, and that the
matrix still governs who may do it.
"""
from __future__ import annotations

import datetime
import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APITestCase

from account.models import PettyExpense
from account.test_petty_expense import PettyExpenseTestCase, TODAY


class PettyExpenseMobileTests(PettyExpenseTestCase, APITestCase):
    """One fixture, two front doors: these are the phone's."""

    ROWS = "/api/v1/account/petty-expenses/rows"
    MASTERS = "/api/v1/account/petty-expenses/masters"
    SAVE = "/api/v1/account/petty-expenses/save"

    def setUp(self):
        self.client.force_authenticate(self.user)

    def body(self, **over):
        payload = {
            "expense_date": TODAY.isoformat(),
            "branch": str(self.branch.pk),
            "farm": str(self.farm.pk),
            "paid_to_name": "Ramesh Kumar",
            "payment_mode": self.mode.pk,
            "paid_from": self.cash.pk,
            "items": [{"account": self.expense_ledger.pk, "description": "Diesel",
                       "quantity": "20", "rate": "92"}],
        }
        payload.update(over)
        return payload

    # -- the register -----------------------------------------------------

    def test_the_list_carries_the_figures_above_it(self):
        """One call, because the tiles are counted from the rows' own
        queryset -- asking twice is how a total stops matching its list."""
        self.fund_cash(20000)
        self.make(lines=((300, 1),))
        response = self.client.get(self.ROWS)
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()["data"]
        self.assertIn("rows", data)
        self.assertIn("cards", data)
        self.assertEqual(data["cards"]["drafts"], 1)
        self.assertEqual(len(data["rows"]), 1)

    def test_the_phone_filters_are_the_registers_filters(self):
        self.make(lines=((300, 1),))
        old = self.make(lines=((400, 1),))
        old.expense_date = TODAY - datetime.timedelta(days=60)
        old.save(update_fields=["expense_date"])

        response = self.client.get(self.ROWS, {
            "from": TODAY.isoformat(), "to": TODAY.isoformat()})
        numbers = {r["expense_no"] for r in response.json()["data"]["rows"]}
        self.assertNotIn(old.expense_no, numbers)

    def test_a_row_says_what_the_phone_list_shows(self):
        """Every field the design puts on a row comes from this one call."""
        expense = self.make(lines=((300, 1),))
        row = self.client.get(self.ROWS).json()["data"]["rows"][0]
        for key in ("expense_no", "date", "branch", "farm", "category",
                    "paid_to", "amount", "status", "bills"):
            self.assertIn(key, row, key)
        self.assertEqual(row["expense_no"], expense.expense_no)

    # -- the entry screen -------------------------------------------------

    def test_the_pickers_are_filled_from_one_call(self):
        masters = self.client.get(self.MASTERS).json()["data"]
        for key in ("branches", "farms", "sheds", "batches", "categories",
                    "groups", "paid_from", "modes", "uoms"):
            self.assertIn(key, masters, key)
        self.assertTrue(masters["branches"])
        self.assertTrue(masters["categories"])

    def test_saving_and_posting_from_the_phone_puts_it_on_the_books(self):
        self.fund_cash(20000)
        response = self.client.post(self.SAVE, self.body(post=True), format="json")
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()["data"]
        self.assertEqual(data["status"], "Posted")
        self.assertTrue(data["voucher_no"])

    def test_a_draft_saved_on_the_phone_is_a_draft_on_the_web(self):
        response = self.client.post(self.SAVE, self.body(), format="json")
        expense = PettyExpense.objects.get(pk=response.json()["data"]["id"])
        self.assertEqual(expense.status, PettyExpense.STATUS_DRAFT)
        self.assertEqual(expense.paid_to_name, "Ramesh Kumar")

    def test_a_refusal_reads_as_a_refusal(self):
        """The cash box is empty, so posting is refused -- and the phone is
        told why rather than being handed a 500."""
        response = self.client.post(self.SAVE, self.body(post=True), format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Not enough petty cash", json.dumps(response.json()))

    def test_an_expense_opens_again_in_full(self):
        expense = self.make(lines=((300, 1),))
        data = self.client.get(
            f"/api/v1/account/petty-expenses/{expense.pk}").json()["data"]
        self.assertEqual(data["expense_no"], expense.expense_no)
        self.assertEqual(len(data["items"]), 1)

    def test_posting_a_draft_from_the_row_menu(self):
        self.fund_cash(20000)
        expense = self.make(lines=((300, 1),))
        response = self.client.post(
            f"/api/v1/account/petty-expenses/{expense.pk}/post")
        self.assertEqual(response.status_code, 200, response.content)
        expense.refresh_from_db()
        self.assertEqual(expense.status, PettyExpense.STATUS_POSTED)

    # -- who may --------------------------------------------------------

    def test_the_phone_is_held_to_the_same_matrix(self):
        """Mapped to the register's own tab, so a user the matrix does not
        give it to is refused here exactly as they are in the browser."""
        from user.models import GroupTabPermission

        outsider = get_user_model().objects.create_user(
            username="outsider", password="x")
        group = Group.objects.create(name="Hatchery only")
        outsider.groups.add(group)
        GroupTabPermission.objects.create(
            group=group, tab_code="batches", can_view=True)

        self.client.force_authenticate(outsider)
        self.assertEqual(self.client.get(self.ROWS).status_code, 403)
        self.assertEqual(
            self.client.post(self.SAVE, self.body(), format="json").status_code, 403)

    def test_without_a_login_nothing_is_reachable(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.ROWS).status_code, 401)
