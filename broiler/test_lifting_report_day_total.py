"""Lifting Report: one customer's liftings on a day, with that day's total sale
value beside the total received from them."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from notification.tests import test_doc_sources as _sources


class _LiftingReportFixture(TestCase):
    """The fixtures and helpers; the tests are in the classes below."""

    def setUp(self):
        # The same farm, customer, one sale and one receipt the source tests build.
        _sources.SourceRowTests.setUp(self)
        self.user = get_user_model().objects.create_superuser("lift", password="pw12345!")
        self.client.force_login(self.user)

    _till = _sources.SourceRowTests._till

    def _more_sale(self, customer=None, amount="30000"):
        from broiler.models import BirdSale

        return BirdSale.objects.create(
            farm=self.farm, batch=self.batch, date=self.today, sale_type="customer",
            customer=customer or self.customer, birds=100, net_weight=Decimal("200"),
            rate=Decimal("90"), amount=Decimal(amount))

    def _page(self, **extra):
        r = self.client.get(reverse("lifting_report"), {
            "from_date": self.today.isoformat(), "to_date": self.today.isoformat(), **extra})
        self.assertEqual(r.status_code, 200)
        return r.context


class LiftingReportDayTotalTests(_LiftingReportFixture):
    def test_two_liftings_for_a_customer_in_a_day_get_a_day_total_line(self):
        self._more_sale()
        ctx = self._page()
        totals = [r for r in ctx["shown_rows"] if r.get("is_day_total")]
        self.assertEqual(len(totals), 1)
        t = totals[0]
        self.assertEqual(t["count"], 2)
        self.assertEqual(t["customer"], "Sadar Traders")
        # 76,000 (the fixture sale) + 18,000 (200 kg at 90: a sale's amount is weight times rate)
        self.assertEqual(t["total"], Decimal("94000.00"))
        # The 50,000 received from them that day, shown beside it.
        self.assertEqual(t["receipt"], Decimal("50000.00"))

    def test_the_day_total_line_follows_its_customers_liftings(self):
        self._more_sale()
        shown = self._page()["shown_rows"]
        self.assertEqual([bool(r.get("is_day_total")) for r in shown], [False, False, True])

    def test_one_lifting_in_a_day_needs_no_day_total(self):
        ctx = self._page()
        self.assertFalse([r for r in ctx["shown_rows"] if r.get("is_day_total")])

    def test_the_report_totals_do_not_count_a_day_total_twice(self):
        self._more_sale()
        ctx = self._page()
        self.assertEqual(len(ctx["rows"]), 2)
        self.assertEqual(ctx["totals"]["total"], Decimal("94000.00"))
        self.assertEqual(ctx["totals"]["receipt"], Decimal("50000.00"))

    def test_another_customers_liftings_are_not_folded_into_the_total(self):
        from sales.models import Customer

        other = Customer.objects.create(name="Zed Poultry", mobile="9876500088")
        self._more_sale(customer=other, amount="10000")
        self._more_sale()
        ctx = self._page()
        totals = [r for r in ctx["shown_rows"] if r.get("is_day_total")]
        self.assertEqual(len(totals), 1)
        self.assertEqual(totals[0]["customer"], "Sadar Traders")
        self.assertEqual(totals[0]["total"], Decimal("94000.00"))


class LiftingReportDayTotalOptionTests(_LiftingReportFixture):
    """The Day totals choice and the paid / due summary on each line."""

    def test_every_customer_day_gets_a_line_when_asked(self):
        ctx = self._page(day_totals="all")
        self.assertEqual(len([r for r in ctx["shown_rows"] if r.get("is_day_total")]), 1)

    def test_day_totals_can_be_switched_off(self):
        self._more_sale()
        ctx = self._page(day_totals="off")
        self.assertFalse([r for r in ctx["shown_rows"] if r.get("is_day_total")])

    def test_an_unknown_choice_falls_back_to_repeat_liftings(self):
        self._more_sale()
        ctx = self._page(day_totals="nonsense")
        self.assertEqual(ctx["day_totals"], "multi")
        self.assertEqual(len([r for r in ctx["shown_rows"] if r.get("is_day_total")]), 1)

    def test_the_line_says_how_much_is_still_due(self):
        self._more_sale()
        t = [r for r in self._page()["shown_rows"] if r.get("is_day_total")][0]
        # 94,000 sold, 50,000 received
        self.assertEqual((t["standing"], t["gap"]), ("due", Decimal("44000.00")))

    def test_a_day_with_no_receipt_is_unpaid(self):
        from broiler.models import BirdSaleReceipt

        BirdSaleReceipt.objects.all().delete()
        self._more_sale()
        t = [r for r in self._page()["shown_rows"] if r.get("is_day_total")][0]
        self.assertEqual(t["standing"], "unpaid")


class LiftingReportExcelTests(_LiftingReportFixture):
    """The Excel download is the report as shown."""

    def _xlsx(self, **extra):
        import io

        import openpyxl

        r = self.client.get(reverse("lifting_report"), {
            "from_date": self.today.isoformat(), "to_date": self.today.isoformat(),
            "export": "excel", **extra})
        self.assertEqual(r.status_code, 200)
        self.assertIn("spreadsheetml", r["Content-Type"])
        self.assertIn("lifting_report.xlsx", r["Content-Disposition"])
        return openpyxl.load_workbook(io.BytesIO(r.content)).active

    def _data_rows(self, ws):
        head = next(i for i in range(1, ws.max_row + 1) if ws.cell(i, 1).value == "Date")
        return head, [[c.value for c in ws[i]] for i in range(head + 1, ws.max_row + 1)]

    def test_the_sheet_has_the_columns_and_real_numbers(self):
        ws = self._xlsx()
        head, rows = self._data_rows(ws)
        headings = [c.value for c in ws[head]]
        self.assertEqual(headings[:3], ["Date", "Branch", "Line"])
        self.assertIn("Receipt Amount", headings)
        first = rows[0]
        self.assertEqual(first[headings.index("Customer")], "Sadar Traders")
        self.assertEqual(first[headings.index("Total Amount")], 76000.0)      # a number, not text
        self.assertIsInstance(first[headings.index("Birds")], int)

    def test_day_total_lines_and_the_grand_total_are_in_the_sheet(self):
        self._more_sale()
        ws = self._xlsx()
        head, rows = self._data_rows(ws)
        headings = [c.value for c in ws[head]]
        farm = headings.index("Farm")
        labels = [r[farm] for r in rows]
        self.assertIn("Day total (2)", labels)
        day = rows[labels.index("Day total (2)")]
        self.assertEqual(day[headings.index("Total Amount")], 94000.0)
        self.assertEqual(day[headings.index("Receipt Amount")], 50000.0)
        self.assertIn("due", day[headings.index("Remarks")])
        total = rows[-1]
        self.assertEqual(total[0], "Total")
        self.assertEqual(total[headings.index("Total Amount")], 94000.0)   # day total not counted twice

    def test_the_download_follows_the_day_totals_choice(self):
        self._more_sale()
        ws = self._xlsx(day_totals="off")
        head, rows = self._data_rows(ws)
        farm = [c.value for c in ws[head]].index("Farm")
        self.assertFalse([r for r in rows if str(r[farm]).startswith("Day total")])

    def test_the_sheet_states_the_filters(self):
        ws = self._xlsx()
        self.assertIn("From", ws["A3"].value)

    def test_the_report_page_links_to_the_download(self):
        r = self.client.get(reverse("lifting_report"))
        self.assertContains(r, "export=excel")
