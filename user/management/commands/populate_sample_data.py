from decimal import Decimal
from datetime import date

from django.core.management.base import BaseCommand

from account.models import BankCode, ChartOfAccount, CoACategory, FinancialYear, Schedule
from inventory.models import Item, ItemCategory, Warehouse
from purchase.models import CreditTerm, PurchaseOrder, PurchaseOrderLineItem, VendorGroup
from sales.models import Customer, CustomerGroup, SalesPriceMaster


class Command(BaseCommand):
    help = "Populate a small set of sample data for basic local testing"

    def handle(self, *args, **options):
        # Inventory
        category, _ = ItemCategory.objects.get_or_create(name="Broiler Feed")
        warehouse, _ = Warehouse.objects.get_or_create(name="Main Warehouse")
        item, created_item = Item.objects.get_or_create(
            item_code="ITEM-001",
            defaults={
                "description": "Balanced broiler feed",
                "category": category,
                "warehouse": warehouse,
                "valuation_method": "Weighted Average",
                "standard_cost_per_unit": Decimal("120.00"),
                "storage_uom": "Bag",
                "consumption_uom": "Bag",
                "usage": "Sales",
                "source": "Purchased",
                "type": "Finished Goods",
                "item_account": "Asset",
                "kg_per_bag": Decimal("50.00"),
                "hsn_code": "2302",
            },
        )

        # Purchase
        credit_term, _ = CreditTerm.objects.get_or_create(term="Net 30")
        vendor_group, _ = VendorGroup.objects.get_or_create(
            code="VG-001",
            defaults={
                "description": "Sample vendor group",
                "currency": "INR",
            },
        )
        purchase_order, _ = PurchaseOrder.objects.get_or_create(
            invoice="PO-1001",
            defaults={
                "date": date.today(),
                "vendor": vendor_group,
                "credit_term": credit_term,
                "pay_later_via": "Cash",
                "tcs": "No",
                "basic_amount": Decimal("1200.00"),
                "total_amount": Decimal("1200.00"),
                "grand_total": Decimal("1200.00"),
                "net_total": Decimal("1200.00"),
            },
        )
        PurchaseOrderLineItem.objects.get_or_create(
            purchase_order=purchase_order,
            defaults={
                "item_category": category,
                "item": item,
                "units": "Bag",
                "price_per_unit": Decimal("120.00"),
                "qty_sent": Decimal("10.00"),
                "qty_received": Decimal("10.00"),
                "qty_free": Decimal("0.00"),
                "type": "Regular",
                "bags_or_boxes": "10",
                "weight": Decimal("500.00"),
                "vat": Decimal("0.00"),
                "warehouse": warehouse.name,
                "flock": "F1",
                "sqft": Decimal("1000.00"),
                "sqft_per_chick": Decimal("1.00"),
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
