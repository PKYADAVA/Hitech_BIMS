"""Which ERP documents the SMS Transaction grid can send from.

The page offered three sources, all of them hatchery, while the template
editor let a template be tagged to any of eight modules and twenty-five
transactions. Templates had already been written for broiler bird sales,
broiler receipts and sales payment reminders — none of which had a document
behind them, so the module they were written for never appeared in the
sender's dropdown at all.

Every registered transaction that has a document and an outside party now has
a source. The ones that do not are listed at the bottom of this file, each
with the reason, and asserted so the list cannot drift unnoticed.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from notification.comm_sources import (DOC_SOURCES, PARTY_TYPES,
                                       TRANSACTION_VARIABLES, _mobile,
                                       party_choices)
from notification.constants import SMS_MODULE_TRANSACTIONS


class DocSourceRegistryTests(TestCase):
    """The shape of the registry, independent of any data in it."""

    def test_every_source_declares_a_party_type_the_page_can_render(self):
        """A source whose party type has no dropdown would filter by a control
        that is not on the page."""
        for key, src in DOC_SOURCES.items():
            self.assertIn(src["party_type"], PARTY_TYPES, key)

    def test_every_source_names_a_transaction_its_module_registers(self):
        """The template filter matches on module *and* transaction, so a
        source pointing at a code its module does not list would silently
        offer no templates at all."""
        for key, src in DOC_SOURCES.items():
            codes = [c for c, _ in SMS_MODULE_TRANSACTIONS.get(src["module"], ())]
            self.assertIn(src["transaction"], codes, key)

    def test_the_modules_with_documents_are_all_represented(self):
        modules = {src["module"] for src in DOC_SOURCES.values()}
        self.assertEqual(
            modules,
            {"hatchery", "broiler", "sales", "purchase", "account", "inventory", "hr"})

    def test_a_transaction_code_shared_by_two_modules_keeps_both_variables(self):
        """"payment_receipt" is a customer receipt under Sales and a supplier
        payment under Account. Keyed by code alone, the second registered used
        to overwrite the first and grey out good variables in the editor."""
        shared = TRANSACTION_VARIABLES["payment_receipt"]
        self.assertIn("CustomerName", shared)
        self.assertIn("SupplierName", shared)

    def test_every_declared_variable_is_one_the_editor_knows(self):
        from notification.comm_sources import SMS_VARIABLES

        for key, src in DOC_SOURCES.items():
            for name in src["variables"]:
                self.assertIn(name, SMS_VARIABLES, f"{key} -> {name}")


class MobilePickerTests(TestCase):
    def test_it_takes_the_first_number_that_is_there(self):
        self.assertEqual(_mobile("", None, "9876543210"), "9876543210")

    def test_a_party_with_no_number_yields_empty_not_the_word_none(self):
        """Employee numbers are integers and a blank one arrives as None; the
        grid prints this straight into a "mobile missing" cell."""
        self.assertEqual(_mobile(None, "", "  "), "")
        self.assertEqual(_mobile("None"), "")

    def test_an_integer_contact_becomes_text(self):
        self.assertEqual(_mobile(9876543210), "9876543210")


class SourceRowTests(TestCase):
    """Each source against real rows: the party it addresses, and the
    variables its template will render."""

    def setUp(self):
        from broiler.models import (BirdSale, BirdSaleReceipt, Branch,
                                    BroilerBatch, BroilerFarm, Farmer, Region,
                                    Supervisor)
        from account.models import ChartOfAccount
        from inventory.models import Warehouse
        from purchase.models import GeneralPurchase, Supplier
        from sales.models import Customer

        self.today = timezone.localdate()
        self.customer = Customer.objects.create(
            name="Sadar Traders", mobile="9876500001", phone="0522-100001")
        self.supplier = Supplier.objects.create(
            name="Balaji Feeds", mobile="9876500002")

        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region,
                                       prefix="AKB")
        sup = Supervisor.objects.create(branch=branch, name="R. Verma")
        self.farmer = Farmer.objects.create(farmer_name="S. Yadav",
                                            mobile_no="9876500003")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=sup, farmer=self.farmer, region=region,
            line="L1", farm_name="Yadav Farm", farm_capacity=9000)
        self.batch = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="B-1",
            start_date=self.today - timedelta(days=30))

        self.sale = BirdSale.objects.create(
            farm=self.farm, batch=self.batch, date=self.today,
            sale_type="customer", customer=self.customer, birds=400,
            net_weight=Decimal("800.00"), rate=Decimal("95"),
            amount=Decimal("76000"), vehicle="UP53TT6785", driver="Ram")
        self.receipt = BirdSaleReceipt.objects.create(
            date=self.today, sale_type="customer", customer=self.customer,
            mode="Bank Transfer", amount=Decimal("50000"),
            location=Warehouse.objects.create(name="Akbarpur Counter"),
            receipt_account=self._till())
        self.purchase = GeneralPurchase.objects.create(
            date=self.today, supplier=self.supplier, net_amount=Decimal("31000"),
            vehicle_no="UP53AA1111")

    def _till(self):
        """A cash ledger to book a receipt against — the model insists on one."""
        from account.models import (AccountType, ChartOfAccount, CompanyProfile)

        kind, _ = AccountType.objects.get_or_create(
            name="Asset", defaults={"code": "AS"})
        return ChartOfAccount.objects.create(
            company=CompanyProfile.get_solo(), code="1001",
            description="Cash in Hand", account_type=kind)

    def rows(self, key, **kw):
        kw.setdefault("from_date", None)
        kw.setdefault("to_date", None)
        kw.setdefault("party_id", None)
        return DOC_SOURCES[key]["rows"](kw["from_date"], kw["to_date"], kw["party_id"])

    # ---- broiler ------------------------------------------------------------

    def test_a_bird_sale_is_addressed_to_its_customer(self):
        row = self.rows("bird_sale")[0]
        self.assertEqual(row["party_type"], "customer")
        self.assertEqual(row["party_name"], "Sadar Traders")
        self.assertEqual(row["mobile"], "9876500001")
        self.assertEqual(row["context"]["Quantity"], "400")
        self.assertEqual(row["context"]["Weight"], "800.00")

    def test_a_farmer_side_lifting_is_not_a_sale_anybody_bills(self):
        from broiler.models import BirdSale

        BirdSale.objects.create(farm=self.farm, batch=self.batch, date=self.today,
                                sale_type="farmer", farmer=self.farmer, birds=50,
                                net_weight=Decimal("100"), rate=Decimal("90"),
                                amount=Decimal("9000"))
        self.assertEqual(len(self.rows("bird_sale")), 1)

    def test_bird_receipt_is_the_money_not_the_birds(self):
        """The template registered for it reads "Amount Rcvd Rs ... via ...",
        which settles what the transaction code means."""
        row = self.rows("bird_receipt")[0]
        self.assertEqual(row["party_type"], "customer")
        self.assertEqual(row["context"]["PaidAmount"], "50,000.00")
        self.assertEqual(row["context"]["PaymentMode"], "Bank Transfer")

    def test_a_broiler_batch_is_addressed_to_the_farmer_growing_it(self):
        row = self.rows("broiler_batch")[0]
        self.assertEqual(row["party_type"], "farmer")
        self.assertEqual(row["party_name"], "S. Yadav")
        self.assertEqual(row["mobile"], "9876500003")

    def test_a_batch_is_dated_by_its_placement(self):
        row = self.rows("broiler_batch")[0]
        self.assertEqual(row["date"], (self.today - timedelta(days=30)).isoformat())

    # ---- purchase -----------------------------------------------------------

    def test_a_purchase_is_addressed_to_its_supplier(self):
        row = self.rows("purchase_invoice")[0]
        self.assertEqual(row["party_type"], "supplier")
        self.assertEqual(row["party_name"], "Balaji Feeds")
        self.assertEqual(row["context"]["Amount"], "31,000.00")

    # ---- the date window ----------------------------------------------------

    def test_the_window_narrows_on_each_source_s_own_date_field(self):
        """A batch is dated by placement and a payment line by its voucher's
        day, so a single hard-coded "date" would filter one of them wrongly."""
        old = self.today - timedelta(days=15)
        self.assertEqual(len(self.rows("broiler_batch", from_date=old.isoformat())), 0)
        self.assertEqual(len(self.rows("bird_sale", from_date=old.isoformat())), 1)

    def test_a_party_filter_narrows_to_that_party(self):
        from sales.models import Customer

        other = Customer.objects.create(name="Other Traders", mobile="9876500009")
        self.assertEqual(len(self.rows("bird_sale", party_id=self.customer.id)), 1)
        self.assertEqual(len(self.rows("bird_sale", party_id=other.id)), 0)

    # ---- reminders come from the balance report, not fresh arithmetic -------

    def test_a_payment_reminder_agrees_with_the_customer_balance_report(self):
        from sales.views import _customer_balance_row

        rows = self.rows("customer_due")
        owed = _customer_balance_row(self.customer, None, None, self.today)["debit"]
        if not owed:
            return self.assertEqual(rows, [])
        self.assertEqual(rows[0]["context"]["Outstanding"], f"{owed:,.2f}")

    def test_a_party_owing_nothing_is_not_reminded(self):
        from sales.models import Customer

        Customer.objects.create(name="Settled Traders", mobile="9876500008")
        names = [r["party_name"] for r in self.rows("customer_due")]
        self.assertNotIn("Settled Traders", names)


class PartyChoiceTests(TestCase):
    def test_the_page_can_offer_a_list_for_every_party_type(self):
        """A source declaring a party type with no list behind it would render
        an empty dropdown that filters nothing."""
        choices = party_choices(None)
        for key in PARTY_TYPES:
            self.assertIn(key, choices)

    def test_an_employee_with_no_name_is_still_identifiable(self):
        from hr.models import Employee

        Employee.objects.create(full_name="")
        labels = [name for _, name in party_choices(None)["employee"]]
        self.assertTrue(all(str(label).strip() for label in labels))


class TransactionPageTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("smsmgr", password="pw12345!")
        self.client.force_login(self.user)

    def test_the_module_dropdown_offers_every_source(self):
        html = self.client.get(reverse("sms_transaction")).content.decode()
        for src in DOC_SOURCES.values():
            self.assertIn(src["label"], html)

    def test_the_page_carries_a_dropdown_for_every_party_type(self):
        html = self.client.get(reverse("sms_transaction")).content.decode()
        for key in PARTY_TYPES:
            self.assertIn(f'id="party-{key}"', html)

    def test_an_unknown_module_is_refused_rather_than_ignored(self):
        response = self.client.get(reverse("sms_transaction_source"),
                                   {"module": "not_a_module"})
        self.assertEqual(response.status_code, 400)

    def test_every_source_answers_the_grid_without_erroring(self):
        """Each source touches a different app's models; a wrong field name
        only shows up when the source is actually run."""
        for key in DOC_SOURCES:
            with self.subTest(module=key):
                response = self.client.get(reverse("sms_transaction_source"),
                                           {"module": key})
                self.assertEqual(response.status_code, 200)
                self.assertIn("rows", response.json())

    def test_all_modules_together_stamp_each_row_with_its_real_source(self):
        """The grid sends against r["module"], so a row from the combined view
        has to name its own source rather than the literal "All"."""
        response = self.client.get(reverse("sms_transaction_source"), {"module": ""})
        self.assertEqual(response.status_code, 200)
        for row in response.json()["rows"]:
            self.assertIn(row["module"], DOC_SOURCES)


class UnregisteredTransactionTests(TestCase):
    """What is deliberately absent, so nobody re-derives it later.

    Three kinds of gap, and the assertion below is what stops one of them
    being filled by accident and going unnoticed:

    * ``user`` / registration and login OTP — sent by the system at the moment
      the thing happens, to one person, with no document to pick off a grid.
    * ``purchase`` / purchase_order — there is no purchase order model in this
      ERP; purchasing begins at the invoice.
    * ``hatchery`` / egg_grading, tray_set, hatch_entry, hatch_register — real
      records, but internal ones. Nobody outside the company is party to a
      tray being set, so there is no number to send them to. Give one of these
      an outside party and it belongs in the registry.
    """

    def test_the_only_transactions_without_a_source_are_the_known_two(self):
        covered = {(s["module"], s["transaction"]) for s in DOC_SOURCES.values()}
        missing = {(mod, code)
                   for mod, codes in SMS_MODULE_TRANSACTIONS.items()
                   for code, _ in codes
                   if (mod, code) not in covered}
        self.assertEqual(missing, {
            ("user", "registration"), ("user", "login_otp"),
            ("purchase", "purchase_order"),
            ("hatchery", "egg_grading"), ("hatchery", "tray_set"),
            ("hatchery", "hatch_entry"), ("hatchery", "hatch_register"),
        })
