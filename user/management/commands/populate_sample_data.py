from decimal import Decimal
from datetime import date

from django.core.management.base import BaseCommand

from account.models import BankCode, ChartOfAccount, CoACategory, FinancialYear, Schedule
from inventory.models import Item, ItemCategory, UnitOfMeasurement, Warehouse
from purchase.models import CreditTerm, GeneralPurchase, GeneralPurchaseItem, Supplier, VendorGroup
from sales.models import Customer, CustomerGroup, SalesPriceMaster


class Command(BaseCommand):
    help = "Populate a small set of sample data for basic local testing"

    def handle(self, *args, **options):
        # Inventory
        category, _ = ItemCategory.objects.get_or_create(name="Broiler Feed")
        warehouse, _ = Warehouse.objects.get_or_create(name="Main Warehouse")
        bag_uom, _ = UnitOfMeasurement.objects.get_or_create(name="Bag")
        item, created_item = Item.objects.get_or_create(
            item_code="ITEM-001",
            defaults={
                "description": "Balanced broiler feed",
                "category": category,
                "valuation_method": "Weighted Average",
                "standard_cost_per_unit": Decimal("120.00"),
                "storage_uom": bag_uom,
                "consumption_uom": bag_uom,
                "usage": "Sales",
                "source": "Purchased",
                "type": "Finished Goods",
                "item_account": "Asset",
                "kg_per_bag": Decimal("50.00"),
                "hsn_code": "2302",
            },
        )
        item.warehouse.set([warehouse])

        # Purchase
        credit_term, _ = CreditTerm.objects.get_or_create(term="Net 30")
        vendor_group, _ = VendorGroup.objects.get_or_create(
            code="VG-001",
            defaults={
                "description": "Sample vendor group",
                "currency": "INR",
            },
        )
        supplier, _ = Supplier.objects.get_or_create(
            code="SUPP-001",
            defaults={"name": "Sample Feed Supplier", "mobile": "9876500000",
                     "contact_type": Supplier.ContactType.SUPPLIER},
        )
        general_purchase, _ = GeneralPurchase.objects.get_or_create(
            bill_no="PO-1001",
            defaults={
                "date": date.today(),
                "supplier": supplier,
                "payment_terms": "Cash",
            },
        )
        GeneralPurchaseItem.objects.get_or_create(
            purchase=general_purchase,
            item=item,
            defaults={
                "unit": "Bag",
                "rate": Decimal("120.00"),
                "sent_qty": Decimal("10.00"),
                "rcv_qty": Decimal("10.00"),
                "free_qty": Decimal("0.00"),
                "gst_percent": Decimal("0.00"),
                "farm_warehouse": warehouse,
            },
        )

        # Sales
        customer_group, _ = CustomerGroup.objects.get_or_create(
            code="CG-001",
            defaults={
                "description": "Sample customer group",
                "currency": "INR",
            },
        )
        Customer.objects.get_or_create(
            phone="9999999999",
            mobile="9999999999",
            defaults={
                "name": "Sample Customer",
                "address": "123 Demo Street",
                "place": "Bangalore",
                "contact_type": "Customer",
                "customer_group": customer_group,
                "credit_limit": Decimal("5000.00"),
                "gstin": "29ABCDE1234F1Z5",
                "state": "Karnataka",
                "note": "Sample customer for local testing",
            },
        )
        SalesPriceMaster.objects.get_or_create(
            item=item,
            defaults={
                "item_category": category,
                "price": Decimal("150.00"),
            },
        )

        # Accounting
        financial_year, _ = FinancialYear.objects.get_or_create(
            start_date=date(2025, 4, 1),
            end_date=date(2026, 3, 31),
            defaults={"is_active": True},
        )
        schedule, _ = Schedule.objects.get_or_create(
            code="SCH-001",
            defaults={"name": "Operating", "description": "Operating accounts"},
        )
        category_account, _ = CoACategory.objects.get_or_create(
            description="Operating Expenses",
            defaults={"type": "Expense"},
        )
        ChartOfAccount.objects.get_or_create(
            code="COA-001",
            defaults={
                "description": "Sample expense account",
                "type": "Expense",
                "schedule": schedule,
                "status": "Active",
            },
        )
        BankCode.objects.get_or_create(
            bank_code="BK-001",
            defaults={
                "bank_name": "Sample Bank",
                "sector": warehouse,
            },
        )

        self.stdout.write(self.style.SUCCESS("Sample data populated successfully."))
        self.stdout.write(
            self.style.SUCCESS(
                f"Created/updated sample records for inventory, purchase, sales, and accounting."
            )
        )
