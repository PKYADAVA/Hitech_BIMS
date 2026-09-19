"""General Purchase register: the Item column reads item names, not codes.

The list sent one comma-joined string of item codes; it now also sends each
line's item — name, code, the quantity the bill is calculated on, and unit —
so the register can show names and fold a long purchase behind "+N more".
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from inventory.models import Item, ItemCategory, Warehouse
from purchase.models import GeneralPurchase, GeneralPurchaseItem, Supplier


class GeneralPurchaseListItemTests(TestCase):

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser(
            "gpadmin", "g@x.com", "Str0ngPass!"))
        store = Warehouse.objects.create(name="Akbarpur Warehouse")
        meds = ItemCategory.objects.create(name="Medicine")
        self.day = date(2026, 8, 22)
        purchase = GeneralPurchase.objects.create(date=self.day, bill_no="GST-009102",
                                                  supplier=Supplier.objects.create(name="Lal Medico"))
        for code, name, sent, rcv in (("ITM-0006", "Liver Tonic", "300", "290"),
                                      ("ITM-0012", "Toxin Binder", "500", "490")):
            item = Item.objects.create(item_code=code, description=name, category=meds,
                                       standard_cost_per_unit=0)
            GeneralPurchaseItem.objects.create(
                purchase=purchase, item=item, farm_warehouse=store, unit="Ltr",
                sent_qty=Decimal(sent), rcv_qty=Decimal(rcv), rate=Decimal("20"),
                discount_percent=Decimal("0"), discount_amount=Decimal("0"))
        self.purchase = purchase

    def row(self):
        rows = self.client.get("/general_purchase_api/", {
            "from_date": self.day.isoformat(), "to_date": self.day.isoformat()}).json()
        self.assertEqual(len(rows), 1)
        return rows[0]

    def test_each_line_comes_with_its_item_name(self):
        self.assertEqual([(i["name"], i["code"], i["unit"]) for i in self.row()["items"]],
                         [("Liver Tonic", "ITM-0006", "Ltr"), ("Toxin Binder", "ITM-0012", "Ltr")])

    def test_quantity_follows_what_the_bill_is_calculated_on(self):
        self.purchase.calculation_based_on = "Received Quantity"
        self.purchase.save()
        self.assertEqual([i["qty"] for i in self.row()["items"]], ["290.00", "490.00"])
        self.purchase.calculation_based_on = "Sent Quantity"
        self.purchase.save()
        self.assertEqual([i["qty"] for i in self.row()["items"]], ["300.00", "500.00"])

    def test_the_page_renders_names_and_exports_the_full_list(self):
        html = self.client.get("/general-purchase/").content.decode()
        self.assertIn("function itemCell(row)", html)
        self.assertIn("data-export", html)
        self.assertIn("Farm/<wbr>Warehouse", html)


class ChicksPurchaseListItemTests(TestCase):
    """Chicks Purchase carries one item per bill; its register reads it by name too."""

    def test_the_list_sends_the_item_name(self):
        from purchase.models import ChicksPurchase

        self.client.force_login(get_user_model().objects.create_superuser(
            "cpadmin", "c@x.com", "Str0ngPass!"))
        item = Item.objects.create(item_code="DOC-0001", description="Day Old Chicks",
                                   category=ItemCategory.objects.create(name="Chicks"),
                                   standard_cost_per_unit=0)
        day = date(2026, 7, 18)
        ChicksPurchase.objects.create(date=day, supplier=Supplier.objects.create(name="Hatch Co"),
                                      item=item)
        rows = self.client.get("/chicks_purchase_api/", {"from_date": day.isoformat(),
                                                         "to_date": day.isoformat()}).json()
        self.assertEqual((rows[0]["item_name"], rows[0]["item_code"]), ("Day Old Chicks", "DOC-0001"))
