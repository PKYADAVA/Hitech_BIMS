from decimal import Decimal

from django.test import TestCase

from purchase.models import GeneralPurchase, Supplier


class AutoRemarksTests(TestCase):
    """The generated `remarks` description must reflect the final total.

    A purchase header is saved before its line items exist, so `net_amount` is
    still zero when the description is first built. The description has to be
    refreshed on the second save (the one that stores the computed total),
    without ever disturbing wording the user typed.
    """

    def setUp(self):
        self.supplier = Supplier.objects.create(name="Ganga Breeding Farm")

    def _two_phase_save(self, **kwargs):
        """Save a header, then store a total the way the views do."""
        purchase = GeneralPurchase(supplier=self.supplier, **kwargs)
        purchase.save()
        first = purchase.remarks
        purchase.net_amount = Decimal("125000.00")
        purchase.save(update_fields=[
            "net_amount", "round_off", "round_off_type", "remarks"])
        purchase.refresh_from_db()
        return first, purchase.remarks

    def test_description_picks_up_the_total(self):
        first, final = self._two_phase_save()
        self.assertEqual(first, "Purchase From Ganga Breeding Farm 0")
        self.assertEqual(final, "Purchase From Ganga Breeding Farm 1,25,000")

    def test_typed_remarks_are_never_replaced(self):
        # The Title-Casing is the global text_format rule, not this receiver —
        # what matters is that the typed wording survives.
        _, final = self._two_phase_save(remarks="Urgent - check GST")
        self.assertEqual(final, "Urgent - Check GST")
        self.assertNotIn("Ganga", final)

    def test_stored_description_is_not_rewritten_on_a_later_edit(self):
        purchase = GeneralPurchase(supplier=self.supplier)
        purchase.save()
        purchase.net_amount = Decimal("500.00")
        purchase.save(update_fields=[
            "net_amount", "round_off", "round_off_type", "remarks"])

        # A fresh instance carries no auto-fill marker, so its stored text
        # stands even though another field changed.
        reloaded = GeneralPurchase.objects.get(pk=purchase.pk)
        reloaded.net_amount = Decimal("999.00")
        reloaded.save()
        reloaded.refresh_from_db()
        self.assertEqual(reloaded.remarks, "Purchase From Ganga Breeding Farm 500")


class SupplierNoteGridTests(TestCase):
    """Supplier Debit / Credit Notes on the row-entry grid.

    Kept in step with sales.CustomerNoteTests — the two sides of the same idea
    should behave identically.
    """

    def setUp(self):
        from django.contrib.auth import get_user_model
        from inventory.models import Warehouse
        user = get_user_model().objects.create_superuser(
            "purchase-tester", "p@example.com", "Str0ngPass!")
        self.client.force_login(user)
        self.supplier = Supplier.objects.create(name="Test Supplier")
        self.warehouse = Warehouse.objects.create(name="Head Office")

    def post_rows(self, slug, rows):
        import json
        return self.client.post("/%s/add/" % slug, {"rows_json": json.dumps(rows)})

    def test_one_screen_saves_several_notes(self):
        from purchase.models import DebitNote
        self.post_rows("debit-note", [
            {"date": "2026-05-01", "supplier": self.supplier.id, "amount": "100",
             "sector": self.warehouse.id},
            {"date": "2026-05-02", "supplier": self.supplier.id, "amount": "250"},
        ])
        notes = DebitNote.objects.order_by("date")
        self.assertEqual([n.note_no for n in notes], ["DN-2627-0001", "DN-2627-0002"])
        self.assertEqual(notes[0].sector_id, self.warehouse.id)

    def test_one_bad_row_saves_nothing(self):
        from purchase.models import DebitNote
        self.post_rows("debit-note", [
            {"date": "2026-05-01", "supplier": self.supplier.id, "amount": "100"},
            {"date": "2026-05-02", "supplier": self.supplier.id, "amount": "0"},
        ])
        self.assertFalse(DebitNote.objects.exists())

    def test_credit_note_uses_its_own_series(self):
        from purchase.models import CreditNote
        self.post_rows("credit-note", [
            {"date": "2026-05-01", "supplier": self.supplier.id, "amount": "500"}])
        self.assertEqual(CreditNote.objects.get().note_no, "CN-2627-0001")

    def test_grid_column_order_and_alignment(self):
        import re
        html = self.client.get("/debit-note/add/").content.decode()
        head = re.search(r"<thead.*?</thead>", html, re.S).group(0)
        labels = [re.sub(r"<[^>]+>", "", h).strip()
                  for h in re.findall(r"<th[^>]*>(.*?)</th>", head, re.S)]
        self.assertEqual(labels[:3], ["Transaction No.", "Date *", "Supplier *"])
        rowjs = re.search(r"tr\.innerHTML = `(.*?)`;", html, re.S).group(1)
        self.assertEqual(len(re.findall(r"<td(?:\s[^>]*)?>", rowjs)), len(labels))

    def test_edit_reopens_the_saved_row(self):
        import json, re
        from datetime import date
        from purchase.models import DebitNote
        note = DebitNote.objects.create(
            date=date(2026, 5, 1), supplier=self.supplier, amount=Decimal("10"),
            against_bill="BILL-9", sector=self.warehouse)
        html = self.client.get("/debit-note/%d/edit/" % note.id).content.decode()
        row = json.loads(re.search(r"const EXISTING = (\[.*?\]);", html, re.S).group(1))[0]
        self.assertEqual(row["note_no"], note.note_no)
        self.assertEqual(row["supplier"], self.supplier.id)
        self.assertEqual(row["against_bill"], "BILL-9")
        self.assertEqual(row["sector"], self.warehouse.id)
        self.assertNotIn('id="add-row"', html)

    def test_notes_show_on_the_supplier_ledger_with_the_office(self):
        from datetime import date
        from purchase.models import CreditNote, DebitNote
        DebitNote.objects.create(
            date=date(2026, 5, 1), supplier=self.supplier, amount=Decimal("2000"),
            sector=self.warehouse)
        CreditNote.objects.create(
            date=date(2026, 5, 2), supplier=self.supplier, amount=Decimal("500"))
        html = self.client.get(
            "/supplier-ledger/?supplier=%d" % self.supplier.id).content.decode()
        for token in ("Debit Note", "Credit Note", "DN-2627-0001", "CN-2627-0001",
                      "Head Office"):
            self.assertIn(token, html)
