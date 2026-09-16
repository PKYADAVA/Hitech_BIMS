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
