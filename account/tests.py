"""Tests for the chart-of-accounts engine: code generation, template
generation, posting rules, auto-ledgers, opening balances and the REST APIs.
"""
import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from account.coa_seed import seed_coa_templates
from account.models import (
    AccountType,
    ChartOfAccount,
    CoAGenerationLog,
    CoATemplate,
    CompanyProfile,
    FinancialYear,
)
from account.services import AccountCodeGenerator, CoAGeneratorService


class EngineTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_coa_templates()
        cls.company = CompanyProfile.get_solo()
        cls.template = CoATemplate.objects.get(industry="Poultry")
        cls.user = get_user_model().objects.create_user(
            username="tester", password="secret123", email="t@example.com"
        )

    def generate(self, **options):
        return CoAGeneratorService(
            self.company, self.template, user=self.user, options=options or None
        ).generate()


class AccountTypeTests(EngineTestCase):
    def test_system_types_cannot_be_deleted(self):
        asset = AccountType.objects.get(code="ASSET")
        with self.assertRaises(ValidationError):
            asset.delete()

    def test_system_types_cannot_be_renamed(self):
        asset = AccountType.objects.get(code="ASSET")
        asset.name = "Something Else"
        with self.assertRaises(ValidationError):
            asset.full_clean()


class CodeGeneratorTests(EngineTestCase):
    def test_hierarchical_codes(self):
        self.generate()
        assets = ChartOfAccount.objects.get(company=self.company, system_role="ASSETS_ROOT")
        cash = ChartOfAccount.objects.get(company=self.company, system_role="CASH")
        self.assertEqual(assets.code, "100000")
        self.assertEqual(assets.level, 0)
        self.assertTrue(cash.path.startswith("100000/"))

        codegen = AccountCodeGenerator(self.company)
        # A new leaf under Cash continues the +1 sequence.
        next_leaf = codegen.next_code(parent=cash)
        self.assertNotIn(
            next_leaf,
            ChartOfAccount.objects.filter(company=self.company).values_list("code", flat=True),
        )
        self.assertTrue(next_leaf.startswith("111"))

    def test_codes_never_duplicate(self):
        self.generate()
        ar = ChartOfAccount.objects.get(company=self.company, system_role="ACCOUNTS_RECEIVABLE")
        codegen = AccountCodeGenerator(self.company)
        seen = set()
        for _ in range(5):
            code = codegen.next_code(parent=ar)
            self.assertNotIn(code, seen)
            seen.add(code)
            ChartOfAccount.objects.create(
                company=self.company, parent=ar, code=code, description=f"L{code}",
                account_type=ar.account_type,
            )


class GeneratorTests(EngineTestCase):
    def test_generation_creates_hierarchy_and_logs(self):
        log = self.generate()
        self.assertEqual(log.status, "Success")
        self.assertGreater(
            ChartOfAccount.objects.filter(company=self.company).count(), 100
        )
        # Poultry specifics landed
        self.assertTrue(
            ChartOfAccount.objects.filter(company=self.company, description="Broiler Sales").exists()
        )
        # GST engine
        for role in ("GST_INPUT_CGST", "GST_OUTPUT_IGST", "GST_PAYABLE", "ROUND_OFF"):
            self.assertTrue(
                ChartOfAccount.objects.filter(company=self.company, system_role=role).exists(),
                f"missing {role}",
            )
        # Fixed assets: cost + accumulated dep + dep expense (but not for Land)
        self.assertTrue(ChartOfAccount.objects.filter(company=self.company, system_role="FA_MACHINERY_ACCUM_DEP").exists())
        self.assertFalse(ChartOfAccount.objects.filter(company=self.company, system_role="FA_LAND_ACCUM_DEP").exists())

    def test_generation_is_idempotent(self):
        self.generate()
        count = ChartOfAccount.objects.filter(company=self.company).count()
        log2 = self.generate()
        self.assertEqual(ChartOfAccount.objects.filter(company=self.company).count(), count)
        created = sum(v["created"] for v in log2.summary.values() if isinstance(v, dict))
        self.assertEqual(created, 0)

    def test_failed_generation_rolls_back(self):
        template = CoATemplate.objects.get(industry="General")
        service = CoAGeneratorService(self.company, template, options={"with_tax": False})
        original = service._run

        def boom():
            original()
            raise RuntimeError("forced failure")

        service._run = boom
        before = ChartOfAccount.objects.filter(company=self.company).count()
        with self.assertRaises(RuntimeError):
            service.generate()
        self.assertEqual(ChartOfAccount.objects.filter(company=self.company).count(), before)
        self.assertEqual(CoAGenerationLog.objects.latest("started_at").status, "Failed")

    def test_posting_rules(self):
        self.generate()
        group = ChartOfAccount.objects.get(company=self.company, system_role="CURRENT_ASSETS")
        self.assertTrue(group.is_group)
        self.assertFalse(group.is_postable)
        leaf = ChartOfAccount.objects.get(company=self.company, system_role="CASH_IN_HAND")
        self.assertTrue(leaf.is_postable)
        bad = ChartOfAccount(
            company=self.company, code="999999", description="X",
            is_group=True, is_postable=True, type="Asset",
        )
        with self.assertRaises(ValidationError):
            bad.clean()


class AutoLedgerTests(EngineTestCase):
    def test_customer_creates_receivable_ledger(self):
        from sales.models import Customer

        self.generate()
        ar = ChartOfAccount.objects.get(company=self.company, system_role="ACCOUNTS_RECEIVABLE")
        customer = Customer.objects.create(name="ABC Poultry", address="x", mobile="9990001112")
        ledger = ChartOfAccount.objects.get(
            company=self.company, parent=ar, description="ABC Poultry"
        )
        self.assertTrue(ledger.is_postable)
        self.assertEqual(ledger.source, customer)
        # Renames propagate, no duplicate is created.
        customer.name = "ABC Poultry Pvt Ltd"
        customer.save()
        ledger.refresh_from_db()
        self.assertEqual(ledger.description, "ABC Poultry Pvt Ltd")
        self.assertEqual(ChartOfAccount.objects.filter(company=self.company, parent=ar).count(), 1)

    def test_employee_gets_payable_and_advance_ledgers(self):
        from hr.models import Employee

        self.generate()
        Employee.objects.create(full_name="Ravi Kumar")
        self.assertTrue(
            ChartOfAccount.objects.filter(
                company=self.company, parent__system_role="SALARY_PAYABLE", description="Ravi Kumar"
            ).exists()
        )
        self.assertTrue(
            ChartOfAccount.objects.filter(
                company=self.company, parent__system_role="EMPLOYEE_ADVANCE", description="Ravi Kumar"
            ).exists()
        )

    def test_no_coa_no_crash(self):
        from sales.models import Customer

        # No generation has run; creating a customer must not fail.
        customer = Customer.objects.create(name="Early Bird", address="x", mobile="9990001113")
        self.assertIsNotNone(customer.pk)


class JournalTests(EngineTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        import datetime
        cls.fy = FinancialYear.objects.create(
            start_date=datetime.date(2026, 4, 1),
            end_date=datetime.date(2027, 3, 31),
            is_active=True,
        )

    def setUp(self):
        self.generate()
        self.cash = ChartOfAccount.objects.get(company=self.company, system_role="CASH_IN_HAND")
        self.sales_group = ChartOfAccount.objects.get(company=self.company, system_role="SALES")
        self.broiler_sales = ChartOfAccount.objects.get(company=self.company, description="Broiler Sales")

    def make_voucher(self, post=True, amount="1000", date="2026-05-01", **kwargs):
        from account.services import journal
        return journal.create_voucher(
            company=self.company,
            date=date,
            lines_data=[
                {"account": self.cash.id, "debit": amount, "credit": 0, "narration": "cash received"},
                {"account": self.broiler_sales.id, "debit": 0, "credit": amount},
            ],
            user=self.user,
            post=post,
            **kwargs,
        )

    def test_posting_assigns_sequential_numbers(self):
        v1 = self.make_voucher()
        v2 = self.make_voucher()
        self.assertEqual(v1.voucher_no, "JV/2026-27/0001")
        self.assertEqual(v2.voucher_no, "JV/2026-27/0002")
        self.assertEqual(v1.status, "Posted")

    def test_unbalanced_voucher_rejected(self):
        from account.services import journal
        with self.assertRaises(ValidationError):
            journal.create_voucher(
                company=self.company, date="2026-05-01",
                lines_data=[
                    {"account": self.cash.id, "debit": "100", "credit": 0},
                    {"account": self.broiler_sales.id, "debit": 0, "credit": "90"},
                ],
            )

    def test_group_account_rejected(self):
        from account.services import journal
        with self.assertRaises(ValidationError):
            journal.create_voucher(
                company=self.company, date="2026-05-01",
                lines_data=[
                    {"account": self.sales_group.id, "debit": "100", "credit": 0},
                    {"account": self.cash.id, "debit": 0, "credit": "100"},
                ],
            )

    def test_locked_year_blocks_posting_and_cancelling(self):
        from account.services import journal
        voucher = self.make_voucher(post=False)
        self.fy.state = "Locked"
        self.fy.save()
        with self.assertRaises(ValidationError):
            journal.post_voucher(voucher, user=self.user)
        self.fy.state = "Open"
        self.fy.save()
        journal.post_voucher(voucher, user=self.user)
        self.fy.state = "Locked"
        self.fy.save()
        with self.assertRaises(ValidationError):
            journal.cancel_voucher(voucher, user=self.user, reason="x")

    def test_posted_voucher_is_immutable_but_cancellable(self):
        from account.services import journal
        voucher = self.make_voucher()
        with self.assertRaises(ValidationError):
            journal.update_draft(voucher, date="2026-05-02", lines_data=[])
        journal.cancel_voucher(voucher, user=self.user, reason="entered twice")
        voucher.refresh_from_db()
        self.assertEqual(voucher.status, "Cancelled")
        self.assertEqual(voucher.cancel_reason, "entered twice")
        # Cancelled vouchers drop out of balances.
        self.assertEqual(journal.account_balance(self.cash), Decimal("0"))

    def test_ledger_running_balance(self):
        from account.services import journal
        self.make_voucher(amount="1000", date="2026-05-01")
        self.make_voucher(amount="250", date="2026-05-03")
        statement = journal.account_ledger(self.cash)
        self.assertEqual(statement["opening"], Decimal("0"))
        self.assertEqual([row["balance"] for row in statement["rows"]],
                         [Decimal("1000"), Decimal("1250")])
        self.assertEqual(statement["closing"], Decimal("1250"))
        # Date-bounded ledger carries the earlier movement as opening.
        bounded = journal.account_ledger(self.cash, date_from="2026-05-02")
        self.assertEqual(bounded["opening"], Decimal("1000"))
        self.assertEqual(bounded["closing"], Decimal("1250"))

    def test_trial_balance_balances(self):
        from account.services import journal
        self.make_voucher(amount="1000")
        report = journal.trial_balance(self.company)
        self.assertEqual(report["totals"]["debit"], report["totals"]["credit"])
        self.assertEqual(report["totals"]["closing_debit"], report["totals"]["closing_credit"])
        codes = {row["code"] for row in report["rows"]}
        self.assertIn(self.cash.code, codes)

    def test_opening_balance_sync_creates_opening_voucher(self):
        self.client.login(username="tester", password="secret123")
        response = self.client.post(
            reverse("api_coa_opening_balance"),
            json.dumps({"entries": [
                {"account": self.cash.id, "opening_balance": "5000", "opening_type": "Debit"},
            ]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["opening_voucher"].startswith("OPV/2026-27/"))
        from account.services import journal
        self.assertEqual(journal.account_balance(self.cash), Decimal("5000"))
        # Re-saving replaces the voucher instead of duplicating it.
        self.client.post(
            reverse("api_coa_opening_balance"),
            json.dumps({"entries": [
                {"account": self.cash.id, "opening_balance": "6000", "opening_type": "Debit"},
            ]}),
            content_type="application/json",
        )
        from account.models import Voucher
        self.assertEqual(
            Voucher.objects.filter(company=self.company, voucher_type="Opening").count(), 1
        )
        self.assertEqual(journal.account_balance(self.cash), Decimal("6000"))

    def test_voucher_api_flow(self):
        from inventory.models import Warehouse

        self.client.login(username="tester", password="secret123")
        sector = Warehouse.objects.create(name="Akbarpur Branch")
        created = self.client.post(
            reverse("api_voucher_list"),
            json.dumps({
                "date": "2026-05-01",
                "voucher_type": "Receipt",
                "narration": "API test",
                "sector": sector.id,
                "lines": [
                    {"account": self.cash.id, "debit": "300", "credit": 0},
                    {"account": self.broiler_sales.id, "debit": 0, "credit": "300"},
                ],
            }),
            content_type="application/json",
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["sector_name"], "Akbarpur Branch")
        voucher_id = created.json()["id"]
        self.assertEqual(created.json()["status"], "Draft")

        posted = self.client.post(f"/api/vouchers/{voucher_id}/post/")
        self.assertEqual(posted.status_code, 200)
        self.assertTrue(posted.json()["voucher_no"].startswith("RV/"))

        ledger = self.client.get(f"/api/chart-of-accounts/{self.cash.id}/ledger/").json()
        self.assertEqual(ledger["closing"], {"amount": "300.00", "side": "Dr"})

        tb = self.client.get(reverse("api_trial_balance")).json()
        self.assertEqual(tb["totals"]["debit"], tb["totals"]["credit"])

    def test_narration_engine_fields_persist_and_track_manual_edit(self):
        from account.services import journal

        voucher = self.make_voucher(
            post=False, auto_narration="Being rent paid.", narration_source="AUTO",
        )
        self.assertEqual(voucher.auto_narration, "Being rent paid.")
        self.assertEqual(voucher.narration_source, "AUTO")
        self.assertIsNone(voucher.narration_edited_by)
        self.assertIsNone(voucher.narration_edited_at)

        journal.update_draft(
            voucher, date="2026-05-01", lines_data=[
                {"account": self.cash.id, "debit": "1000", "credit": 0},
                {"account": self.broiler_sales.id, "debit": 0, "credit": "1000"},
            ],
            user=self.user, narration="Rent for the Akbarpur office.",
            narration_source="MANUAL",
        )
        voucher.refresh_from_db()
        self.assertEqual(voucher.narration, "Rent for the Akbarpur office.")
        self.assertEqual(voucher.narration_source, "MANUAL")
        self.assertEqual(voucher.narration_edited_by, self.user)
        self.assertIsNotNone(voucher.narration_edited_at)
        # auto_narration is kept as the engine's own audit trail even after the override.
        self.assertEqual(voucher.auto_narration, "Being rent paid.")

    def test_narration_role_anchors_present_on_generated_coa(self):
        # These roles are what the client-side narration engine keys off to
        # recognize ledger context (Rent, Electricity, GST, ...) without
        # fragile name/keyword matching.
        for role, expected_name in [
            ("RENT_EXPENSE", "Rent"),
            ("ELECTRICITY_EXPENSE", "Electricity"),
            ("FUEL_EXPENSE", "Fuel & Diesel"),
            ("INTEREST_EXPENSE", "Interest Expense"),
            ("INTEREST_INCOME", "Interest Income"),
        ]:
            account = ChartOfAccount.objects.get(company=self.company, system_role=role)
            self.assertEqual(account.description, expected_name)
        # Freight Inward (COGS) and Freight Outward (expense) are distinct
        # ledgers and must keep distinct roles - sharing one would make the
        # generator's role-first existing-account match silently dedupe the
        # second one away during COA generation.
        inward = ChartOfAccount.objects.get(company=self.company, system_role="FREIGHT_INWARD_EXPENSE")
        outward = ChartOfAccount.objects.get(company=self.company, system_role="FREIGHT_OUTWARD_EXPENSE")
        self.assertEqual(inward.description, "Freight Inward")
        self.assertEqual(outward.description, "Freight Outward")


class NarrationSettingsTests(TestCase):
    def test_get_solo_is_a_true_singleton(self):
        from account.models import NarrationSettings

        first = NarrationSettings.get_solo()
        self.assertEqual(first.pk, 1)
        self.assertTrue(first.enabled)
        second = NarrationSettings.get_solo()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(NarrationSettings.objects.count(), 1)


class AutoPostingTests(EngineTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        import datetime
        from inventory.models import Item, ItemCategory, Warehouse

        cls.fy = FinancialYear.objects.create(
            start_date=datetime.date(2026, 4, 1),
            end_date=datetime.date(2027, 3, 31),
            is_active=True,
        )
        cls.warehouse = Warehouse.objects.create(name="Main Hatchery")
        category = ItemCategory.objects.create(name="Eggs")
        cls.item = Item.objects.create(
            item_code="HE-001", description="Hatching Eggs", category=category,
            warehouse=cls.warehouse, valuation_method="Weighted Average",
            standard_cost_per_unit=5, storage_uom="Nos", consumption_uom="Nos",
            usage="Produced", source="Purchased", type="Raw Material", item_account="Expense",
        )

    def setUp(self):
        self.generate()
        from hatchery.models import EggPurchase, EggPurchaseItem
        from purchase.models import Supplier
        from account.services.auto_posting import post_document

        self.post_document = post_document
        self.bank = ChartOfAccount.objects.filter(
            company=self.company, parent__system_role="BANK_ACCOUNTS", is_postable=True
        ).first() or ChartOfAccount.objects.get(company=self.company, system_role="PETTY_CASH")
        self.supplier = Supplier.objects.create(name="XYZ Feed")
        self.EggPurchase, self.EggPurchaseItem = EggPurchase, EggPurchaseItem

    def make_purchase(self, payment_mode="pay_later", freight="0", freight_type="Exclude", amount="10000"):
        import datetime
        doc = self.EggPurchase.objects.create(
            date=datetime.date(2026, 5, 10), supplier=self.supplier, warehouse=self.warehouse,
            payment_mode=payment_mode, pay_account=self.bank,
            freight_type=freight_type, freight_amount=Decimal(freight),
        )
        self.EggPurchaseItem.objects.create(egg_purchase=doc, item=self.item,
                                            rcv_qty=2000, amount=Decimal(amount))
        return doc

    def test_credit_purchase_posts_to_supplier_ledger(self):
        from account.models import Voucher
        from account.services import journal

        doc = self.make_purchase()
        voucher = self.post_document(doc)
        self.assertIsNotNone(voucher)
        self.assertEqual(voucher.status, "Posted")
        self.assertEqual(voucher.voucher_type, "Purchase")
        self.assertEqual(voucher.sector, self.warehouse)
        self.assertEqual(voucher.total_debit, Decimal("10000.00"))
        # Supplier sub-ledger was auto-created and credited.
        supplier_ledger = ChartOfAccount.objects.get(
            company=self.company, parent__system_role="ACCOUNTS_PAYABLE", description="XYZ Feed"
        )
        self.assertEqual(journal.account_balance(supplier_ledger), Decimal("-10000.00"))
        # Egg Purchases role account created on demand under COGS.
        eggs = ChartOfAccount.objects.get(company=self.company, system_role="EGG_PURCHASES")
        self.assertEqual(journal.account_balance(eggs), Decimal("10000.00"))
        self.assertEqual(Voucher.objects.filter(status="Posted").count(), 1)

    def test_pay_in_bill_with_separate_freight(self):
        from account.services import journal

        doc = self.make_purchase(payment_mode="pay_in_bill", freight="1500", freight_type="Exclude")
        voucher = self.post_document(doc)
        self.assertEqual(voucher.total_debit, Decimal("11500.00"))
        # Whole outflow hits the pay account: bill 10000 + freight 1500.
        self.assertEqual(journal.account_balance(self.bank), Decimal("-11500.00"))

    def test_edit_replaces_voucher_and_delete_cancels(self):
        from account.models import Voucher

        doc = self.make_purchase()
        first = self.post_document(doc)
        # Same amounts -> no new voucher.
        again = self.post_document(doc)
        self.assertEqual(first.id, again.id)
        # Changed amounts -> old voucher cancelled, new one posted.
        doc.items.all().update(amount=Decimal("12000"))
        doc.items.first().save()
        second = self.post_document(doc)
        first.refresh_from_db()
        self.assertEqual(first.status, "Cancelled")
        self.assertEqual(second.status, "Posted")
        self.assertEqual(second.total_debit, Decimal("12000.00"))
        # Deleting the document cancels its voucher via signal.
        doc.delete()
        second.refresh_from_db()
        self.assertEqual(second.status, "Cancelled")
        self.assertIn("deleted", second.cancel_reason)
        self.assertEqual(Voucher.objects.filter(status="Posted").count(), 0)

    def test_chick_sale_posts_to_customer_and_income(self):
        import datetime
        from hatchery.models import ChickSale, ChickSaleItem
        from sales.models import Customer
        from account.services import journal

        customer = Customer.objects.create(name="ABC Poultry", address="x", mobile="9955501112")
        sale = ChickSale.objects.create(
            date=datetime.date(2026, 6, 1), customer=customer, warehouse=self.warehouse,
            freight_type="Include in Bill", freight_amount=Decimal("500"),
        )
        ChickSaleItem.objects.create(sale=sale, item=self.item, total_qty=1000,
                                     net_qty=1000, sale_rate=Decimal("42"))
        sale.recalculate()
        voucher = self.post_document(sale)
        self.assertEqual(voucher.voucher_type, "Sales")
        self.assertEqual(voucher.total_debit, Decimal("42500.00"))
        ar_ledger = ChartOfAccount.objects.get(
            company=self.company, parent__system_role="ACCOUNTS_RECEIVABLE", description="ABC Poultry"
        )
        self.assertEqual(journal.account_balance(ar_ledger), Decimal("42500.00"))
        chick_sales = ChartOfAccount.objects.get(company=self.company, system_role="CHICK_SALES")
        self.assertEqual(journal.account_balance(chick_sales), Decimal("-42000.00"))


class FinancialReportsTests(EngineTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        import datetime
        cls.fy = FinancialYear.objects.create(
            start_date=datetime.date(2026, 4, 1),
            end_date=datetime.date(2027, 3, 31),
            is_active=True,
        )

    def setUp(self):
        self.generate()
        self.cash = ChartOfAccount.objects.get(company=self.company, system_role="CASH_IN_HAND")
        self.broiler_sales = ChartOfAccount.objects.get(company=self.company, description="Broiler Sales")
        self.salary = ChartOfAccount.objects.get(company=self.company, system_role="SALARY_EXPENSE")
        self.capital = ChartOfAccount.objects.get(company=self.company, system_role="CAPITAL")

    def post(self, debit_acct, credit_acct, amount, date="2026-05-01", vtype="Journal"):
        from account.services import journal
        return journal.create_voucher(
            company=self.company, date=date,
            lines_data=[
                {"account": debit_acct.id, "debit": amount, "credit": 0},
                {"account": credit_acct.id, "debit": 0, "credit": amount},
            ],
            voucher_type=vtype, post=True,
        )

    def test_profit_and_loss_totals(self):
        from account.services import journal

        self.post(self.cash, self.broiler_sales, "50000", vtype="Receipt")
        self.post(self.salary, self.cash, "20000", vtype="Payment")

        report = journal.profit_and_loss(self.company, date_to="2026-12-31")
        self.assertEqual(report["total_income"], Decimal("50000.00"))
        self.assertEqual(report["total_expense"], Decimal("20000.00"))
        self.assertEqual(report["gross_profit"], Decimal("50000.00"))
        self.assertEqual(report["net_profit"], Decimal("30000.00"))

    def test_profit_and_loss_respects_date_range(self):
        from account.services import journal

        self.post(self.cash, self.broiler_sales, "50000", date="2026-05-01", vtype="Receipt")
        self.post(self.cash, self.broiler_sales, "10000", date="2026-08-01", vtype="Receipt")

        full = journal.profit_and_loss(self.company, date_to="2026-12-31")
        self.assertEqual(full["total_income"], Decimal("60000.00"))
        scoped = journal.profit_and_loss(self.company, date_from="2026-06-01", date_to="2026-12-31")
        self.assertEqual(scoped["total_income"], Decimal("10000.00"))

    def test_balance_sheet_always_balances(self):
        from account.services import journal

        self.post(self.cash, self.capital, "100000", vtype="Receipt")
        self.post(self.cash, self.broiler_sales, "50000", vtype="Receipt")
        self.post(self.salary, self.cash, "20000", vtype="Payment")

        bs = journal.balance_sheet(self.company, date_upto="2026-12-31")
        self.assertTrue(bs["balanced"])
        self.assertEqual(bs["total_assets"], bs["total_liabilities_and_equity"])
        self.assertEqual(bs["current_earnings"], Decimal("30000.00"))

        cash_row = next(r for r in bs["assets"] if r["account_id"] == self.cash.id)
        self.assertEqual(cash_row["amount"], Decimal("130000.00"))

    def test_balance_sheet_as_of_date_excludes_later_entries(self):
        from account.services import journal

        self.post(self.cash, self.capital, "100000", date="2026-05-01", vtype="Receipt")
        self.post(self.cash, self.broiler_sales, "50000", date="2026-09-01", vtype="Receipt")

        early = journal.balance_sheet(self.company, date_upto="2026-06-01")
        self.assertEqual(early["total_assets"], Decimal("100000.00"))
        self.assertTrue(early["balanced"])

        later = journal.balance_sheet(self.company, date_upto="2026-12-31")
        self.assertEqual(later["total_assets"], Decimal("150000.00"))
        self.assertTrue(later["balanced"])

    def test_report_apis(self):
        self.client.login(username="tester", password="secret123")
        self.post(self.cash, self.capital, "100000", vtype="Receipt")
        self.post(self.cash, self.broiler_sales, "50000", vtype="Receipt")
        self.post(self.salary, self.cash, "20000", vtype="Payment")

        pl = self.client.get(reverse("api_profit_loss") + "?to=2026-12-31").json()
        self.assertEqual(pl["net_profit"], "30000.00")

        bs = self.client.get(reverse("api_balance_sheet") + "?to=2026-12-31").json()
        self.assertTrue(bs["balanced"])
        self.assertEqual(bs["total_assets"], bs["total_liabilities_and_equity"])


class ApiTests(EngineTestCase):
    def setUp(self):
        self.client.login(username="tester", password="secret123")

    def post_json(self, url, payload):
        return self.client.post(url, json.dumps(payload), content_type="application/json")

    def test_generate_endpoint_and_tree(self):
        response = self.post_json(reverse("api_coa_generate"), {"template": self.template.id})
        self.assertEqual(response.status_code, 201)
        tree = self.client.get(reverse("api_coa_tree")).json()
        root_codes = {node["code"] for node in tree}
        self.assertIn("100000", root_codes)
        self.assertIn("600000", root_codes)

    def test_create_update_softdelete_flow(self):
        self.post_json(reverse("api_coa_generate"), {"template": self.template.id})
        admin_group = ChartOfAccount.objects.get(company=self.company, system_role="ADMIN_EXPENSES")

        created = self.post_json(
            reverse("api_coa_list"),
            {"parent": admin_group.id, "description": "Security Charges"},
        )
        self.assertEqual(created.status_code, 201)
        body = created.json()
        self.assertTrue(body["code"])  # auto-generated
        self.assertTrue(body["is_postable"])

        updated = self.client.put(
            reverse("api_coa_detail", args=[body["id"]]),
            json.dumps({"description": "Security & Housekeeping"}),
            content_type="application/json",
        )
        self.assertEqual(updated.status_code, 200)

        deleted = self.client.delete(reverse("api_coa_detail", args=[body["id"]]))
        self.assertEqual(deleted.status_code, 200)
        self.assertFalse(ChartOfAccount.objects.filter(pk=body["id"]).exists())
        self.assertTrue(ChartOfAccount.all_objects.filter(pk=body["id"]).exists())

        # Audit trail recorded all three actions.
        audit = self.client.get(reverse("api_coa_audit")).json()
        actions = [row["action"] for row in audit["results"]]
        for action in ("create", "update", "delete"):
            self.assertIn(action, actions)

    def test_leaf_converts_to_group_and_accepts_children(self):
        self.post_json(reverse("api_coa_generate"), {"template": self.template.id})
        cash_in_hand = ChartOfAccount.objects.get(company=self.company, system_role="CASH_IN_HAND")
        self.assertFalse(cash_in_hand.is_group)

        # Creating a child under a postable leaf is rejected.
        rejected = self.post_json(
            reverse("api_coa_list"),
            {"parent": cash_in_hand.id, "description": "Front Desk Cash"},
        )
        self.assertEqual(rejected.status_code, 400)

        # Convert the leaf to a group, then the child create succeeds.
        converted = self.client.put(
            reverse("api_coa_detail", args=[cash_in_hand.id]),
            json.dumps({"is_group": True}),
            content_type="application/json",
        )
        self.assertEqual(converted.status_code, 200)
        cash_in_hand.refresh_from_db()
        self.assertTrue(cash_in_hand.is_group)
        self.assertFalse(cash_in_hand.is_postable)

        created = self.post_json(
            reverse("api_coa_list"),
            {"parent": cash_in_hand.id, "description": "Front Desk Cash"},
        )
        self.assertEqual(created.status_code, 201)
        self.assertTrue(created.json()["code"].startswith("111"))

        # And it cannot be converted back while it has children.
        back = self.client.put(
            reverse("api_coa_detail", args=[cash_in_hand.id]),
            json.dumps({"is_group": False}),
            content_type="application/json",
        )
        self.assertEqual(back.status_code, 400)

    def test_leaf_with_opening_balance_cannot_become_group(self):
        self.post_json(reverse("api_coa_generate"), {"template": self.template.id})
        petty = ChartOfAccount.objects.get(company=self.company, system_role="PETTY_CASH")
        petty.opening_balance = Decimal("500")
        petty.save()
        response = self.client.put(
            reverse("api_coa_detail", args=[petty.id]),
            json.dumps({"is_group": True}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("opening balance", response.json()["error"])

    def test_system_account_cannot_be_deleted(self):
        self.post_json(reverse("api_coa_generate"), {"template": self.template.id})
        anchor = ChartOfAccount.objects.get(company=self.company, system_role="GST_PAYABLE")
        response = self.client.delete(reverse("api_coa_detail", args=[anchor.id]))
        self.assertEqual(response.status_code, 400)

    def test_opening_balance_rebalances_equity(self):
        self.post_json(reverse("api_coa_generate"), {"template": self.template.id})
        cash = ChartOfAccount.objects.get(company=self.company, system_role="CASH_IN_HAND")
        response = self.post_json(
            reverse("api_coa_opening_balance"),
            {"entries": [{"account": cash.id, "opening_balance": "50000", "opening_type": "Debit"}]},
        )
        self.assertEqual(response.status_code, 200)
        balancer = ChartOfAccount.objects.get(company=self.company, system_role="OPENING_BALANCE_EQUITY")
        self.assertEqual(balancer.opening_balance, Decimal("50000"))
        self.assertEqual(balancer.opening_type, "Credit")

    def test_import_template_download(self):
        csv_response = self.client.get(reverse("api_coa_import_template") + "?format=csv")
        self.assertEqual(csv_response.status_code, 200)
        self.assertIn("attachment", csv_response["Content-Disposition"])
        first_line = csv_response.content.decode().splitlines()[0]
        self.assertEqual(
            first_line,
            "code,name,type,group,parent_code,is_group,opening_balance,opening_type",
        )

        xlsx_response = self.client.get(reverse("api_coa_import_template") + "?format=xlsx")
        self.assertEqual(xlsx_response.status_code, 200)
        import io as _io
        import openpyxl as _openpyxl
        workbook = _openpyxl.load_workbook(_io.BytesIO(xlsx_response.content))
        self.assertEqual(workbook.sheetnames, ["Accounts", "Instructions"])

    def test_import_validates_before_writing(self):
        self.post_json(reverse("api_coa_generate"), {"template": self.template.id})
        before = ChartOfAccount.objects.filter(company=self.company).count()
        bad_csv = b"code,name,type,group,parent_code,is_group\n,Valid Account,Asset,,,\n,Broken,NotAType,,,\n"
        from django.core.files.uploadedfile import SimpleUploadedFile

        response = self.client.post(
            reverse("api_coa_import"),
            {"file": SimpleUploadedFile("accounts.csv", bad_csv, content_type="text/csv")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(ChartOfAccount.objects.filter(company=self.company).count(), before)

        good_csv = b"code,name,type,group,parent_code,is_group\n,Generator Fuel,Expense,,,\n"
        response = self.client.post(
            reverse("api_coa_import"),
            {"file": SimpleUploadedFile("accounts.csv", good_csv, content_type="text/csv")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            ChartOfAccount.objects.filter(company=self.company, description="Generator Fuel").exists()
        )
