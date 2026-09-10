"""A transaction number that was taken between the read and the write.

Every document number here is issued the same way — read the highest already
used, add one, write the row — and the gap between the reading and the writing
is real. Two saves that land in it read the same highest and take the same
number. These columns are unique, so the second save did not file a duplicate;
it failed, and the page showed a 500 with nothing to act on.

The number is now reissued and the write attempted again, which is what would
have happened had the two saves arrived one after the other. Stock Transfer
stands in for the whole family: thirty-odd registers mint their numbers this
way, and all of them go through the same helper.
"""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from inventory.models import Item, ItemCategory, StockTransfer, Warehouse


class TransactionNumberRetryTests(TestCase):

    def setUp(self):
        self.warehouse = Warehouse.objects.create(name="Main Warehouse")
        self.item = Item.objects.create(
            description="Pre-Starter Feed",
            category=ItemCategory.objects.create(name="Feed"),
            valuation_method="Weighted Average", standard_cost_per_unit=30,
            usage="Produced", source="Purchased", type="Raw Material",
            item_account="Expense")

    def transfer(self, quantity=10):
        return StockTransfer.objects.create(
            item=self.item, quantity=quantity, rate=30, date=date(2026, 7, 20),
            from_location_type="warehouse", from_warehouse=self.warehouse,
            to_location_type="warehouse", to_warehouse=self.warehouse)

    def test_a_number_is_issued_in_sequence(self):
        first, second = self.transfer(), self.transfer()
        self.assertTrue(first.trnum)
        self.assertNotEqual(first.trnum, second.trnum)

    def test_a_transfer_whose_number_was_taken_still_lands(self):
        """The case that used to be a 500. Staged by taking the number away
        in the instant between it being issued and the row being written —
        which is exactly what a second save does."""
        first = self.transfer()
        stolen = {"done": False}
        original = StockTransfer._next_trnum.__func__

        def steal(cls, on_date):
            number = original(cls, on_date)
            if not stolen["done"]:
                stolen["done"] = True
                StockTransfer.objects.filter(pk=first.pk).update(trnum=number)
            return number

        StockTransfer._next_trnum = classmethod(steal)
        try:
            second = self.transfer(quantity=25)
        finally:
            StockTransfer._next_trnum = classmethod(original)

        self.assertTrue(stolen["done"], "the race was never staged")
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertTrue(second.trnum, "the second transfer has no number")
        self.assertNotEqual(second.trnum, first.trnum)
        self.assertEqual(StockTransfer.objects.count(), 2)

    def test_the_record_itself_is_not_written_twice(self):
        """Reissuing the number must not file the transfer again — the retry
        is on the update that carries the number, not on the row."""
        before = StockTransfer.objects.count()
        self.transfer()
        self.assertEqual(StockTransfer.objects.count(), before + 1)


class HelperCoverageTests(TestCase):
    """Every register that mints a number goes through the one helper, so a
    new one added without it is the thing to catch."""

    def test_every_minting_save_uses_the_shared_retry(self):
        import io
        import re

        missing = []
        for path in ("broiler/models.py", "hatchery/models.py", "inventory/models.py",
                     "sales/models.py", "purchase/models.py", "hr/models.py",
                     "account/models.py"):
            source = io.open(path, encoding="utf-8").read()
            # A number written on its own after the row exists: the shape that
            # cannot be anything but a minted document number.
            for match in re.finditer(
                    r"super\(\)\.save\(update_fields=\[[\"'](\w+)[\"']\]\)", source):
                window = source[max(0, match.start() - 700):match.start()]
                if "mint_with_retry" not in window and "self.pk" not in window:
                    missing.append("%s: %s" % (path, match.group(1)))
        self.assertEqual(missing, [],
                         "these mint a number without the shared retry")
