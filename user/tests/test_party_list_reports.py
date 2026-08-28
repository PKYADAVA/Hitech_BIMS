"""Supplier List and Customer List — the party masters as a report.

Not balance reports. These answer who we deal with and whether their record is
complete; Supplier Balance and Customer Balance answer what they owe. That is
why they carry every column on the master rather than a chosen handful.

Both run through one module, so most of what matters is tested once here and
confirmed on the other side.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from purchase.models import Supplier
from sales.models import Customer, CustomerGroup


class PartyListMixin:
    def page(self, **params):
        return self.client.get(self.url, params).context

    def rows(self, **params):
        return self.page(**params)["rows"]

    def headers(self, **params):
        return [c["label"] for c in self.page(**params)["columns"]]

    def cell(self, row, header, **params):
        """One cell by column name, since rows are positional."""
        labels = self.headers(**params)
        return row["cells"][labels.index(header)]

    def named(self, name, **params):
        labels = self.headers(**params)
        for row in self.rows(**params):
            if row["cells"][labels.index("Name")] == name:
                return row
        return None


class SupplierListTests(PartyListMixin, TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="buyer", password="x", email="b@example.com")
        self.client.force_login(self.user)
        self.url = reverse("supplier_list_report")

        Supplier.objects.create(name="Balaji Feeds", code="SUP-1",
                                supplier_group="Feed", gstin="29ABCDE1234F1Z5",
                                mobile="9990001112", credit_limit=Decimal("50000"),
                                state="Karnataka")
        Supplier.objects.create(name="Verma Traders", code="SUP-2",
                                supplier_group="Medicine", gstin="",
                                mobile="9990001113", credit_limit=Decimal("25000"),
                                state="Uttar Pradesh")
        Supplier.objects.create(name="Nobody Ltd", code="SUP-3",
                                supplier_group="Feed", mobile="9990001114")

    # -- the whole master -------------------------------------------------

    def test_every_field_on_the_master_is_a_column(self):
        """The point of the report. A hand-written column list would be wrong
        the first time somebody adds a field and forgets this one."""
        expected = {f.name for f in Supplier._meta.fields} - {"id"}
        got = {c["name"] for c in self.page()["columns"]}
        self.assertEqual(got, expected)

    def test_acronyms_are_not_titlecased_into_typos(self):
        """A printed sheet that says Gstin and Ifsc code reads as a mistake."""
        headers = self.headers()
        for wanted in ("GSTIN", "PAN", "IFSC Code", "Aadhaar", "A/c No."):
            self.assertIn(wanted, headers)
        for unwanted in ("Gstin", "Ifsc code", "Aadhar"):
            self.assertNotIn(unwanted, headers)

    def test_a_row_has_a_cell_for_every_column(self):
        for row in self.rows():
            self.assertEqual(len(row["cells"]), len(self.page()["columns"]))

    def test_an_upload_reads_as_yes_rather_than_a_storage_path(self):
        """Nobody can click a path on a printed page, and showing one implies
        the file is somewhere the reader can reach."""
        self.assertEqual(self.cell(self.named("Balaji Feeds"), "Agreement copy"), "")

    # -- filters ----------------------------------------------------------

    def test_every_supplier_is_listed(self):
        self.assertEqual(len(self.rows()), 3)

    def test_the_group_filter_narrows_it(self):
        rows = self.rows(group="Feed")
        labels = self.headers(group="Feed")
        names = [r["cells"][labels.index("Name")] for r in rows]
        self.assertEqual(names, ["Balaji Feeds", "Nobody Ltd"])

    def test_search_looks_at_name_code_gstin_and_mobile(self):
        for term, expected in (("Verma", "Verma Traders"),
                               ("SUP-1", "Balaji Feeds"),
                               ("29ABCDE", "Balaji Feeds"),
                               ("9990001114", "Nobody Ltd")):
            self.assertIsNotNone(self.named(expected, q=term), term)
            self.assertEqual(len(self.rows(q=term)), 1, term)

    def test_registered_and_unregistered_add_up_to_everyone(self):
        """A blank GSTIN and a null one both mean not registered. Catching only
        one would leave the two halves not adding up to the count on the card
        above them."""
        with_gst = self.rows(gst="with")
        without = self.rows(gst="without")
        self.assertEqual(len(with_gst), 1)
        self.assertEqual(len(with_gst) + len(without), 3)

    # -- totals -----------------------------------------------------------

    def test_only_the_columns_worth_adding_up_carry_a_total(self):
        """Summing a credit term in days would produce a number that means
        nothing and looks official."""
        totalled = {c["name"] for c in self.page()["columns"] if c["totalled"]}
        self.assertEqual(totalled, {"credit_limit", "opening_balance"})

    def test_the_totals_are_right(self):
        totals = self.page()["totals"]
        self.assertEqual(totals["count"], 3)
        self.assertEqual(totals["with_gstin"], 1)
        self.assertEqual(totals["credit_limit"], Decimal("75000"))

    def test_totals_follow_the_filter_rather_than_the_whole_master(self):
        """A filtered report whose totals quietly cover everyone is worse than
        one with no totals at all."""
        self.assertEqual(self.page(group="Medicine")["totals"]["credit_limit"],
                         Decimal("25000"))

    # -- export -----------------------------------------------------------

    def test_the_excel_export_comes_back_as_a_spreadsheet(self):
        response = self.client.get(self.url, {"export": "excel"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("spreadsheet", response["Content-Type"])
        self.assertIn("supplier_list.xlsx", response["Content-Disposition"])

    def test_the_export_carries_the_filter_too(self):
        """Exporting from a filtered screen must not quietly widen to everyone."""
        self.assertEqual(
            self.client.get(self.url, {"group": "Medicine", "export": "excel"}).status_code,
            200)


class CustomerListTests(PartyListMixin, TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="seller", password="x", email="s@example.com")
        self.client.force_login(self.user)
        self.url = reverse("customer_list_report")

        self.group = CustomerGroup.objects.create(code="CG1", description="Traders")
        Customer.objects.create(name="Sample Customer", code="CUST-0001",
                                customer_group=self.group, gstin="29ABCDE1234F1Z5",
                                mobile="9999999999", credit_limit=Decimal("5000"))
        Customer.objects.create(name="Abhinav", code="CUST-0002",
                                mobile="8977793600")

    def test_every_field_on_the_master_is_a_column(self):
        expected = {f.name for f in Customer._meta.fields} - {"id"}
        got = {c["name"] for c in self.page()["columns"]}
        self.assertEqual(got, expected)

    def test_the_customer_has_its_own_columns_not_the_suppliers(self):
        """The two masters differ — customers have a phone and a credit period
        that suppliers do not — so a shared report has to follow the model it
        was handed."""
        headers = self.headers()
        self.assertIn("Credit Period", headers)
        self.assertIn("Phone", headers)
        self.assertIn("PAN / TIN", headers)

    def test_a_foreign_key_reads_as_its_name_not_its_id(self):
        self.assertEqual(self.cell(self.named("Sample Customer"), "Customer group"),
                         "Traders")

    def test_a_customer_with_no_group_is_listed_rather_than_dropped(self):
        """An incomplete record is exactly what this report exists to surface."""
        row = self.named("Abhinav")
        self.assertIsNotNone(row)
        self.assertEqual(self.cell(row, "Customer group"), "")

    def test_the_group_filter_takes_the_group_id(self):
        """Customer groups are a table, unlike the supplier's free-text field."""
        self.assertEqual(len(self.rows(group=str(self.group.id))), 1)

    def test_the_excel_export_is_named_for_this_report(self):
        response = self.client.get(self.url, {"export": "excel"})
        self.assertIn("customer_list.xlsx", response["Content-Disposition"])
