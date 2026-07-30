import re
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from account.models import AccountType, ChartOfAccount, CompanyProfile
from hatchery.models import ChickSale, ChickSaleItem, EggPurchase, EggPurchaseItem
from purchase.models import (ChicksPurchase, ChicksPurchaseItem, GeneralPurchase,
                             GeneralPurchaseItem, Supplier)
from sales.models import Customer
from inventory.services.item_summary import location_item_stock
from inventory.services.valuation import item_ledger
from inventory.models import (
    InventoryAdjustment,
    InventoryAdjustmentItem,
    Item,
    ItemCategory,
    StockIssue,
    StockIssueItem,
    StockReceive,
    StockReceiveItem,
    Warehouse,
    warehouse_item_stock,
)


class InventoryLineReportTests(TestCase):
    """The three Inventory line reports: Adjustment, Received and Issued.

    They share one view engine and one template, so these cover what differs:
    Adjustment's extra Type column, where the location is read from (its header
    vs the line), the weighted-average Price total, and the filters.
    """

    def setUp(self):
        user = get_user_model().objects.create_superuser(
            "reporter", "reporter@example.com", "Str0ngPass!")
        self.client.force_login(user)
        account_type = AccountType.objects.create(
            name="Stock Adjustment Expense", code_range_start=500000,
            code_range_end=599999, report="PL")
        self.coa = ChartOfAccount.objects.create(
            company=CompanyProfile.get_solo(), code="500001",
            description="Stock Adjustment", account_type=account_type)
        self.warehouse = Warehouse.objects.create(name="Akbarpur Warehouse")
        self.item = Item.objects.create(
            description="Pre Starter Feed",
            category=ItemCategory.objects.create(name="Feed"),
            valuation_method="Weighted Average",
            standard_cost_per_unit=Decimal("50"), usage="Produced",
            source="Purchased", type="Raw Material", item_account="Expense")

    # -------------------------------------------------------------- adjustment

    def test_adjustment_report_shows_type_and_weighted_average_price(self):
        header = InventoryAdjustment.objects.create(
            date=date(2026, 2, 1), location_type="warehouse",
            warehouse=self.warehouse, chart_of_account=self.coa)
        InventoryAdjustmentItem.objects.create(
            adjustment=header, item=self.item, adjustment_type="Add",
            quantity=Decimal("100"), rate=Decimal("50"), remarks="opening fix")
        InventoryAdjustmentItem.objects.create(
            adjustment=header, item=self.item, adjustment_type="Deduct",
            quantity=Decimal("300"), rate=Decimal("30"))

        html = self.client.get("/inventory-adjustment-report/").content.decode()
        for token in ("Inventory Adjustment Report", "Type", "Add", "Deduct",
                      "Pre Starter Feed",
                      # location comes off the header for this report
                      "Akbarpur Warehouse",
                      # remarks are Title-Cased by the global text_format rule
                      "Opening Fix"):
            self.assertIn(token, html)
        # 100x50 + 300x30 = 14,000 over 400 units, so Price totals the weighted
        # average 35.00 - summing the two rates (80) would be meaningless.
        self.assertIn("400.00", html)
        self.assertIn("14,000.00", html)
        self.assertIn("35.00", html)
        self.assertColumnsAligned(html, expected=9)

    # ----------------------------------------------------------------- receive

    def test_received_report_has_no_type_column(self):
        header = StockReceive.objects.create(
            date=date(2026, 2, 1), chart_of_account=self.coa)
        StockReceiveItem.objects.create(
            receive=header, item=self.item, quantity=Decimal("54000"),
            rate=Decimal("54.24"), location_type="warehouse",
            warehouse=self.warehouse)

        html = self.client.get("/inventory-received-report/").content.decode()
        self.assertIn("Inventory Received Report", html)
        self.assertNotIn("<th>Type</th>", html)
        self.assertIn("54,000.00", html)
        # location comes off the line, not the header, for this report
        self.assertIn("Akbarpur Warehouse", html)
        self.assertColumnsAligned(html, expected=8)

    # ------------------------------------------------------------------- issue

    def test_issued_report_renders_and_filters(self):
        header = StockIssue.objects.create(
            date=date(2026, 2, 1), chart_of_account=self.coa)
        StockIssueItem.objects.create(
            issue=header, item=self.item, quantity=Decimal("20"),
            rate=Decimal("10"), location_type="warehouse",
            warehouse=self.warehouse)

        html = self.client.get("/inventory-issued-report/").content.decode()
        self.assertIn("Inventory Issued Report", html)
        self.assertColumnsAligned(html, expected=8)

        outside = self.client.get(
            "/inventory-issued-report/?from_date=2027-01-01&to_date=2027-12-31"
        ).content.decode()
        self.assertIn("No records match these filters.", outside)

        matched = self.client.get(
            "/inventory-issued-report/?item=%d" % self.item.id).content.decode()
        self.assertIn("Pre Starter Feed", matched)

    # ------------------------------------------------------------------ export

    def test_every_report_streams_an_excel_workbook(self):
        for slug in ("inventory-adjustment-report", "inventory-received-report",
                     "inventory-issued-report"):
            response = self.client.get("/%s/?export=excel" % slug)
            self.assertEqual(response.status_code, 200)
            self.assertIn("spreadsheetml", response["Content-Type"])

    # ------------------------------------------------------------------ helper

    def assertColumnsAligned(self, html, expected):
        """Header, data row and totals row must all span the same width."""
        thead = re.search(r"<thead>(.*?)</thead>", html, re.S).group(1)
        head = len(re.findall(r"<th(?:\s[^>]*)?>", thead))
        body = re.search(r"<tbody>(.*?)</tbody>", html, re.S).group(1)
        row = len(re.findall(
            r"<td(?:\s[^>]*)?>", re.search(r"<tr>(.*?)</tr>", body, re.S).group(1)))
        tfoot = re.search(r"<tfoot>(.*?)</tfoot>", html, re.S).group(1)
        span = 0
        for cell in re.findall(r"<td(?:\s[^>]*)?>", tfoot):
            found = re.search(r'colspan="(\d+)"', cell)
            span += int(found.group(1)) if found else 1
        self.assertEqual([head, row, span], [expected, expected, expected])


class HatcheryStockVisibilityTests(TestCase):
    """Hatchery movements must reach the inventory stock engines."""

    def setUp(self):
        get_user_model().objects.create_superuser("h", "h@x.com", "Str0ngPass!")
        at = AccountType.objects.create(name="T", code_range_start=500000,
                                        code_range_end=599999, report="PL")
        self.coa = ChartOfAccount.objects.create(
            company=CompanyProfile.get_solo(), code="500001", description="X",
            account_type=at)
        self.wh = Warehouse.objects.create(name="Hatchery Store")
        self.item = Item.objects.create(
            description="Hatching Eggs", category=ItemCategory.objects.create(name="Eggs"),
            valuation_method="Weighted Average", standard_cost_per_unit=Decimal("5"),
            usage="Produced", source="Purchased", type="Raw Material",
            item_account="Expense")
        self.supplier = Supplier.objects.create(name="Egg Supplier")
        self.customer = Customer.objects.create(name="Chick Buyer")

    def _egg_purchase(self, rcv, free=0, sent=0):
        ep = EggPurchase.objects.create(
            date=date(2026, 5, 1), supplier=self.supplier, warehouse=self.wh,
            pay_account=self.coa)
        EggPurchaseItem.objects.create(
            egg_purchase=ep, item=self.item, sent_qty=Decimal(str(sent)),
            rcv_qty=Decimal(str(rcv)), free_qty=Decimal(str(free)),
            rate=Decimal("5"))
        return ep

    def _chick_sale(self, total, mortality=0, culls=0):
        cs = ChickSale.objects.create(
            date=date(2026, 5, 10), customer=self.customer, warehouse=self.wh)
        ChickSaleItem.objects.create(
            sale=cs, item=self.item, total_qty=Decimal(str(total)),
            mortality=Decimal(str(mortality)), culls=Decimal(str(culls)),
            sale_rate=Decimal("9"))
        return cs

    def test_egg_purchase_is_an_inflow(self):
        self.assertEqual(warehouse_item_stock(self.item.id, self.wh.id), Decimal("0"))
        self._egg_purchase(rcv=1000, free=50)
        self.assertEqual(warehouse_item_stock(self.item.id, self.wh.id), Decimal("1050"))

    def test_received_falls_back_to_sent(self):
        self._egg_purchase(rcv=0, sent=800, free=0)
        self.assertEqual(warehouse_item_stock(self.item.id, self.wh.id), Decimal("800"))

    def test_chick_sale_is_an_outflow_including_losses(self):
        self._egg_purchase(rcv=1000)
        self._chick_sale(total=300, mortality=10, culls=5)
        # 1000 - 300 (not 1000 - 285): the dead and culled birds left too
        self.assertEqual(warehouse_item_stock(self.item.id, self.wh.id), Decimal("700"))

    def test_reports_agree_with_the_stock_function(self):
        self._egg_purchase(rcv=1000, free=50)
        self._chick_sale(total=300)
        expected = Decimal("750")
        self.assertEqual(warehouse_item_stock(self.item.id, self.wh.id), expected)
        loc = location_item_stock("warehouse", self.wh.id, self.item.id)
        self.assertEqual(Decimal(str(loc)), expected)

        led = item_ledger(self.item.id, self.wh.id)
        types = [r["type"] for r in led["rows"]]
        self.assertIn("Egg Purchase", types)
        self.assertIn("Chick Sale", types)
        self.assertEqual(led["closing"]["qty"], expected)

    def test_chicks_purchase_stocks_the_physical_count(self):
        cp = ChicksPurchase.objects.create(
            date=date(2026, 5, 2), supplier=self.supplier, item=self.item)
        line = ChicksPurchaseItem.objects.create(
            purchase=cp, farm_warehouse=self.wh, sent_qty=Decimal("1000"),
            free_percent=Decimal("10"), rate=Decimal("40"))
        stock = warehouse_item_stock(self.item.id, self.wh.id)
        # 1000 x 1.1 = 1100 gross, no losses, / 1.1 = 1000 chargeable,
        # + 10% free = 100, so 1100 birds physically arrive.
        self.assertEqual(line.received_qty, Decimal("1000"))
        self.assertEqual(line.free_qty, Decimal("100"))
        self.assertEqual(line.total_qty, Decimal("1100"))
        self.assertEqual(line.amount, Decimal("40000"))    # billed on 1000
        self.assertEqual(stock, Decimal("1100"))           # stocked on 1100
        self.assertEqual(Decimal(str(location_item_stock(
            "warehouse", self.wh.id, self.item.id))), Decimal("1100"))


class GeneralPurchaseBasisTests(TestCase):
    """A General Purchase is billed on Sent or Received quantity.

    calculation_based_on defaults to "Sent Quantity", and on that basis rcv_qty
    is legitimately left at zero. Reading rcv_qty alone made every such
    purchase invisible to stock and to the feed report.
    """

    def setUp(self):
        get_user_model().objects.create_superuser("gp", "g@x.com", "Str0ngPass!")
        self.warehouse = Warehouse.objects.create(name="Bahraich Warehouse")
        self.item = Item.objects.create(
            description="Pre Starter Feed",
            category=ItemCategory.objects.create(name="Feed"),
            valuation_method="Weighted Average", standard_cost_per_unit=Decimal("50"),
            usage="Produced", source="Purchased", type="Raw Material",
            item_account="Expense")
        self.supplier = Supplier.objects.create(name="Maharashtra Feeds Pvt Ltd")

    def buy(self, basis, sent="0", rcv="0", free="0"):
        purchase = GeneralPurchase.objects.create(
            date=date(2026, 7, 21), supplier=self.supplier, calculation_based_on=basis)
        GeneralPurchaseItem.objects.create(
            purchase=purchase, item=self.item, farm_warehouse=self.warehouse,
            sent_qty=Decimal(sent), rcv_qty=Decimal(rcv), free_qty=Decimal(free),
            rate=Decimal("50"),
            # The views always pass these as Decimals; the model's int defaults
            # would make save() do Decimal * float and blow up.
            discount_percent=Decimal("0"), discount_amount=Decimal("0"),
            gst_percent=Decimal("0"))
        return purchase

    def test_sent_basis_purchase_reaches_stock(self):
        # The reported case: sent 500, nothing booked as received.
        self.buy("Sent Quantity", sent="500")
        stock = warehouse_item_stock(self.item.id, self.warehouse.id)
        print("RESULT sent-basis stock     %s" % stock)
        self.assertEqual(stock, Decimal("500"))

    def test_received_basis_purchase_uses_received(self):
        self.buy("Received Quantity", sent="500", rcv="480")
        stock = warehouse_item_stock(self.item.id, self.warehouse.id)
        print("RESULT received-basis stock %s" % stock)
        self.assertEqual(stock, Decimal("480"))

    def test_free_quantity_is_added_on_either_basis(self):
        self.buy("Sent Quantity", sent="500", free="20")
        print("RESULT sent + free          %s" % warehouse_item_stock(self.item.id, self.warehouse.id))
        self.assertEqual(warehouse_item_stock(self.item.id, self.warehouse.id), Decimal("520"))

    def test_reports_agree_with_the_stock_function(self):
        self.buy("Sent Quantity", sent="500")
        expected = Decimal("500")
        self.assertEqual(warehouse_item_stock(self.item.id, self.warehouse.id), expected)
        loc = location_item_stock("warehouse", self.warehouse.id, self.item.id)
        led = item_ledger(self.item.id, self.warehouse.id)
        print("RESULT summary=%s ledger=%s" % (loc, led["closing"]["qty"]))
        self.assertEqual(Decimal(str(loc)), expected)
        self.assertEqual(led["closing"]["qty"], expected)

    def test_a_line_created_without_explicit_decimals_still_saves(self):
        """A DecimalField's default=0 is a plain int until the row is read back,
        so percent/100 produced a float and the next Decimal operation raised
        TypeError. The forms always post Decimals; a script or import does not.
        """
        purchase = GeneralPurchase.objects.create(
            date=date(2026, 7, 21), supplier=self.supplier,
            calculation_based_on="Sent Quantity")
        line = GeneralPurchaseItem.objects.create(      # no percents passed
            purchase=purchase, item=self.item, farm_warehouse=self.warehouse,
            sent_qty=Decimal("500"), rate=Decimal("50"))
        print("RESULT bare line amount     %s" % line.amount)
        self.assertEqual(line.amount, Decimal("25000"))
        self.assertEqual(
            warehouse_item_stock(self.item.id, self.warehouse.id), Decimal("500"))


class ChicksPurchaseFormulaTests(TestCase):
    """Received / Free / Total / Amount from a single Free %."""

    def setUp(self):
        self.warehouse = Warehouse.objects.create(name="Akbarpur Warehouse")
        self.item = Item.objects.create(
            description="Broiler Chicks",
            category=ItemCategory.objects.create(name="Chicks"),
            valuation_method="Weighted Average", standard_cost_per_unit=Decimal("40"),
            usage="Produced", source="Purchased", type="Raw Material",
            item_account="Expense")
        self.supplier = Supplier.objects.create(name="Ganga Breeding Farm")

    def line(self, **kw):
        purchase = ChicksPurchase.objects.create(
            date=date(2026, 7, 21), supplier=self.supplier, item=self.item)
        defaults = dict(sent_qty=Decimal("1000"), free_percent=Decimal("10"),
                        rate=Decimal("40"))
        defaults.update(kw)
        return ChicksPurchaseItem.objects.create(
            purchase=purchase, farm_warehouse=self.warehouse, **defaults)

    def test_clean_consignment(self):
        line = self.line()
        print("RESULT clean      recv=%s free=%s total=%s amt=%s"
              % (line.received_qty, line.free_qty, line.total_qty, line.amount))
        self.assertEqual(line.received_qty, Decimal("1000"))
        self.assertEqual(line.free_qty, Decimal("100"))
        self.assertEqual(line.total_qty, Decimal("1100"))
        self.assertEqual(line.amount, Decimal("40000"))

    def test_losses_reduce_the_received_count(self):
        # gross 1100 - 50 mortality - 20 shortage - 30 weaks + 10 excess = 1010
        # 1010 / 1.1 = 918 chargeable, 92 free, 1010 physical
        line = self.line(mortality=Decimal("50"), shortage=Decimal("20"),
                         weaks=Decimal("30"), excess_qty=Decimal("10"))
        print("RESULT with losses recv=%s free=%s total=%s"
              % (line.received_qty, line.free_qty, line.total_qty))
        self.assertEqual(line.received_qty, Decimal("918"))
        self.assertEqual(line.free_qty, Decimal("92"))
        self.assertEqual(line.total_qty, Decimal("1010"))

    def test_zero_free_percent_passes_the_quantity_straight_through(self):
        line = self.line(free_percent=Decimal("0"))
        print("RESULT no free    recv=%s free=%s total=%s"
              % (line.received_qty, line.free_qty, line.total_qty))
        self.assertEqual(line.received_qty, Decimal("1000"))
        self.assertEqual(line.free_qty, Decimal("0"))
        self.assertEqual(line.total_qty, Decimal("1000"))

    def test_amount_never_charges_the_free_chicks(self):
        line = self.line()
        self.assertEqual(line.amount, line.received_qty * line.rate)
        self.assertLess(line.amount, line.total_qty * line.rate)
        print("RESULT free not billed: %s < %s"
              % (line.amount, line.total_qty * line.rate))


class ItemBagWeightFieldTests(TestCase):
    """Kg per Bag must be settable from the Item screen.

    The API already accepted and returned it, but the form had no input, so
    every item saved with it empty — which silently zeroed the bag-denominated
    feed reports.
    """

    def setUp(self):
        user = get_user_model().objects.create_superuser(
            "itm", "i@example.com", "Str0ngPass!")
        self.client.force_login(user)
        self.category = ItemCategory.objects.create(name="Feed")

    def test_form_offers_the_field_on_add_and_edit(self):
        html = self.client.get("/items/").content.decode()
        self.assertIn('id="kg_per_bag"', html)          # add form
        self.assertIn('id="dynamic-kg_per_bag"', html)  # edit modal
        self.assertIn("kg_per_bag:", html)              # posted in the payload

    def test_value_round_trips_through_the_api(self):
        import json
        resp = self.client.post(
            "/create-item/",
            data=json.dumps({
                "description": "Pre Starter Feed", "category": self.category.id,
                "valuation_method": "Weighted Average", "standard_cost_per_unit": 50,
                "usage": "Produced", "source": "Purchased", "type": "Raw Material",
                "item_account": "Expense", "kg_per_bag": "50",
            }),
            content_type="application/json")
        self.assertIn(resp.status_code, (200, 201))
        item = Item.objects.get(description="Pre Starter Feed")
        print("RESULT saved kg_per_bag = %s" % item.kg_per_bag)
        self.assertEqual(item.kg_per_bag, Decimal("50"))

    def test_add_form_preselects_every_warehouse(self):
        """All is the default: the Add form opens with every warehouse chosen,
        so an item is visible everywhere unless it is narrowed on purpose."""
        a = Warehouse.objects.create(name="Main Warehouse")
        b = Warehouse.objects.create(name="Akbarpur Warehouse")
        html = self.client.get("/items/").content.decode()
        import re
        add_form = html[html.index('id="item-form"'):html.index("</form>", html.index('id="item-form"'))]
        chosen = re.findall(r'<option value="(\d+)" selected>', add_form)
        print("RESULT preselected warehouse ids: %s of %s"
              % (sorted(chosen), sorted([str(a.id), str(b.id)])))
        self.assertEqual(sorted(chosen), sorted([str(a.id), str(b.id)]))
        # the "All" sentinel itself stays unselected — it is a trigger, and the
        # API expects real ids, not the sentinel
        self.assertNotIn('<option value="__all__" selected>', add_form)

