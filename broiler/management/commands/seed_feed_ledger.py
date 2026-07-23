"""Seed raw data for the Feed Dispatch & Stock Report (Broiler > Reports)
so all three ledger event kinds are exercised: a Purchase receipt (Supplier
-> Warehouse, with freight), a fresh Warehouse -> Farm dispatch, and a fresh
Farm -> Warehouse return.

Reuses the same farm/office/feed items as seed_gc_report (falls back to
creating its own farm/office if that command hasn't been run). Idempotent —
re-running deletes the previous seed-tagged records first. Run:
  python manage.py seed_feed_ledger
"""
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from broiler.models import BroilerFarm, BroilerBatch
from inventory.models import Item, ItemCategory, Mapping, StockTransfer, Warehouse
from purchase.models import GeneralPurchase, GeneralPurchaseItem, Supplier

SEED_TAG = "SEED-FEED-LEDGER"
SEED_SUPPLIER_NAME = "Balaji Feed Suppliers"
FEED_RATE = Decimal("42")


class Command(BaseCommand):
    help = "Seed a Purchase, a Warehouse->Farm dispatch and a Farm->Warehouse return for the Feed Dispatch & Stock Report."

    @transaction.atomic
    def handle(self, *args, **options):
        farm = BroilerFarm.objects.select_related("branch").first()
        if not farm:
            raise CommandError("No BroilerFarm exists — run 'seed_gc_report' first or create a farm.")
        branch = farm.branch

        office_id = (Mapping.objects
                     .filter(type=Mapping.TYPE_SECTOR_BRANCH, to_id=branch.id)
                     .values_list("from_id", flat=True).first())
        office = Warehouse.objects.filter(id=office_id).first()
        if not office:
            raise CommandError(f"No Office is mapped to branch {branch} — map one under "
                               f"Inventory > Office Mapping first.")

        batch = BroilerBatch.objects.filter(broiler_farm=farm).order_by("-id").first()
        if not batch:
            raise CommandError("No BroilerBatch exists for this farm — run 'seed_gc_report' first.")

        feed_cat = ItemCategory.objects.filter(name__icontains="feed").first()
        if not feed_cat:
            raise CommandError("No feed ItemCategory exists (e.g. 'Broiler Feed').")
        pre_starter = Item.objects.filter(category=feed_cat, description__icontains="pre-starter").first()
        starter = Item.objects.filter(category=feed_cat, description__icontains="starter").exclude(description__icontains="pre-starter").first()
        if not (pre_starter and starter):
            raise CommandError("Pre-Starter/Starter Feed items not found — run 'seed_gc_report' first.")

        # ---- idempotency: remove previous seed-tagged records ----
        GeneralPurchaseItem.objects.filter(purchase__bill_no=SEED_TAG).delete()
        GeneralPurchase.objects.filter(bill_no=SEED_TAG).delete()
        StockTransfer.objects.filter(remarks__in=[
            f"{SEED_TAG} dispatch", f"{SEED_TAG} return",
        ]).delete()

        supplier, _ = Supplier.objects.get_or_create(
            name=SEED_SUPPLIER_NAME,
            defaults=dict(contact_type=Supplier.ContactType.SUPPLIER,
                         party_category=Supplier.PartyCategory.WHOLESALER,
                         place="Gorakhpur", mobile="9876543210"),
        )

        base_date = batch.start_date or date.today()

        # ---- 1. Purchase receipt: Supplier -> Warehouse (with freight) ----
        purchase = GeneralPurchase.objects.create(
            date=base_date + timedelta(days=2), supplier=supplier, bill_no=SEED_TAG,
            dc_no="MFEED-1180", vehicle_no="UP53AB1234",
            freight_type="Extra", freight_amount=Decimal("600"),
            remarks="Feed purchase (seed)",
        )
        GeneralPurchaseItem.objects.create(
            purchase=purchase, item=starter, unit="Kg", farm_warehouse=office,
            sent_qty=Decimal("1000"), rcv_qty=Decimal("1000"), free_qty=Decimal("0"),
            rate=FEED_RATE, discount_percent=Decimal("0"), discount_amount=Decimal("0"),
            gst_percent=Decimal("0"),
        )

        # ---- 2. Fresh Warehouse -> Farm dispatch ----
        StockTransfer.objects.create(
            date=base_date + timedelta(days=4), item=pre_starter, quantity=Decimal("250"),
            rate=FEED_RATE, purchase_rate=FEED_RATE,
            from_location_type="warehouse", from_warehouse=office,
            to_location_type="farm", to_farm=farm, to_batch=batch,
            dc_no="DC-FD-9001", vehicle_no="UP53CD5678",
            remarks=f"{SEED_TAG} dispatch",
        )

        # ---- 3. Fresh Farm -> Warehouse return ----
        StockTransfer.objects.create(
            date=base_date + timedelta(days=6), item=starter, quantity=Decimal("60"),
            rate=FEED_RATE, purchase_rate=FEED_RATE,
            from_location_type="farm", from_farm=farm, from_batch=batch,
            to_location_type="warehouse", to_warehouse=office,
            dc_no="DC-RET-9002", vehicle_no="UP53CD5678",
            remarks=f"{SEED_TAG} return",
        )

        self.stdout.write(self.style.SUCCESS(
            f"Seeded feed ledger raw data on {office.name} / {farm.farm_name}:\n"
            f"  Purchase   : {purchase.purchase_no} — {starter.description} 1000kg @ {FEED_RATE}, freight 600\n"
            f"  Dispatch   : {pre_starter.description} 250kg -> {farm.farm_name}\n"
            f"  Farm Return: {starter.description} 60kg -> {office.name}\n"
            f"  Open the report:  /feed-dispatch-stock-report/?submit=1&warehouse={office.id}"
            f"&from_date={base_date.isoformat()}&to_date={(base_date + timedelta(days=30)).isoformat()}"
        ))
