"""Seed a complete broiler batch cycle so the Growing Charge Statement
report (Broiler > Reports > Batch History Report) shows meaningful data end
to end: chick placement, feed transfers-in, a feed return, ~37 days of daily
entries with mortality + phase-based feed consumption (pre-starter ->
pre-starter & starter -> starter -> starter & finisher -> finisher),
bird sales, and a matching Growing Charge Scheme for Admin Cost / Grade.

Reuses existing masters (farm, supervisor, office, customer, categories) and
is idempotent — re-running deletes the previous seed batch and its
transactions first. Run:  python manage.py seed_gc_report
"""
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from broiler.models import (
    Branch, BroilerBatch, BroilerFarm, BirdSale, DailyEntry,
    GrowingChargeScheme, GCFarmerClassification,
)
from inventory.models import (
    Item, ItemCategory, Mapping, StockTransfer, UnitOfMeasurement, Warehouse,
)
from sales.models import Customer

BOOK_NO = "SEED-GC-DEMO"          # marks the seed batch for idempotent re-runs
SEED_SCHEMA_NAME = "SEED Growing Charge"
START = date(2026, 5, 8)
DAYS = 37
PLACEMENT = 1861
CHICK_RATE = Decimal("35")
FEED_RATE = Decimal("42")

# Front-loaded mortality per age-day (index 0 == age 1).
MORTALITY = [22, 18, 15, 12, 10, 8, 6,   5, 5, 4, 4, 3, 3, 3,
             3, 2, 2, 2, 2, 2, 2,        2, 2, 1, 1, 1, 1, 1,
             1, 1, 1, 1, 1, 1, 1,        1, 1]
# Anchor points (age -> value) linearly interpolated for the days between.
WEIGHT_G = {1: 42, 7: 176, 14: 465, 21: 930, 28: 1460, 35: 1980, 37: 2120}
INTAKE_G = {1: 13, 7: 32, 14: 70, 21: 110, 28: 150, 35: 175, 37: 185}


def interp(anchors, x):
    keys = sorted(anchors)
    if x <= keys[0]:
        return float(anchors[keys[0]])
    if x >= keys[-1]:
        return float(anchors[keys[-1]])
    for a, b in zip(keys, keys[1:]):
        if a <= x <= b:
            t = (x - a) / (b - a)
            return anchors[a] + t * (anchors[b] - anchors[a])
    return float(anchors[keys[-1]])


class Command(BaseCommand):
    help = "Seed a full broiler batch cycle for the Growing Charge Statement report."

    @transaction.atomic
    def handle(self, *args, **options):
        farm = BroilerFarm.objects.select_related("branch", "supervisor").first()
        if not farm:
            raise CommandError("No BroilerFarm exists — create a farm first.")
        supervisor = farm.supervisor
        branch = farm.branch

        office_id = (Mapping.objects
                     .filter(type=Mapping.TYPE_SECTOR_BRANCH, to_id=branch.id)
                     .values_list("from_id", flat=True).first())
        office = Warehouse.objects.filter(id=office_id).first()
        if not office:
            raise CommandError(f"No Office is mapped to branch {branch} — map one under "
                               f"Inventory > Office Mapping first.")

        customer = Customer.objects.first()
        if not customer:
            raise CommandError("No Customer exists — create one for the bird sales.")

        feed_cat = ItemCategory.objects.filter(name__icontains="feed").first()
        chick_cat = ItemCategory.objects.filter(name__icontains="chick").first()
        if not (feed_cat and chick_cat):
            raise CommandError("Need a feed and a chick ItemCategory (e.g. 'Broiler Feed', "
                               "'Day Old Chicks').")
        uom = UnitOfMeasurement.objects.first()

        def ensure_feed(desc):
            item, _ = Item.objects.get_or_create(
                description=desc, category=feed_cat,
                defaults=dict(valuation_method="Weighted Average",
                              standard_cost_per_unit=FEED_RATE, storage_uom=uom,
                              consumption_uom=uom, usage="Produced", source="Purchased",
                              type="Raw Material", item_account="Expense",
                              kg_per_bag=Decimal("50")),
            )
            return item

        pre = ensure_feed("Pre-Starter Feed")
        starter = ensure_feed("Starter Feed")
        finisher = ensure_feed("Finisher Feed")
        chick_item = Item.objects.filter(category=chick_cat).first()
        if not chick_item:
            raise CommandError("No item under the chick category to place.")

        # ---- idempotency: drop the previous seed batch + its transactions ----
        old = BroilerBatch.objects.filter(broiler_farm=farm, book_number=BOOK_NO)
        for b in old:
            StockTransfer.objects.filter(to_batch=b).delete()
            StockTransfer.objects.filter(from_batch=b).delete()
            BirdSale.objects.filter(batch=b).delete()
            DailyEntry.objects.filter(batch=b).delete()
        old.delete()

        batch = BroilerBatch.objects.create(
            broiler_farm=farm, book_number=BOOK_NO, lot_no="LOT-SEED",
            start_date=START, end_date=START + timedelta(days=DAYS + 2),
        )

        # ---- Chick Placement (Warehouse -> Farm/Batch) ----
        StockTransfer.objects.create(
            date=START, item=chick_item, quantity=Decimal(PLACEMENT),
            rate=CHICK_RATE, purchase_rate=CHICK_RATE,
            chicks_ordered=Decimal(PLACEMENT), transit_mortality=0, shortage=0, culls=0,
            from_location_type="warehouse", from_warehouse=office,
            to_location_type="farm", to_farm=farm, to_batch=batch,
            dc_no="DC-CHK-001", remarks="Chick placement (seed)",
        )

        # ---- day-by-day daily entries ----
        consumed = {pre.id: Decimal("0"), starter.id: Decimal("0"), finisher.id: Decimal("0")}
        sold_by_day = {35: 640, 36: 990, 37: 80}   # ages -> birds sold that day
        opening = PLACEMENT
        for i in range(DAYS):
            age = i + 1
            d = START + timedelta(days=i)
            mort = MORTALITY[i] if i < len(MORTALITY) else 0
            weight_g = Decimal(str(round(interp(WEIGHT_G, age), 2)))
            flock_feed = Decimal(str(round(interp(INTAKE_G, age) * opening / 1000, 2)))

            # feed phase -> (feed_1, qty1, feed_2, qty2)
            if age <= 10:
                f1, q1, f2, q2 = pre, flock_feed, None, Decimal("0")
            elif age <= 12:                                   # pre-starter & starter
                f1, q1, f2, q2 = pre, (flock_feed * Decimal("0.4")).quantize(Decimal("0.01")), \
                    starter, (flock_feed * Decimal("0.6")).quantize(Decimal("0.01"))
            elif age <= 24:
                f1, q1, f2, q2 = starter, flock_feed, None, Decimal("0")
            elif age <= 26:                                   # starter & finisher
                f1, q1, f2, q2 = starter, (flock_feed * Decimal("0.4")).quantize(Decimal("0.01")), \
                    finisher, (flock_feed * Decimal("0.6")).quantize(Decimal("0.01"))
            else:
                f1, q1, f2, q2 = finisher, flock_feed, None, Decimal("0")

            consumed[f1.id] += q1
            if f2:
                consumed[f2.id] += q2

            DailyEntry.objects.create(
                date=d, supervisor=supervisor, farm=farm, batch=batch, age_days=age,
                mortality=mort, culls=0,
                feed_1=f1, feed_1_qty=q1, feed_2=f2, feed_2_qty=q2,
                avg_weight_gms=weight_g, remarks="",
            )

            # ---- bird sales on the selling days ----
            sold = sold_by_day.get(age, 0)
            if sold:
                avg_kg = (weight_g / Decimal("1000")).quantize(Decimal("0.01"))
                BirdSale.objects.create(
                    sale_type="customer", customer=customer, farm=farm, batch=batch,
                    date=d, birds=sold, net_weight=(avg_kg * sold).quantize(Decimal("0.01")),
                    rate=Decimal("101"), doc_no=f"BS-DOC-{age}",
                )
            opening = opening - mort - sold

        # ---- Feed Transfer-In (Office -> Farm/Batch), covering consumption + buffer ----
        for item in (pre, starter, finisher):
            qty = (consumed[item.id] + Decimal("40")).quantize(Decimal("0.01"))
            StockTransfer.objects.create(
                date=START + timedelta(days=1), item=item, quantity=qty,
                rate=FEED_RATE, purchase_rate=FEED_RATE,
                from_location_type="warehouse", from_warehouse=office,
                to_location_type="farm", to_farm=farm, to_batch=batch,
                dc_no=f"DC-FD-{item.item_code}", remarks="Feed transfer-in (seed)",
            )

        # ---- Feed Return (Farm/Batch -> Office) ----
        StockTransfer.objects.create(
            date=START + timedelta(days=DAYS), item=starter, quantity=Decimal("40"),
            rate=FEED_RATE, purchase_rate=FEED_RATE,
            from_location_type="farm", from_farm=farm, from_batch=batch,
            to_location_type="warehouse", to_warehouse=office,
            dc_no="DC-RET-001", remarks="Unused feed returned (seed)",
        )

        # ---- Growing Charge Scheme (wins the match: later from_date) ----
        GrowingChargeScheme.objects.filter(schema_name=SEED_SCHEMA_NAME).delete()
        scheme = GrowingChargeScheme.objects.create(
            region_id=branch.region_id, branch=branch,
            from_date=date(2026, 4, 5), to_date=date(2026, 7, 30),
            schema_name=SEED_SCHEMA_NAME,
            chick_cost=CHICK_RATE, feed_cost=FEED_RATE,
            farmer_admin_cost=Decimal("3"), management_admin_cost=Decimal("1"),
            std_production_cost=Decimal("90"), standard_gc_cost=Decimal("18"),
            minimum_gc_cost=Decimal("15"), standard_fcr=Decimal("1.65"),
            standard_mortality=Decimal("5"),
        )
        for lo, hi, grade in [(0, 85, "A"), (85, 92, "B"), (92, 100, "C"), (100, 200, "D")]:
            GCFarmerClassification.objects.create(
                scheme=scheme, production_cost_from=Decimal(lo),
                production_to=Decimal(hi), grade=grade,
            )

        total_mort = sum(MORTALITY)
        total_sold = sum(sold_by_day.values())
        self.stdout.write(self.style.SUCCESS(
            f"Seeded batch {batch.batch_name} (id={batch.id}) on {farm.farm_name}.\n"
            f"  Placed {PLACEMENT} | mortality {total_mort} | sold {total_sold} | "
            f"feed consumed {sum(consumed.values()):.0f} kg\n"
            f"  Scheme: {scheme.scheme_code} (farmer admin 3, management admin 1)\n"
            f"  Open the report:  /broiler-report/?batch={batch.id}&fetch_type=farmer"
        ))
