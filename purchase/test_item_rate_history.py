"""The last rates an item was bought at, beside the row being typed.

Entering a purchase means judging whether the rate on the invoice is
reasonable, and the only way to check used to be leaving the half-filled form
and opening the register. The Items header now carries the recent history,
split by who sold it: what the supplier on this bill charged last time, and
what anyone else charged.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from inventory.models import Item, ItemCategory, Warehouse
from purchase.models import (ChicksPurchase, ChicksPurchaseItem, GeneralPurchase,
                             GeneralPurchaseItem, Supplier)


class ItemRateHistoryTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="buyer", password="x", email="buyer@example.com")
        self.client.force_login(self.user)
        self.url = reverse("general_purchase_item_rates")

        self.warehouse = Warehouse.objects.create(name="Akbarpur Store")
        cat = ItemCategory.objects.create(name="Broiler Feed")
        self.item = Item.objects.create(item_code="ITM-1", description="Pre-Starter",
                                        category=cat, standard_cost_per_unit=0)
        self.other_item = Item.objects.create(item_code="ITM-2", description="Finisher",
                                              category=cat, standard_cost_per_unit=0)
        self.usual = Supplier.objects.create(name="Balaji Feeds")
        self.rival = Supplier.objects.create(name="Verma Traders")

    def bought(self, supplier, on, rate, item=None):
        p = GeneralPurchase.objects.create(supplier=supplier, date=on)
        GeneralPurchaseItem.objects.create(
            purchase=p, item=item or self.item, farm_warehouse=self.warehouse,
            unit="Bag", sent_qty=Decimal("10"), rcv_qty=Decimal("10"),
            rate=Decimal(rate))
        return p

    def bought_as_chicks(self, supplier, on, rate, item=None):
        """The chicks register keeps the item on the header and the rate on the
        line beneath it."""
        p = ChicksPurchase.objects.create(supplier=supplier, date=on, item=item or self.item)
        ChicksPurchaseItem.objects.create(
            purchase=p, farm_warehouse=self.warehouse,
            sent_qty=Decimal("5000"), rate=Decimal(rate))
        return p

    def ask(self, supplier=None):
        params = {"item": self.item.id}
        if supplier:
            params["supplier"] = supplier.id
        return self.client.get(self.url, params).json()

    def test_the_three_most_recent_come_back_newest_first(self):
        for day, rate in ((1, "40"), (2, "41"), (3, "42"), (4, "43"), (5, "44")):
            self.bought(self.usual, date(2026, 5, day), rate)
        rates = [r["rate"] for r in self.ask()["others"]]
        self.assertEqual(rates, ["44.00", "43.00", "42.00"])

    def test_what_this_supplier_charged_is_kept_apart_from_what_others_did(self):
        """The two answer different questions: one settles an argument with the
        supplier, the other says whether to be having it."""
        self.bought(self.usual, date(2026, 5, 1), "40")
        self.bought(self.rival, date(2026, 5, 2), "38")
        d = self.ask(self.usual)
        self.assertEqual([r["rate"] for r in d["same"]], ["40.00"])
        self.assertEqual([r["rate"] for r in d["others"]], ["38.00"])
        self.assertEqual(d["supplier"], "Balaji Feeds")

    def test_a_busy_supplier_cannot_crowd_the_others_out(self):
        """Five purchases from the usual supplier and one from a rival: the
        rival's price still shows. Merged into a single 'last three' it would
        have fallen off the end, which is the comparison worth having."""
        for day in range(1, 6):
            self.bought(self.usual, date(2026, 5, day), "40")
        self.bought(self.rival, date(2026, 4, 1), "31")
        d = self.ask(self.usual)
        self.assertEqual(len(d["same"]), 3)
        self.assertEqual([r["rate"] for r in d["others"]], ["31.00"])

    def test_with_no_supplier_chosen_the_whole_history_is_the_other_list(self):
        """Nothing has been picked to compare against yet, so there is no
        'them' — the history is simply everyone's."""
        self.bought(self.usual, date(2026, 5, 1), "40")
        d = self.ask()
        self.assertEqual(d["same"], [])
        self.assertEqual([r["rate"] for r in d["others"]], ["40.00"])
        self.assertEqual(d["supplier"], "")

    def test_another_items_purchases_are_not_this_items_history(self):
        self.bought(self.usual, date(2026, 5, 1), "99", item=self.other_item)
        self.assertEqual(self.ask()["others"], [])

    def test_free_quantity_is_not_netted_off_the_rate(self):
        """A discount in kind belongs to the deal, not to the price on the
        line. Reporting a rate other than the one recorded would be worse than
        showing nothing."""
        p = self.bought(self.usual, date(2026, 5, 1), "40")
        line = p.items.get()
        line.free_qty = Decimal("5")
        line.save()
        self.assertEqual(self.ask()["others"][0]["rate"], "40.00")

    def test_a_missing_or_junk_item_is_answered_not_raised(self):
        for bad in ("", "abc", "0x1"):
            d = self.client.get(self.url, {"item": bad}).json()
            self.assertEqual((d["same"], d["others"]), ([], []), bad)

    def test_chicks_bought_on_their_own_form_are_part_of_the_history(self):
        """Day-old chicks are bought on the Chicks Purchase page, where the item
        sits on the header. Reading only the general register left a chick row
        on this page showing nothing while its whole buying history sat in the
        other table."""
        self.bought_as_chicks(self.usual, date(2026, 7, 18), "42")
        self.assertEqual([r["rate"] for r in self.ask()["others"]], ["42.00"])

    def test_the_two_registers_are_one_history_in_date_order(self):
        """What an item cost is a question about the item, not about which
        screen recorded it."""
        self.bought(self.usual, date(2026, 5, 1), "40")
        self.bought_as_chicks(self.usual, date(2026, 7, 18), "42")
        self.bought(self.usual, date(2026, 6, 1), "41")
        self.assertEqual([r["rate"] for r in self.ask()["others"]],
                         ["42.00", "41.00", "40.00"])

    def test_a_chicks_purchase_splits_by_supplier_like_any_other(self):
        self.bought_as_chicks(self.usual, date(2026, 7, 18), "42")
        self.bought_as_chicks(self.rival, date(2026, 7, 19), "39")
        d = self.ask(self.usual)
        self.assertEqual([r["rate"] for r in d["same"]], ["42.00"])
        self.assertEqual([r["rate"] for r in d["others"]], ["39.00"])
