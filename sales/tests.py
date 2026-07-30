import json
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from inventory.models import Warehouse
from sales.models import Customer, CustomerCreditNote, CustomerDebitNote
from sales.views import _customer_balance_row


class CustomerNoteTests(TestCase):
    """Customer Debit / Credit Notes — the sales-side counterpart of the
    supplier notes in purchase.

    A debit note raises what the customer owes, a credit note reduces it, and
    both have to reach the Customer Ledger and Customer Balance to be worth
    anything.
    """

    def setUp(self):
        user = get_user_model().objects.create_superuser(
            "sales-tester", "s@example.com", "Str0ngPass!")
        self.client.force_login(user)
        self.customer = Customer.objects.create(
            name="Test Customer", opening_balance=Decimal("0"))
        self.warehouse = Warehouse.objects.create(name="Head Office")

    # ------------------------------------------------------------------- CRUD

    def post_rows(self, slug, rows):
        return self.client.post("/%s/add/" % slug, {"rows_json": json.dumps(rows)})

    def test_debit_note_saves_with_an_auto_number(self):
        response = self.post_rows("customer-debit-note", [{
            "date": "2026-05-01", "customer": self.customer.id,
            "against_bill": "INV-9", "amount": "2000",
            "sector": self.warehouse.id, "remarks": "",
        }])
        self.assertEqual(response.status_code, 302)
        note = CustomerDebitNote.objects.get()
        self.assertTrue(note.note_no.startswith("CDN-2627-"))
        self.assertEqual(note.amount, Decimal("2000"))
        self.assertEqual(note.sector_id, self.warehouse.id)

    def test_one_screen_saves_several_notes(self):
        self.post_rows("customer-debit-note", [
            {"date": "2026-05-01", "customer": self.customer.id, "amount": "100"},
            {"date": "2026-05-02", "customer": self.customer.id, "amount": "250"},
            {"date": "2026-05-03", "customer": self.customer.id, "amount": "400"},
        ])
        notes = CustomerDebitNote.objects.order_by("date")
        self.assertEqual([str(n.amount) for n in notes],
                         ["100.00", "250.00", "400.00"])
        # each row gets its own number in sequence
        self.assertEqual([n.note_no for n in notes],
                         ["CDN-2627-0001", "CDN-2627-0002", "CDN-2627-0003"])

    def test_one_bad_row_saves_nothing(self):
        self.post_rows("customer-debit-note", [
            {"date": "2026-05-01", "customer": self.customer.id, "amount": "100"},
            {"date": "2026-05-02", "customer": self.customer.id, "amount": "0"},
        ])
        self.assertFalse(CustomerDebitNote.objects.exists())

    def test_credit_note_saves_with_its_own_series(self):
        self.post_rows("customer-credit-note", [{
            "date": "2026-05-01", "customer": self.customer.id, "amount": "500",
        }])
        self.assertTrue(CustomerCreditNote.objects.get().note_no.startswith("CCN-2627-"))

    def test_a_note_without_a_customer_or_amount_is_rejected(self):
        self.post_rows("customer-debit-note", [{"date": "2026-05-01", "amount": "100"}])
        self.post_rows("customer-debit-note", [
            {"date": "2026-05-01", "customer": self.customer.id, "amount": "0"}])
        self.post_rows("customer-debit-note", [])
        self.assertFalse(CustomerDebitNote.objects.exists())

    def test_edit_and_delete_round_trip(self):
        note = CustomerDebitNote.objects.create(
            date=date(2026, 5, 1), customer=self.customer, amount=Decimal("100"))
        self.client.post("/customer-debit-note/%d/edit/" % note.id, {
            "rows_json": json.dumps([{"id": note.id, "date": "2026-05-02",
                                      "customer": self.customer.id, "amount": "150"}])})
        note.refresh_from_db()
        self.assertEqual(note.amount, Decimal("150"))

        self.client.post("/customer-debit-note/%d/delete/" % note.id)
        self.assertFalse(CustomerDebitNote.objects.exists())

    def test_register_and_api_list(self):
        CustomerDebitNote.objects.create(
            date=date(2026, 5, 1), customer=self.customer, amount=Decimal("100"),
            sector=self.warehouse)
        page = self.client.get("/customer-debit-note/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Customer Debit Note Register", page.content.decode())

        rows = self.client.get("/customer_debit_note_api/").json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["customer_name"], "Test Customer")
        self.assertEqual(rows[0]["amount"], "100.00")
        self.assertEqual(rows[0]["sector_name"], "Head Office")

    # -------------------------------------------------------------- narration

    def test_remarks_are_auto_described(self):
        note = CustomerCreditNote.objects.create(
            date=date(2026, 5, 1), customer=self.customer, amount=Decimal("2500"))
        # Generated here, then Title-Cased by the global text_format rule.
        self.assertEqual(note.remarks, "Customer Credit Note Test Customer 2,500")

    def test_typed_remarks_are_kept(self):
        note = CustomerDebitNote.objects.create(
            date=date(2026, 5, 1), customer=self.customer, amount=Decimal("100"),
            remarks="agreed with buyer")
        self.assertEqual(note.remarks, "Agreed With Buyer")

    # ----------------------------------------------------------------- ledger

    def test_notes_move_the_customer_balance_in_opposite_directions(self):
        def owed():
            # "debit" is the closing balance when the customer owes us.
            return _customer_balance_row(
                self.customer, None, None, date(2026, 12, 31))["debit"]

        self.assertEqual(owed(), Decimal("0.00"))

        CustomerDebitNote.objects.create(
            date=date(2026, 5, 1), customer=self.customer, amount=Decimal("2000"))
        self.assertEqual(owed(), Decimal("2000.00"))

        CustomerCreditNote.objects.create(
            date=date(2026, 5, 2), customer=self.customer, amount=Decimal("500"))
        self.assertEqual(owed(), Decimal("1500.00"))

    def test_notes_appear_on_the_customer_ledger(self):
        CustomerDebitNote.objects.create(
            date=date(2026, 5, 1), customer=self.customer, amount=Decimal("2000"),
            against_bill="INV-9", sector=self.warehouse)
        CustomerCreditNote.objects.create(
            date=date(2026, 5, 2), customer=self.customer, amount=Decimal("500"))

        html = self.client.get(
            "/customer-ledger/?customer=%d" % self.customer.id).content.decode()
        for token in ("Debit Note", "Credit Note", "CDN-2627-0001", "CCN-2627-0001",
                      "Head Office"):   # Sector shows the office/branch
            self.assertIn(token, html)

    def test_a_note_outside_the_window_only_moves_the_opening(self):
        CustomerDebitNote.objects.create(
            date=date(2026, 4, 1), customer=self.customer, amount=Decimal("700"))
        row = _customer_balance_row(
            self.customer, date(2026, 5, 1), date(2026, 5, 31), date(2026, 5, 31))
        self.assertEqual(row["opening"], Decimal("700.00"))
        self.assertEqual(row["debit"], Decimal("700.00"))
        # it fell before the window, so the period columns stay empty
        self.assertEqual(row["amount"], Decimal("0.00"))
