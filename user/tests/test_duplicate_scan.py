"""The duplicate analyser finds what it claims to, and nothing else.

A scanner that always reports nothing looks identical to a clean database, so
every check here plants a duplicate and insists it is found, then plants a
near-miss and insists it is not. Without the second half the first proves very
little.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from account.models import AccountType, ChartOfAccount, CompanyProfile
from broiler.models import (BirdSale, Branch, BroilerBatch, BroilerFarm, DailyEntry, Farmer,
                            FarmerGroup, MedicineVaccineEntry, Region, Supervisor)
from inventory.models import Item, ItemCategory
from purchase.models import GeneralPurchase, Supplier
from user.services.duplicate_scan import run, summary


def check(code):
    found = run(only=code)
    assert found, f"no check named {code}"
    return found[0]


class DuplicateScanBase(TestCase):

    def setUp(self):
        self.today = date.today()
        self.region = Region.objects.create(description="East")
        self.branch = Branch.objects.create(branch_name="Akbarpur", region=self.region, prefix="AKB")
        self.other_branch = Branch.objects.create(branch_name="Basti", region=self.region, prefix="BST")
        self.supervisor = Supervisor.objects.create(branch=self.branch, name="A. Pal")
        self.category = ItemCategory.objects.create(name="Feed")
        self.farmer = Farmer.objects.create(farmer_name="Vishvanath")

    def farm(self, name="Vishvanath Farm", branch=None):
        return BroilerFarm.objects.create(
            farm_name=name, branch=branch or self.branch, supervisor=self.supervisor,
            farmer=self.farmer, region="East", line="Baskhari", farm_capacity=5000)

    def batch(self, farm):
        return BroilerBatch.objects.create(broiler_farm=farm, start_date=self.today - timedelta(days=20))

    def account(self):
        """A ledger account, which receipts and adjustments cannot be saved without."""
        if not hasattr(self, "_account"):
            kind = AccountType.objects.create(name="Cash", code_range_start=100000,
                                              code_range_end=199999, report="BS")
            self._account = ChartOfAccount.objects.create(
                company=CompanyProfile.get_solo(), code="100001",
                description="Cash in hand", account_type=kind)
        return self._account

    def warehouse(self, name="Central"):
        from inventory.models import Warehouse

        return Warehouse.objects.get_or_create(name=name)[0]


class EntryDuplicateTests(DuplicateScanBase):

    def test_two_daily_entries_on_one_day_are_found(self):
        farm = self.farm()
        batch = self.batch(farm)
        for mortality in (10, 12):
            DailyEntry.objects.create(farm=farm, batch=batch, supervisor=self.supervisor,
                                      date=self.today, mortality=mortality)
        found = check("daily_entry")
        self.assertEqual(found.count, 1)
        self.assertEqual(found.records, 2)
        self.assertIn(batch.batch_name, found.groups[0].matched)

    def test_the_same_flock_on_different_days_is_not_a_duplicate(self):
        farm = self.farm()
        batch = self.batch(farm)
        DailyEntry.objects.create(farm=farm, batch=batch, supervisor=self.supervisor,
                                  date=self.today, mortality=10)
        DailyEntry.objects.create(farm=farm, batch=batch, supervisor=self.supervisor,
                                  date=self.today - timedelta(days=1), mortality=10)
        self.assertEqual(check("daily_entry").count, 0)

    def test_two_flocks_on_the_same_day_are_not_a_duplicate(self):
        for name in ("Farm A", "Farm B"):
            farm = self.farm(name=name)
            DailyEntry.objects.create(farm=farm, batch=self.batch(farm),
                                      supervisor=self.supervisor, date=self.today, mortality=10)
        self.assertEqual(check("daily_entry").count, 0)

    def test_the_same_medicine_twice_in_a_day_is_found(self):
        farm = self.farm()
        item = Item.objects.create(description="Vaccine A", category=self.category,
                                   valuation_method="FIFO", usage="Purchased",
                                   standard_cost_per_unit=Decimal("10"))
        for _ in range(2):
            MedicineVaccineEntry.objects.create(farm=farm, supervisor=self.supervisor,
                                                item=item, date=self.today, qty=Decimal("5"))
        self.assertEqual(check("medicine_entry").count, 1)

    def test_a_different_medicine_the_same_day_is_not_a_duplicate(self):
        farm = self.farm()
        for name in ("Vaccine A", "Vaccine B"):
            item = Item.objects.create(description=name, category=self.category,
                                       valuation_method="FIFO", usage="Purchased",
                                       standard_cost_per_unit=Decimal("10"))
            MedicineVaccineEntry.objects.create(farm=farm, supervisor=self.supervisor,
                                                item=item, date=self.today, qty=Decimal("5"))
        self.assertEqual(check("medicine_entry").count, 0)

    def test_identical_bird_sales_on_one_day_are_found(self):
        farm = self.farm()
        batch = self.batch(farm)
        for _ in range(2):
            BirdSale.objects.create(farm=farm, batch=batch, birds=500, sale_type="farmer",
                                    farmer=self.farmer, date=self.today)
        self.assertEqual(check("bird_sale").count, 1)

    def test_sales_of_different_sizes_are_not_duplicates(self):
        farm = self.farm()
        batch = self.batch(farm)
        for birds in (500, 400):
            BirdSale.objects.create(farm=farm, batch=batch, birds=birds, sale_type="farmer",
                                    farmer=self.farmer, date=self.today)
        self.assertEqual(check("bird_sale").count, 0)

    def test_one_bill_entered_twice_is_found(self):
        supplier = Supplier.objects.create(name="Maharashtra Feeds")
        for _ in range(2):
            GeneralPurchase.objects.create(supplier=supplier, date=self.today, bill_no="INV-77")
        found = check("purchase_bill")
        self.assertEqual(found.count, 1)
        self.assertIn("INV-77", found.groups[0].matched)

    def test_a_blank_bill_number_is_never_a_duplicate(self):
        supplier = Supplier.objects.create(name="Maharashtra Feeds")
        for _ in range(3):
            GeneralPurchase.objects.create(supplier=supplier, date=self.today, bill_no="")
        self.assertEqual(check("purchase_bill").count, 0)

    def test_the_same_bill_from_two_suppliers_is_not_a_duplicate(self):
        for name in ("Feeds A", "Feeds B"):
            GeneralPurchase.objects.create(supplier=Supplier.objects.create(name=name),
                                           date=self.today, bill_no="INV-77")
        self.assertEqual(check("purchase_bill").count, 0)


class MasterDuplicateTests(DuplicateScanBase):

    def test_two_farmers_with_one_name_are_found_whatever_the_case(self):
        Farmer.objects.create(farmer_name="vishvanath")
        found = check("farmer_name")
        self.assertEqual(found.count, 1)
        self.assertEqual(found.records, 2)

    def test_different_farmers_are_left_alone(self):
        Farmer.objects.create(farmer_name="Ramesh")
        self.assertEqual(check("farmer_name").count, 0)

    def test_a_shared_mobile_is_found(self):
        self.farmer.mobile_no = "9876500000"
        self.farmer.save()
        Farmer.objects.create(farmer_name="Ramesh", mobile_no="9876500000")
        self.assertEqual(check("farmer_mobile_no").count, 1)

    def test_blank_identifiers_are_not_matched_against_each_other(self):
        # Every farmer without a PAN would otherwise be a duplicate of every
        # other farmer without a PAN.
        for name in ("A", "B", "C"):
            Farmer.objects.create(farmer_name=name, pan_no="")
        self.assertEqual(check("farmer_pan_no").count, 0)

    def test_two_farms_of_one_name_at_one_branch_are_found(self):
        self.farm()
        self.farm()
        self.assertEqual(check("farm_name").count, 1)

    def test_the_same_farm_name_at_two_branches_is_allowed(self):
        self.farm()
        other_supervisor = Supervisor.objects.create(branch=self.other_branch, name="R. Singh")
        BroilerFarm.objects.create(farm_name="Vishvanath Farm", branch=self.other_branch,
                                   supervisor=other_supervisor, farmer=self.farmer,
                                   region="East", line="L", farm_capacity=100)
        self.assertEqual(check("farm_name").count, 0)

    def test_two_items_of_one_name_in_one_category_are_found(self):
        for _ in range(2):
            Item.objects.create(description="Pre Starter", category=self.category,
                                valuation_method="FIFO", usage="Purchased",
                                standard_cost_per_unit=Decimal("40"))
        self.assertEqual(check("item_description").count, 1)

    def test_the_same_item_name_in_two_categories_is_allowed(self):
        other = ItemCategory.objects.create(name="Medicine")
        for category in (self.category, other):
            Item.objects.create(description="Pre Starter", category=category,
                                valuation_method="FIFO", usage="Purchased",
                                standard_cost_per_unit=Decimal("40"))
        self.assertEqual(check("item_description").count, 0)

    def test_suppliers_and_customers_are_checked_too(self):
        Supplier.objects.create(name="Maharashtra Feeds")
        Supplier.objects.create(name="maharashtra feeds")
        self.assertEqual(check("supplier_name").count, 1)


class ScanShapeTests(DuplicateScanBase):

    def test_a_clean_database_reports_nothing_but_still_runs_every_check(self):
        checks = run()
        self.assertGreaterEqual(len(checks), 13)
        totals = summary(checks)
        self.assertEqual((totals["groups"], totals["records"]), (0, 0))
        self.assertEqual(totals["failed"], [])

    def test_the_summary_separates_entries_from_masters(self):
        Farmer.objects.create(farmer_name="vishvanath")
        farm = self.farm()
        batch = self.batch(farm)
        for mortality in (10, 12):
            DailyEntry.objects.create(farm=farm, batch=batch, supervisor=self.supervisor,
                                      date=self.today, mortality=mortality)
        totals = summary(run())
        self.assertEqual(totals["entry_groups"], 1)
        self.assertEqual(totals["master_groups"], 1)
        self.assertEqual(totals["with_findings"], 2)

    def test_every_check_names_what_it_matched_and_why_it_matters(self):
        for c in run():
            self.assertTrue(c.title and c.matched_on and c.why, c.code)


class DuplicatePageTests(DuplicateScanBase):

    def setUp(self):
        super().setUp()
        self.client.force_login(get_user_model().objects.create_superuser(
            "dupadmin", "d@x.com", "Str0ngPass!"))

    def page(self):
        return self.client.get(reverse("duplicate_analyser"))

    def test_a_clean_database_says_so_rather_than_showing_an_empty_page(self):
        response = self.page()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nothing found")
        self.assertEqual(response.context["totals"]["groups"], 0)

    def test_a_duplicated_entry_is_shown_with_what_it_costs(self):
        farm = self.farm()
        batch = self.batch(farm)
        for mortality in (10, 12):
            DailyEntry.objects.create(farm=farm, batch=batch, supervisor=self.supervisor,
                                      date=self.today, mortality=mortality)
        response = self.page()
        self.assertContains(response, "Two daily entries for one flock on one day")
        self.assertContains(response, "1 match")
        self.assertContains(response, batch.batch_name)
        # the consequence is spelled out, not left to the reader
        self.assertContains(response, "counted twice")

    def test_a_duplicated_master_is_shown_too(self):
        Farmer.objects.create(farmer_name="vishvanath")
        response = self.page()
        self.assertContains(response, "Farmers with the same name")
        self.assertContains(response, "FRM-0001")

    def test_entries_and_masters_are_counted_separately_on_the_page(self):
        Farmer.objects.create(farmer_name="vishvanath")
        response = self.page()
        self.assertEqual(response.context["totals"]["master_groups"], 1)
        self.assertEqual(response.context["totals"]["entry_groups"], 0)

    def test_one_check_can_be_run_on_its_own(self):
        Farmer.objects.create(farmer_name="vishvanath")
        response = self.client.get(reverse("duplicate_analyser"), {"only": "farmer_name"})
        self.assertEqual(response.context["totals"]["checks"], 1)
        self.assertNotContains(response, "Two daily entries for one flock on one day")

    def test_the_page_never_offers_to_change_anything(self):
        # Merging records is not an operation this system has, and a button
        # implying otherwise would be a lie.
        html = self.page().content.decode()
        for word in ("Merge", "Delete duplicate", "Fix all"):
            self.assertNotIn(word, html)


class NewCheckTests(DuplicateScanBase):
    """The checks added to match the reference layout."""

    def test_the_same_purchase_line_twice_is_found(self):
        from purchase.models import GeneralPurchaseItem
        from inventory.models import Warehouse

        supplier = Supplier.objects.create(name="Maharashtra Feeds")
        item = Item.objects.create(description="Pre Starter", category=self.category,
                                   valuation_method="FIFO", usage="Purchased",
                                   standard_cost_per_unit=Decimal("40"))
        warehouse = Warehouse.objects.create(name="Central")
        for bill in ("INV-1", "INV-2"):     # different bills, same delivery
            purchase = GeneralPurchase.objects.create(supplier=supplier, date=self.today, bill_no=bill)
            GeneralPurchaseItem.objects.create(
                purchase=purchase, item=item, farm_warehouse=warehouse, unit="Bag",
                rcv_qty=Decimal("100"), rate=Decimal("42"), discount_percent=Decimal("0"),
                discount_amount=Decimal("0"), gst_percent=Decimal("0"))
        found = check("purchase_line")
        self.assertEqual(found.count, 1)
        # The bill numbers differ, so the bill check alone would not catch it.
        self.assertEqual(check("purchase_bill").count, 0)

    def test_a_repeated_stock_transfer_is_found(self):
        from inventory.models import StockTransfer, Warehouse

        item = Item.objects.create(description="Pre Starter", category=self.category,
                                   valuation_method="FIFO", usage="Purchased",
                                   standard_cost_per_unit=Decimal("40"))
        source = Warehouse.objects.create(name="Central")
        farm = self.farm()
        for _ in range(2):
            StockTransfer.objects.create(
                item=item, quantity=Decimal("50"), date=self.today,
                from_location_type="warehouse", from_warehouse=source,
                to_location_type="farm", to_farm=farm)
        self.assertEqual(check("stock_transfer").count, 1)

    def test_transfers_of_different_sizes_are_not_duplicates(self):
        from inventory.models import StockTransfer, Warehouse

        item = Item.objects.create(description="Pre Starter", category=self.category,
                                   valuation_method="FIFO", usage="Purchased",
                                   standard_cost_per_unit=Decimal("40"))
        source = Warehouse.objects.create(name="Central")
        farm = self.farm()
        for qty in ("50", "60"):
            StockTransfer.objects.create(
                item=item, quantity=Decimal(qty), date=self.today,
                from_location_type="warehouse", from_warehouse=source,
                to_location_type="farm", to_farm=farm)
        self.assertEqual(check("stock_transfer").count, 0)

    def test_suppliers_sharing_a_gstin_are_found(self):
        Supplier.objects.create(name="Feeds A", gstin="09ABCDE1234F1Z5")
        Supplier.objects.create(name="Feeds Alpha", gstin="09ABCDE1234F1Z5")
        self.assertEqual(check("supplier_gstin").count, 1)

    def test_every_check_belongs_to_a_module(self):
        for c in run():
            self.assertTrue(c.module, c.code)

    def test_a_module_can_be_scanned_on_its_own(self):
        broiler_only = run(module="Broiler")
        self.assertTrue(broiler_only)
        self.assertEqual({c.module for c in broiler_only}, {"Broiler"})
        self.assertLess(len(broiler_only), len(run()))


class ExportTests(DuplicateScanBase):

    def setUp(self):
        super().setUp()
        self.client.force_login(get_user_model().objects.create_superuser(
            "expadmin", "e@x.com", "Str0ngPass!"))

    def test_the_findings_download_as_a_file(self):
        Farmer.objects.create(farmer_name="vishvanath")
        response = self.client.get(reverse("duplicate_analyser"), {"export": "csv"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertIn("duplicate-entries.csv", response["Content-Disposition"])
        body = response.content.decode()
        self.assertIn("Farmers with the same name", body)
        self.assertIn("FRM-0001", body)

    def test_the_page_offers_both_tabs_and_the_module_filter(self):
        response = self.client.get(reverse("duplicate_analyser"))
        self.assertContains(response, "Transactional Entries")
        self.assertContains(response, "Master Records")
        self.assertContains(response, 'id="dup-module"')
        self.assertContains(response, "All Modules")
        self.assertContains(response, "Run All Checks")


class HatcheryAndHRTests(DuplicateScanBase):
    """The modules the first version left out entirely."""

    def employee(self, name, **kw):
        from hr.models import Employee

        return Employee.objects.create(full_name=name, **kw)

    def test_two_employees_with_one_name_are_found(self):
        self.employee("R. Verma")
        self.employee("r. verma")
        self.assertEqual(check("employee_name").count, 1)

    def test_different_employees_are_left_alone(self):
        self.employee("R. Verma")
        self.employee("S. Yadav")
        self.assertEqual(check("employee_name").count, 0)

    def test_a_shared_contact_number_is_found(self):
        self.employee("R. Verma", personal_contact=9876500000)
        self.employee("Ramesh V", personal_contact=9876500000)
        self.assertEqual(check("employee_personal_contact").count, 1)

    def test_employees_with_no_contact_are_not_matched_on_it(self):
        # A number column cannot be compared to "", which is what broke the
        # first cut of this check — every HR check went down with it.
        self.employee("A")
        self.employee("B")
        self.assertEqual(check("employee_personal_contact").count, 0)

    def test_attendance_needs_no_check_because_the_database_refuses_it(self):
        # hr.Attendance is unique on (employee, date), so a second mark for one
        # person on one day cannot be stored at all. That is why there is no
        # attendance check: it could never find anything.
        from django.db import IntegrityError, transaction
        from hr.models import Attendance

        person = self.employee("R. Verma")
        Attendance.objects.create(employee=person, date=self.today, status="Present")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Attendance.objects.create(employee=person, date=self.today, status="Present")
        self.assertEqual([c for c in run() if c.code == "attendance_day"], [])

    def test_one_month_paid_twice_is_found(self):
        from hr.models import Payroll

        person = self.employee("R. Verma")
        for _ in range(2):
            Payroll.objects.create(employee=person, month=6, year=2026,
                                   gross_salary=Decimal("20000"), net_salary=Decimal("19000"),
                                   total_working_days=26, payable_salary=Decimal("19000"))
        self.assertEqual(check("payroll_period").count, 1)

    def test_different_months_are_not_duplicates(self):
        from hr.models import Payroll

        person = self.employee("R. Verma")
        for month in (6, 7):
            Payroll.objects.create(employee=person, month=month, year=2026,
                                   gross_salary=Decimal("20000"), net_salary=Decimal("19000"),
                                   total_working_days=26, payable_salary=Decimal("19000"))
        self.assertEqual(check("payroll_period").count, 0)

    def test_hatchery_and_hr_are_both_scannable_on_their_own(self):
        self.assertTrue(run(module="Hatchery"))
        self.assertTrue(run(module="Human Resource"))

    def test_every_business_module_is_covered(self):
        # The first version claimed "all modules" while covering five; this is
        # the assertion that keeps the claim and the code together.
        covered = {c.module for c in run()}
        for name in ("Broiler", "Purchase", "Inventory", "Account", "Sales",
                     "Hatchery", "Human Resource"):
            self.assertIn(name, covered)

    def test_no_check_fails_to_run(self):
        self.assertEqual(summary(run())["failed"], [])


class DashboardWidgetTests(DuplicateScanBase):
    """The dashboard card, which counts without fetching the rows."""

    def plant(self):
        farm = self.farm()
        batch = self.batch(farm)
        for mortality in (10, 12):
            DailyEntry.objects.create(farm=farm, batch=batch, supervisor=self.supervisor,
                                      date=self.today, mortality=mortality)
        Farmer.objects.create(farmer_name="vishvanath")

    def widget(self):
        from user.services.dashboard_widgets import _duplicate_entries

        return _duplicate_entries(None, {}, None)

    def test_counts_only_agrees_with_the_full_scan(self):
        self.plant()
        full, light = summary(run()), summary(run(counts_only=True))
        self.assertEqual(full["groups"], light["groups"])
        # Records matter too: the card shows them, and a placeholder row that
        # did not carry the real count made this read zero for ever.
        self.assertEqual(full["records"], light["records"])
        self.assertEqual(light["records"], 4)

    def test_counts_only_does_not_fetch_the_rows(self):
        self.plant()
        for check in run(counts_only=True):
            for group in check.groups:
                self.assertEqual([r.cells for r in group.rows], [[]] * len(group.rows))

    def test_the_card_reports_what_was_found(self):
        self.plant()
        card = self.widget()
        stats = {s["label"]: s["value"] for s in card["stats"]}
        self.assertEqual(stats["Possible duplicates"], "2")
        self.assertEqual(stats["Entry duplicates"], "1")
        self.assertEqual(stats["Records involved"], "4")
        self.assertTrue(card["findings"])
        self.assertIn("Farm + Batch + Date", [f["matched_on"] for f in card["findings"]])
        self.assertTrue(card["checked_at"])

    def test_the_card_breaks_the_findings_down_by_module(self):
        self.plant()
        bands = self.widget()["bands"]
        self.assertEqual([b["label"] for b in bands], ["Broiler"])
        self.assertEqual(bands[0]["count"], 2)
        # One module holding everything is the whole band, and each band
        # carries the colour its findings are dotted with.
        self.assertEqual(bands[0]["share"], 100.0)
        self.assertTrue(bands[0]["colour"].startswith("#"))

    def test_a_clean_database_says_so_and_draws_no_band(self):
        card = self.widget()
        self.assertEqual(card["bands"], [])
        self.assertIn("Nothing found", card["note"])
        self.assertEqual(card["findings"], [])

    def test_the_card_admits_the_dashboard_filters_do_not_apply(self):
        # An empty filters_used is what makes the dashboard print "Date does
        # not apply here" rather than showing a figure that ignored it.
        self.assertEqual(self.widget()["filters_used"], [])

    def test_the_widget_is_registered_and_gated_on_the_page(self):
        from user.services.dashboard_widgets import WIDGETS

        entry = [w for w in WIDGETS if w[0] == "duplicates"]
        self.assertEqual(len(entry), 1)
        key, title, tabs, url, _icon, _colour, _build = entry[0]
        self.assertEqual((title, tabs, url),
                         ("Duplicate Entries", ("duplicate_analyser",), "duplicate_analyser"))

    def test_it_sits_before_field_team_in_the_default_order(self):
        from user.services.dashboard_widgets import DEFAULT_PANEL_ORDER

        order = list(DEFAULT_PANEL_ORDER)
        self.assertLess(order.index("duplicates"), order.index("field_team"))


class MoneyDuplicateTests(DuplicateScanBase):
    """Where a duplicate moves cash rather than a figure."""

    def customer(self, name="Sample Customer", mobile="9000000001"):
        from sales.models import Customer

        return Customer.objects.create(name=name, address="Main Road", mobile=mobile)

    def test_the_same_customer_receipt_twice_is_found(self):
        from sales.models import SalesReceipt

        customer = self.customer()
        for _ in range(2):
            SalesReceipt.objects.create(customer=customer, date=self.today,
                                        amount=Decimal("5000"), mode="Cash",
                                        location=self.warehouse(), receipt_account=self.account())
        found = check("sales_receipt")
        self.assertEqual(found.count, 1)
        self.assertEqual(found.records, 2)

    def test_receipts_of_different_amounts_are_not_duplicates(self):
        from sales.models import SalesReceipt

        customer = self.customer()
        for amount in ("5000", "4000"):
            SalesReceipt.objects.create(customer=customer, date=self.today,
                                        amount=Decimal(amount), mode="Cash",
                                        location=self.warehouse(), receipt_account=self.account())
        self.assertEqual(check("sales_receipt").count, 0)

    def test_two_customers_paying_the_same_amount_are_not_duplicates(self):
        from sales.models import SalesReceipt

        for i, name in enumerate(("A Ltd", "B Ltd")):
            SalesReceipt.objects.create(customer=self.customer(name, f"90000000{i}2"),
                                        date=self.today, amount=Decimal("5000"), mode="Cash",
                                        location=self.warehouse(), receipt_account=self.account())
        self.assertEqual(check("sales_receipt").count, 0)

    def test_the_same_bird_sale_receipt_twice_is_found(self):
        from broiler.models import BirdSaleReceipt

        for _ in range(2):
            BirdSaleReceipt.objects.create(farmer=self.farmer, sale_type="farmer",
                                           date=self.today, amount=Decimal("1200"), mode="Cash",
                                           location=self.warehouse(), receipt_account=self.account())
        self.assertEqual(check("bird_sale_receipt").count, 1)

    def test_the_same_growing_charge_payment_twice_is_found(self):
        from broiler.models import FarmerGCPayment

        for _ in range(2):
            FarmerGCPayment.objects.create(date=self.today, narration="GC for June")
        self.assertEqual(check("gc_payment").count, 1)

    def test_a_payment_with_no_narration_is_not_matched(self):
        from broiler.models import FarmerGCPayment

        for _ in range(3):
            FarmerGCPayment.objects.create(date=self.today, narration="")
        self.assertEqual(check("gc_payment").count, 0)

    def test_the_same_supplier_debit_note_twice_is_found(self):
        from purchase.models import DebitNote

        supplier = Supplier.objects.create(name="Maharashtra Feeds")
        for _ in range(2):
            DebitNote.objects.create(supplier=supplier, date=self.today,
                                     amount=Decimal("750"), against_bill="INV-9")
        self.assertEqual(check("debitnote").count, 1)


class StockMovementDuplicateTests(DuplicateScanBase):

    def item(self, name="Pre Starter"):
        return Item.objects.create(description=name, category=self.category,
                                   valuation_method="FIFO", usage="Purchased",
                                   standard_cost_per_unit=Decimal("40"))

    def test_the_same_inventory_adjustment_twice_is_found(self):
        from inventory.models import InventoryAdjustment, InventoryAdjustmentItem

        warehouse = self.warehouse()
        item = self.item()
        for _ in range(2):
            adjustment = InventoryAdjustment.objects.create(
                date=self.today, location_type="warehouse", warehouse=warehouse,
                chart_of_account=self.account())
            InventoryAdjustmentItem.objects.create(
                adjustment=adjustment, item=item, adjustment_type="add",
                quantity=Decimal("20"), rate=Decimal("40"))
        self.assertEqual(check("inventory_adjustment").count, 1)

    def test_adjustments_of_different_sizes_are_not_duplicates(self):
        from inventory.models import InventoryAdjustment, InventoryAdjustmentItem

        warehouse = self.warehouse()
        item = self.item()
        for qty in ("20", "30"):
            adjustment = InventoryAdjustment.objects.create(
                date=self.today, location_type="warehouse", warehouse=warehouse,
                chart_of_account=self.account())
            InventoryAdjustmentItem.objects.create(
                adjustment=adjustment, item=item, adjustment_type="add",
                quantity=Decimal(qty), rate=Decimal("40"))
        self.assertEqual(check("inventory_adjustment").count, 0)


class HatcheryProductionTests(DuplicateScanBase):

    def test_hatch_entries_need_no_check_because_the_database_refuses_them(self):
        # HatchEntry.tray_setting is a one-to-one, so a second hatch against one
        # setting cannot be stored. Same reasoning as attendance and settlement.
        self.assertEqual([c for c in run() if c.code == "hatch_entry"], [])

    def test_a_settlement_cannot_be_duplicated_either(self):
        from broiler.models import GrowingChargeSettlement

        field = GrowingChargeSettlement._meta.get_field("batch")
        self.assertTrue(field.one_to_one, "a batch can only be settled once")


class CoverageTests(DuplicateScanBase):

    def test_every_check_runs_and_is_described(self):
        checks = run()
        self.assertGreaterEqual(len(checks), 38)
        self.assertEqual(summary(checks)["failed"], [])
        for c in checks:
            self.assertTrue(c.title and c.matched_on and c.why and c.module, c.code)
            self.assertTrue(c.columns, c.code)

    def test_check_codes_are_unique(self):
        codes = [c.code for c in run()]
        self.assertEqual(len(codes), len(set(codes)))

    def test_the_money_movements_are_all_covered(self):
        codes = {c.code for c in run()}
        for code in ("sales_receipt", "bird_sale_receipt", "gc_payment",
                     "debitnote", "creditnote", "customerdebitnote", "customercreditnote",
                     "sales_invoice_reference"):
            self.assertIn(code, codes)


class WhereItHappenedTests(DuplicateScanBase):
    """Every row says where it happened, and the source counts as "where"."""

    def transfer(self, item, source_farm, dest_farm, qty="50"):
        from inventory.models import StockTransfer

        return StockTransfer.objects.create(
            item=item, quantity=Decimal(qty), date=self.today,
            from_location_type="farm", from_farm=source_farm,
            to_location_type="farm", to_farm=dest_farm)

    def test_transfers_from_different_sources_are_not_duplicates(self):
        # The case that was being reported wrongly: same item, same quantity,
        # same day, same destination — but one delivery from each of two farms.
        item = Item.objects.create(description="Starter", category=self.category,
                                   valuation_method="FIFO", usage="Purchased",
                                   standard_cost_per_unit=Decimal("40"))
        destination = self.farm(name="Destination Farm")
        self.transfer(item, self.farm(name="Source A"), destination)
        self.transfer(item, self.farm(name="Source B"), destination)
        self.assertEqual(check("stock_transfer").count, 0)

    def test_the_same_source_and_destination_is_still_a_duplicate(self):
        item = Item.objects.create(description="Starter", category=self.category,
                                   valuation_method="FIFO", usage="Purchased",
                                   standard_cost_per_unit=Decimal("40"))
        source, destination = self.farm(name="Source A"), self.farm(name="Destination Farm")
        self.transfer(item, source, destination)
        self.transfer(item, source, destination)
        found = check("stock_transfer")
        self.assertEqual(found.count, 1)
        self.assertIn("From", found.columns)
        self.assertIn("Source A", found.groups[0].rows[0].cells)

    def test_a_daily_entry_row_names_its_branch(self):
        farm = self.farm()
        batch = self.batch(farm)
        for mortality in (10, 12):
            DailyEntry.objects.create(farm=farm, batch=batch, supervisor=self.supervisor,
                                      date=self.today, mortality=mortality)
        found = check("daily_entry")
        self.assertIn("Branch", found.columns)
        self.assertIn("Akbarpur", found.groups[0].rows[0].cells)

    def test_a_receipt_row_names_its_location(self):
        from sales.models import Customer, SalesReceipt

        customer = Customer.objects.create(name="Sample", address="Road", mobile="9000000009")
        for _ in range(2):
            SalesReceipt.objects.create(customer=customer, date=self.today,
                                        amount=Decimal("500"), mode="Cash",
                                        location=self.warehouse("Akbarpur Store"),
                                        receipt_account=self.account())
        found = check("sales_receipt")
        self.assertIn("Location", found.columns)
        self.assertIn("Akbarpur Store", found.groups[0].rows[0].cells)

    def test_every_row_has_a_cell_for_every_column(self):
        # A column added to one check and not to its cells would push every
        # value in that row one place left.
        for c in run():
            for group in c.groups:
                for row in group.rows:
                    self.assertEqual(len(row.cells), len(c.columns), c.code)


class WhereToGoTests(DuplicateScanBase):
    """Each check names the page its records are entered on."""

    def test_every_check_names_a_page(self):
        for c in run():
            self.assertTrue(c.tab, c.code)
            self.assertIn("›", c.where, c.code)

    def test_the_path_reads_module_section_tab(self):
        daily = check("daily_entry")
        self.assertEqual(daily.where, "Broiler › Transactions › Daily Entry")
        self.assertEqual(check("sales_receipt").where, "Sales › Transactions › Sales Receipt")
        self.assertEqual(check("payroll_period").where, "Human Resource › Payroll › Payroll")

    def test_the_path_comes_from_the_registry_not_a_second_copy(self):
        # Rename a tab in the access registry and the analyser follows, rather
        # than going on showing the old name.
        from user.services import duplicate_scan

        duplicate_scan._TAB_PATHS = None
        try:
            duplicate_scan._TAB_PATHS = {"daily_entry_list": ("Broiler", "Transactions", "Renamed")}
            self.assertEqual(check("daily_entry").where, "Broiler › Transactions › Renamed")
        finally:
            duplicate_scan._TAB_PATHS = None

    def test_every_tab_named_actually_exists(self):
        from user.access import iter_tabs
        from user.services.duplicate_scan import CHECK_TABS

        known = {code for _nav, _section, code, _label, _extra in iter_tabs()}
        for check_code, tab in CHECK_TABS.items():
            self.assertIn(tab, known, f"{check_code} points at a tab that is not registered")


class FullDetailTests(DuplicateScanBase):

    def test_a_daily_entry_row_carries_the_whole_day(self):
        farm = self.farm()
        batch = self.batch(farm)
        for mortality in (10, 12):
            DailyEntry.objects.create(farm=farm, batch=batch, supervisor=self.supervisor,
                                      date=self.today, mortality=mortality, culls=1,
                                      feed_1_qty=Decimal("40"))
        found = check("daily_entry")
        for column in ("Age", "Mortality", "Culls", "Feed 1", "Entered by", "Entered at"):
            self.assertIn(column, found.columns)
        self.assertEqual(len(found.groups[0].rows[0].cells), len(found.columns))

    def test_a_purchase_line_carries_its_costing(self):
        from purchase.models import GeneralPurchaseItem

        supplier = Supplier.objects.create(name="Feeds Ltd")
        item = Item.objects.create(description="Starter", category=self.category,
                                   valuation_method="FIFO", usage="Purchased",
                                   standard_cost_per_unit=Decimal("40"))
        for bill in ("A-1", "A-2"):
            purchase = GeneralPurchase.objects.create(supplier=supplier, date=self.today, bill_no=bill)
            GeneralPurchaseItem.objects.create(
                purchase=purchase, item=item, farm_warehouse=self.warehouse(), unit="Bag",
                rcv_qty=Decimal("100"), rate=Decimal("42"), discount_percent=Decimal("0"),
                discount_amount=Decimal("0"), gst_percent=Decimal("5"))
        found = check("purchase_line")
        for column in ("Bill No", "Warehouse", "Unit", "Sent", "Received", "Free",
                       "Rate", "Discount", "GST %", "Amount"):
            self.assertIn(column, found.columns)
        self.assertEqual(len(found.groups[0].rows[0].cells), len(found.columns))
