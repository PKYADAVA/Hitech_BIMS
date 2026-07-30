import re
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from account.models import AccountType, ChartOfAccount, CompanyProfile
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
