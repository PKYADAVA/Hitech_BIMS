"""Freight: three types, and only one of them touches the bill.

  No Freight        nothing was charged. The amount is cleared and the account
                    released, so nothing downstream can pick either up.
  Freight Included  the carriage is already inside the supplier's price. The
                    amount is still captured — landed cost needs to know how
                    much of that price was carriage — but adding it to the
                    invoice would charge it twice.
  Freight Extra     billed on top, and added.

The arithmetic used to run the other way: freight was added when the type read
"Included in Bill" and left out when it read "Extra", the opposite of what
those words say.
"""
from decimal import Decimal

from django.test import TestCase

from account.models import ChartOfAccount
from inventory.models import Item, ItemCategory, Warehouse
from purchase.models import (ChicksPurchase, GeneralPurchase, GeneralPurchaseItem,
                             Supplier)


class FreightOnTheBillTests(TestCase):
    def setUp(self):
        self.supplier = Supplier.objects.create(name="Verma Feeds")
        self.warehouse = Warehouse.objects.create(name="Akbarpur Store")
        cat = ItemCategory.objects.create(name="Broiler Feed")
        self.item = Item.objects.create(item_code="ITM-1", description="Pre-Starter",
                                        category=cat, standard_cost_per_unit=0)
        self.account = ChartOfAccount.objects.create(
            code="5001", description="Transport / Freight", type="Expense",
            status="Active")

    def purchase(self, freight_type, freight=Decimal("8000"), **over):
        p = GeneralPurchase.objects.create(
            supplier=self.supplier, freight_type=freight_type,
            freight_amount=freight, freight_account=self.account, **over)
        GeneralPurchaseItem.objects.create(
            purchase=p, item=self.item, farm_warehouse=self.warehouse,
            sent_qty=Decimal("8000"), rcv_qty=Decimal("8000"),
            rate=Decimal("40"))
        p.refresh_from_db()
        return p

    def test_freight_extra_is_added_to_the_bill(self):
        """Goods 3,20,000 plus carriage 8,000 is an invoice of 3,28,000."""
        p = self.purchase("Freight Extra")
        self.assertEqual(p.gross_amount(), Decimal("320000.00"))
        self.assertEqual(p.freight_included_amount(), Decimal("328000.00"))

    def test_freight_included_is_not_added_again(self):
        """The 8,000 is already inside the supplier's price. Adding it would
        bill the carriage twice."""
        p = self.purchase("Freight Included")
        self.assertEqual(p.gross_amount(), Decimal("320000.00"))
        self.assertEqual(p.freight_included_amount(), Decimal("320000.00"))

    def test_freight_included_still_keeps_the_amount(self):
        """Landed cost needs to know how much of the price was carriage."""
        p = self.purchase("Freight Included")
        self.assertEqual(p.freight_amount, Decimal("8000"))
        self.assertEqual(p.freight_account, self.account)

    def test_no_freight_clears_the_amount_and_the_account(self):
        """A disabled input is a courtesy to the person typing, not a rule —
        the save path takes whatever is posted to it."""
        p = self.purchase("No Freight")
        self.assertEqual(p.freight_amount, Decimal("0"))
        self.assertIsNone(p.freight_account)
        self.assertEqual(p.freight_included_amount(), Decimal("320000.00"))

    def test_the_three_types_are_what_the_form_offers(self):
        for model in (GeneralPurchase, ChicksPurchase):
            self.assertEqual([v for v, _ in model.FREIGHT_TYPE_CHOICES],
                             ["No Freight", "Freight Included", "Freight Extra"])

    def test_chicks_purchase_follows_the_same_rule(self):
        p = ChicksPurchase.objects.create(
            supplier=self.supplier, item=self.item,
            freight_type="No Freight", freight_amount=Decimal("5000"),
            freight_account=self.account)
        p.refresh_from_db()
        self.assertEqual(p.freight_amount, Decimal("0"))
        self.assertIsNone(p.freight_account)

    def test_the_net_amount_carries_the_difference_through(self):
        """Round-off and net amount are computed from the same total, so the
        rule has to hold all the way to what the supplier is paid."""
        extra = self.purchase("Freight Extra")
        included = self.purchase("Freight Included")
        self.assertEqual(extra.compute_net_amount() - included.compute_net_amount(),
                         Decimal("8000"))


class FreightSettlementTests(FreightOnTheBillTests):
    """Which bill the carriage lands on — a different question from how it is
    priced. The transporter is often not the supplier of the goods, and then
    the freight is a liability to somebody else entirely.
    """

    TRANSPORTER = "Yadav Transport"

    def test_freight_on_the_supplier_s_own_bill_is_added(self):
        """Material 1,00,000 plus 5,000 carriage is a bill of 1,05,000, and
        the whole of it is owed to the one supplier."""
        p = self.purchase("Freight Extra", Decimal("5000"),
                          freight_settlement="In Purchase Bill")
        self.assertTrue(p.freight_on_this_bill())
        self.assertEqual(p.transporter_payable(), 0)
        self.assertEqual(p.freight_included_amount() - p.gross_amount(),
                         Decimal("5000"))

    def test_a_separate_freight_bill_leaves_the_purchase_alone(self):
        """Two liabilities: the supplier is owed the goods, the transporter
        the carriage. Adding the carriage here would bill the supplier for
        somebody else's invoice."""
        p = self.purchase("Freight Extra", Decimal("5000"),
                          freight_settlement="Separate Bill",
                          freight_transporter=self.TRANSPORTER)
        self.assertFalse(p.freight_on_this_bill())
        self.assertEqual(p.freight_included_amount(), p.gross_amount())
        self.assertEqual(p.transporter_payable(), Decimal("5000"))
        self.assertEqual(p.freight_transporter, self.TRANSPORTER)

    def test_settlement_is_only_a_question_for_freight_charged_on_top(self):
        """Carriage already inside the quoted price arrives on the supplier's
        own invoice by definition; there is no bill at all without freight."""
        for freight_type in ("No Freight", "Freight Included"):
            p = self.purchase(freight_type, Decimal("5000"),
                              freight_settlement="Separate Bill",
                              freight_transporter=self.TRANSPORTER)
            self.assertEqual(p.freight_settlement, "In Purchase Bill", freight_type)
            self.assertEqual(p.freight_transporter, "", freight_type)
            self.assertEqual(p.transporter_payable(), 0, freight_type)

    def test_a_transporter_is_only_kept_where_one_can_be_owed(self):
        p = self.purchase("Freight Extra", Decimal("5000"),
                          freight_settlement="In Purchase Bill",
                          freight_transporter=self.TRANSPORTER)
        self.assertEqual(p.freight_transporter, "")

    def test_the_transporter_is_a_name_not_a_party(self):
        """Whoever the supplier put on the lorry that day — rarely the same
        firm twice, and almost never one worth a master record."""
        p = self.purchase("Freight Extra", Decimal("5000"),
                          freight_settlement="Separate Bill",
                          freight_transporter="Ram Singh, UP-53-AT-1123")
        self.assertEqual(p.freight_transporter, "Ram Singh, UP-53-AT-1123")

    def test_payment_status_says_whether_not_when(self):
        """"Pay In Bill" read as an instruction about timing. The stored
        values are unchanged; only the question changed."""
        labels = dict(GeneralPurchase.PAYMENT_MODE_CHOICES)
        self.assertEqual(labels["pay_in_bill"], "Paid")
        self.assertEqual(labels["pay_later"], "Credit / Pay Later")
