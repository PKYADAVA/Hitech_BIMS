"""Transfer Charges: the allocation math never loses a rupee, and posting
goes through the real accounting engine exactly like Petty Expense does.
"""
import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from account.coa_seed import seed_coa_templates
from account.models import (BankCashMaster, ChartOfAccount, CoATemplate,
                            CompanyProfile, FinancialYear, OrganizationCentre)
from account.services import CoAGeneratorService
from account.services.bank_cash import ledger_for_bank_cash
from broiler.models import Branch, BroilerFarm, Farmer, Region, Supervisor
from inventory.models import (ChargeType, Item, ItemCategory, Sector,
                              StockTransfer, TransferChargeAllocation,
                              TransferChargeHeader, TransferChargeLine,
                              Warehouse)
from inventory.services import transfer_charges as service

TODAY = datetime.date.today()


# --------------------------------------------------------------------------
# Pure allocation math — no database, no rounding loss.
# --------------------------------------------------------------------------

class AllocationMathTests(TestCase):
    FARMS = [
        {"farm_id": 1, "farm_name": "Tulsipur", "quantity": Decimal("150"), "stock_value": Decimal("177500")},
        {"farm_id": 2, "farm_name": "Sitapur", "quantity": Decimal("80"), "stock_value": Decimal("92000")},
        {"farm_id": 3, "farm_name": "Akbarpur", "quantity": Decimal("60"), "stock_value": Decimal("66000")},
    ]

    def test_by_quantity_matches_the_spec_example(self):
        rows = service.allocate_by_quantity(self.FARMS, Decimal("6000"))
        by_farm = {r["farm_id"]: r["allocated_amount"] for r in rows}
        self.assertEqual(by_farm[1], Decimal("3103.45"))
        self.assertEqual(by_farm[2], Decimal("1655.17"))
        # Last farm absorbs the rounding remainder rather than being rounded itself.
        self.assertEqual(sum(by_farm.values()), Decimal("6000"))

    def test_equal_split_sums_exactly_on_an_awkward_total(self):
        rows = service.allocate_equal(self.FARMS, Decimal("1000"))
        self.assertEqual(sum(r["allocated_amount"] for r in rows), Decimal("1000"))

    def test_by_stock_value_sums_exactly(self):
        rows = service.allocate_by_stock_value(self.FARMS, Decimal("9999.99"))
        self.assertEqual(sum(r["allocated_amount"] for r in rows), Decimal("9999.99"))

    def test_by_distance_falls_back_to_equal_when_no_distance_known(self):
        farms = [dict(f, distance=None) for f in self.FARMS]
        rows = service.allocate_by_distance(farms, Decimal("300"))
        self.assertEqual(sorted(r["allocated_amount"] for r in rows),
                         [Decimal("100"), Decimal("100"), Decimal("100")])

    def test_single_farm_takes_the_whole_amount(self):
        rows = service.allocate_by_quantity(self.FARMS[:1], Decimal("2500"))
        self.assertEqual(rows[0]["allocated_amount"], Decimal("2500"))

    def test_percentages_sum_to_a_hundred(self):
        rows = service.allocate_by_quantity(self.FARMS, Decimal("6000"))
        self.assertEqual(sum(r["percentage"] for r in rows), Decimal("100.00"))


# --------------------------------------------------------------------------
# End-to-end: Stock Transfer rows -> Transfer Charge -> posted voucher.
# --------------------------------------------------------------------------

class TransferChargePostingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_coa_templates()
        cls.company = CompanyProfile.get_solo()
        CoAGeneratorService(cls.company, CoATemplate.objects.get(industry="Poultry")).generate()

        start = datetime.date(TODAY.year if TODAY.month >= 4 else TODAY.year - 1, 4, 1)
        FinancialYear.objects.create(
            start_date=start, end_date=start.replace(year=start.year + 1) - datetime.timedelta(days=1),
            is_active=True, state="Open")

        Sector.objects.get_or_create(code=OrganizationCentre.CENTRE_TYPE_BRANCH,
                                     defaults={"name": "Branch Office"})

        cls.region = Region.objects.create(description="East")
        cls.branch = Branch.objects.create(branch_name="Akbarpur", region=cls.region, prefix="AKB")
        cls.supervisor = Supervisor.objects.create(branch=cls.branch, name="R. Singh")
        cls.farmer = Farmer.objects.create(farmer_name="S. Yadav")
        cls.farm1 = BroilerFarm.objects.create(
            branch=cls.branch, supervisor=cls.supervisor, farmer=cls.farmer,
            region="East", line="L1", farm_name="Tulsipur")
        cls.farm2 = BroilerFarm.objects.create(
            branch=cls.branch, supervisor=cls.supervisor, farmer=cls.farmer,
            region="East", line="L1", farm_name="Sitapur")

        cls.warehouse = Warehouse.objects.create(name="Akbarpur Main Store")
        cls.item = Item.objects.create(
            description="Finisher Feed", category=ItemCategory.objects.create(name="Feed"),
            valuation_method="Weighted Average", standard_cost_per_unit=42,
            usage="Produced", source="Purchased", type="Raw Material", item_account="Expense")

        cls.cash = BankCashMaster.objects.create(name="Farm Cash Box", is_cash=True)
        cls.cash_ledger = ledger_for_bank_cash(cls.cash)

        cls.transport_ledger = ChartOfAccount.objects.filter(
            company=cls.company, account_type__name="Expense", is_postable=True, is_group=False
        ).order_by("code").first()
        cls.transport = ChargeType.objects.get(name="Transport")
        cls.transport.expense_ledger = cls.transport_ledger
        cls.transport.save(update_fields=["expense_ledger"])
        cls.unloading = ChargeType.objects.get(name="Unloading")
        # Deliberately left unmapped — the "mapping not configured" test needs it.

        cls.user = get_user_model().objects.create_superuser(
            username="tctester", password="x", email="tc@example.com")

        # One DC, two farms, 150 and 80 units.
        cls.t1 = StockTransfer.objects.create(
            dc_no="DC-TEST-1", date=TODAY, item=cls.item, quantity=Decimal("150"), rate=Decimal("42"),
            from_location_type="warehouse", from_warehouse=cls.warehouse,
            to_location_type="farm", to_farm=cls.farm1)
        cls.t2 = StockTransfer.objects.create(
            dc_no="DC-TEST-1", date=TODAY, item=cls.item, quantity=Decimal("80"), rate=Decimal("42"),
            from_location_type="warehouse", from_warehouse=cls.warehouse,
            to_location_type="farm", to_farm=cls.farm2)

    def make_header(self):
        header = TransferChargeHeader.objects.create(
            company=self.company, charge_date=TODAY, dc_no="DC-TEST-1", paid_from=self.cash)
        header.stock_transfers.set([self.t1, self.t2])
        return header

    def test_destination_farms_resolved_from_the_linked_transfers(self):
        header = self.make_header()
        summary = service.transfer_summary(header.stock_transfers.all())
        self.assertEqual(summary["farm_count"], 2)
        self.assertEqual(summary["total_quantity"], Decimal("230"))
        self.assertEqual(summary["total_stock_value"], Decimal("150") * 42 + Decimal("80") * 42)

    def test_common_by_quantity_allocates_without_rounding_loss(self):
        header = self.make_header()
        TransferChargeLine.objects.create(
            header=header, charge_type=self.transport, charge_scope=TransferChargeLine.SCOPE_COMMON,
            total_amount=Decimal("1000"), allocation_method=TransferChargeLine.METHOD_QUANTITY)
        service.recompute_allocations(header)
        allocs = TransferChargeAllocation.objects.filter(line__header=header)
        self.assertEqual(allocs.count(), 2)
        self.assertEqual(sum(a.allocated_amount for a in allocs), Decimal("1000"))

    def test_farm_wise_line_is_not_touched_by_recompute(self):
        header = self.make_header()
        line = TransferChargeLine.objects.create(
            header=header, charge_type=self.unloading, charge_scope=TransferChargeLine.SCOPE_FARM_WISE)
        TransferChargeAllocation.objects.create(
            line=line, destination_farm=self.farm1, allocated_amount=Decimal("300"))
        TransferChargeAllocation.objects.create(
            line=line, destination_farm=self.farm2, allocated_amount=Decimal("200"))
        service.recompute_allocations(header)
        self.assertEqual(line.line_total, Decimal("500"))

    def test_posting_blocked_when_charge_type_has_no_ledger_mapped(self):
        header = self.make_header()
        line = TransferChargeLine.objects.create(
            header=header, charge_type=self.unloading, charge_scope=TransferChargeLine.SCOPE_FARM_WISE)
        TransferChargeAllocation.objects.create(
            line=line, destination_farm=self.farm1, allocated_amount=Decimal("300"))
        with self.assertRaises(service.TransferChargeError) as ctx:
            service.post(header, user=self.user)
        self.assertIn("Accounting mapping is not configured", str(ctx.exception))

    def test_posting_creates_a_balanced_voucher(self):
        header = self.make_header()
        TransferChargeLine.objects.create(
            header=header, charge_type=self.transport, charge_scope=TransferChargeLine.SCOPE_COMMON,
            total_amount=Decimal("1000"), allocation_method=TransferChargeLine.METHOD_QUANTITY)
        voucher = service.post(header, user=self.user)
        header.refresh_from_db()
        self.assertEqual(header.status, TransferChargeHeader.STATUS_POSTED)
        self.assertEqual(voucher.status, "Posted")
        total_debit = sum(l.debit for l in voucher.lines.all())
        total_credit = sum(l.credit for l in voucher.lines.all())
        self.assertEqual(total_debit, total_credit)
        self.assertEqual(total_debit, Decimal("1000"))

    def test_cannot_post_twice(self):
        header = self.make_header()
        TransferChargeLine.objects.create(
            header=header, charge_type=self.transport, charge_scope=TransferChargeLine.SCOPE_COMMON,
            total_amount=Decimal("500"), allocation_method=TransferChargeLine.METHOD_EQUAL)
        service.post(header, user=self.user)
        header.refresh_from_db()
        with self.assertRaises(service.TransferChargeError):
            service.post(header, user=self.user)

    def test_cancel_reverses_through_the_journal_engine(self):
        header = self.make_header()
        TransferChargeLine.objects.create(
            header=header, charge_type=self.transport, charge_scope=TransferChargeLine.SCOPE_COMMON,
            total_amount=Decimal("500"), allocation_method=TransferChargeLine.METHOD_EQUAL)
        service.post(header, user=self.user)
        header.refresh_from_db()
        service.cancel(header, user=self.user, reason="test")
        header.refresh_from_db()
        self.assertEqual(header.status, TransferChargeHeader.STATUS_CANCELLED)
        self.assertEqual(header.voucher.status, "Cancelled")

    def test_validate_catches_unbalanced_common_allocation(self):
        header = self.make_header()
        line = TransferChargeLine.objects.create(
            header=header, charge_type=self.transport, charge_scope=TransferChargeLine.SCOPE_COMMON,
            total_amount=Decimal("1000"), allocation_method=TransferChargeLine.METHOD_MANUAL)
        TransferChargeAllocation.objects.create(
            line=line, destination_farm=self.farm1, allocated_amount=Decimal("400"))
        problems = service.validate(header)
        self.assertTrue(any("does not equal" in p for p in problems))
