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
