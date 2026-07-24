"""Seed foundational dummy data for the Hatchery module.

Creates the hatchery masters (hatcheries with their setter/hatcher machines,
expense types and a few expense entries) and complete hatch-register batches:
each HatchSetting carries its egg-intake rows, hatcher candling/output rows and
customer sales lines, with quantities that reconcile (received - breakage/crack
= set eggs; graded output -> saleable chicks -> chicks sold).

Self-contained — creates no account/inventory/purchase/sales records, so it
runs on an empty database. The account-linked transactions (Egg Purchase, Egg
Grading, Tray Setting, Hatch Entry, Delivery Challan, Chick Sale) are
intentionally left out; seed those once suppliers/warehouses/items exist.

Idempotent — keyed on natural unique fields; each hatch setting's child rows are
rebuilt on re-run so nothing duplicates. Run:
  python manage.py seed_hatchery_dummy
"""
from datetime import date, time, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.timezone import now

from hatchery_master.models import (
    Hatchery, Setter, Hatcher, ExpenseType, HatcheryExpense,
)
from hatchery.models import (
    HatchSetting, HatchEggIntake, HatchHatcherOutput, HatchSalesLine,
)

# hatchery_name, operation_type, owner, state, contact, [setter_nos], [hatcher_nos]
HATCHERIES = [
    ("Hitech Hatchery Unit 1", "own", "Hitech Farms Pvt Ltd", "Uttar Pradesh",
     "9876500101", ["S-01", "S-02", "S-03", "S-04"], ["H-01", "H-02"]),
    ("Balaji Hatchery", "contract", "Balaji Agro", "Bihar",
     "9876500102", ["S-01", "S-02"], ["H-01"]),
    ("Sunrise Hatchery", "lease", "Sunrise Poultry", "Uttar Pradesh",
     "9876500103", ["S-01", "S-02", "S-03"], ["H-01", "H-02"]),
]

SETTER_CAPACITY = 19200      # eggs per setter machine
HATCHER_CAPACITY = 9600      # eggs per hatcher machine

EXPENSE_TYPES = ["Feed", "Medicine", "Labor", "Electricity", "Fuel / Diesel", "Packing"]

# Hatch-register batches. Percentages drive a reconciled egg -> chick breakdown.
# setting_no, hatchery index, supplier_name, received, breakage, crack,
#   hatch_pct, [(customer, chicks_sold, rate, payment_status)]
SETTINGS = [
    ("HS-DUMMY-01", 0, "Balaji Breeder Farm", 20160, 190, 130, 0.85, [
        ("Anand Poultry Traders", 6120, "31.00", "paid"),
        ("Krishna Chick Center", 5100, "30.50", "partial"),
        ("Vishnu Broiler Farm", 4080, "31.50", "unpaid"),
    ]),
    ("HS-DUMMY-02", 0, "Suguna Breeder Unit", 19200, 150, 110, 0.83, [
        ("Anand Poultry Traders", 5100, "32.00", "paid"),
        ("Sri Sai Poultry", 5100, "31.00", "partial"),
    ]),
    ("HS-DUMMY-03", 2, "Venkateshwara Hatcheries", 14400, 120, 90, 0.86, [
        ("Krishna Chick Center", 4080, "30.00", "paid"),
        ("Lakshmi Traders", 3060, "30.50", "unpaid"),
    ]),
    ("HS-DUMMY-04", 1, "Balaji Breeder Farm", 9600, 80, 70, 0.84, [
        ("Ganga Poultry Traders", 4080, "31.00", "partial"),
    ]),
]


def _r(value):
    """Round to nearest int, half up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def split(total, parts):
    """Split ``total`` into ``parts`` near-equal integers summing exactly to it."""
    base = total // parts
    out = [base] * parts
    for i in range(total - base * parts):
        out[i] += 1
    return out


class Command(BaseCommand):
    help = "Seed foundational dummy data for the Hatchery module (masters + hatch register)."

    @transaction.atomic
    def handle(self, *args, **options):
        # ---- Hatcheries + machines ----
        hatcheries = []
        for name, op_type, owner, state, contact, setters, hatchers in HATCHERIES:
            hatchery, _ = Hatchery.objects.get_or_create(
                hatchery_name=name,
                defaults=dict(operation_type=op_type, owner_name=owner, state=state,
                              contact=contact, email=f"{name.split()[0].lower()}@example.com",
                              agreement_months=24),
            )
            hatcheries.append(hatchery)
            for sno in setters:
                Setter.objects.get_or_create(
                    hatchery=hatchery, setter_no=sno,
                    defaults=dict(capacity=SETTER_CAPACITY),
                )
            for hno in hatchers:
                Hatcher.objects.get_or_create(
                    hatchery=hatchery, hatcher_no=hno,
                    defaults=dict(capacity=HATCHER_CAPACITY),
                )

        # ---- Expense types ----
        expense_types = {name: ExpenseType.objects.get_or_create(name=name)[0]
                         for name in EXPENSE_TYPES}

        # ---- A few expense entries per hatchery (deterministic -> idempotent) ----
        exp_base = now().date() - timedelta(days=20)
        exp_plan = [
            ("Feed", "eggs", "18500.00"), ("Labor", "eggs", "12000.00"),
            ("Electricity", "eggs", "8400.00"), ("Medicine", "chicks", "5600.00"),
            ("Packing", "chicks", "3200.00"), ("Fuel / Diesel", "eggs", "4100.00"),
        ]
        expense_count = 0
        for hatchery in hatcheries:
            for i, (etype, stage, amount) in enumerate(exp_plan):
                _, created = HatcheryExpense.objects.get_or_create(
                    hatchery=hatchery, date=exp_base + timedelta(days=i),
                    expense_type=expense_types[etype], stage=stage,
                    defaults=dict(amount=Decimal(amount)),
                )
                expense_count += int(created)

        # ---- Hatch-register batches ----
        set_base = now().date() - timedelta(days=25)
        register_count = 0
        for offset, (setting_no, h_idx, supplier, received, breakage, crack,
                     hatch_pct, customers) in enumerate(SETTINGS):
            hatchery = hatcheries[h_idx]
            setting_qty = received - breakage - crack

            received_date = set_base + timedelta(days=offset * 3)
            setting_date = received_date + timedelta(days=1)
            transfer_date = setting_date + timedelta(days=18)
            hatch_date = setting_date + timedelta(days=21)

            setter_nos = list(hatchery.setters.values_list("setter_no", flat=True))
            hatcher_nos = list(hatchery.hatchers.values_list("hatcher_no", flat=True))

            hs, _ = HatchSetting.objects.get_or_create(
                setting_no=setting_no,
                defaults=dict(
                    supplier_name=supplier,
                    primary_machine_nos=",".join(setter_nos),
                    avg_egg_weight="EGG WT 55-58 GM",
                    received_date=received_date, received_time=time(7, 30),
                    setting_date=setting_date, transfer_date=transfer_date,
                    hatch_date=hatch_date, push_time=time(6, 0),
                    received_qty=received, breakage_qty=breakage, crack_qty=crack,
                    setting_qty=setting_qty,
                    setter_temperature="99F", setter_humidity="60%",
                    hatcher_temperature="98.5F", hatcher_humidity="70%",
                    avg_chick_weight="CHICKS WT 38-40 GM",
                    medicine_vaccine="Marek's + ND-IB spray",
                    packing_boxes_used=_r(setting_qty * hatch_pct / 100),
                    prepared_by="Operator Ravi", verified_by="Manager Anil",
                    remarks="Seed hatch register",
                ),
            )
            # keep header quantities in sync if it already existed
            HatchSetting.objects.filter(pk=hs.pk).update(
                received_qty=received, breakage_qty=breakage,
                crack_qty=crack, setting_qty=setting_qty)

            # ---- rebuild child rows for a clean, reconciled series ----
            hs.egg_intakes.all().delete()
            hs.hatcher_outputs.all().delete()
            hs.sales_lines.all().delete()

            # Egg intake: distribute set eggs across this hatchery's setters.
            n_setters = min(len(setter_nos), 3) or 1
            for sno, eggs in zip(setter_nos, split(setting_qty, n_setters)):
                if eggs <= 0:
                    continue
                HatchEggIntake.objects.create(
                    hatch_setting=hs, sub_lot_flock=f"{supplier[:6]}",
                    setter_no=sno, tray_size=150,
                    no_trays=_r(eggs / 150), total_eggs=eggs,
                )

            # Hatcher output: split eggs across hatchers, graded breakdown each.
            n_hatchers = len(hatcher_nos) or 1
            total_saleable = 0
            for hno, eggs in zip(hatcher_nos, split(setting_qty, n_hatchers)):
                infertile = _r(eggs * 0.08)
                early_dead = _r(eggs * 0.03)
                dead_in_shell = _r(eggs * 0.02)
                blasting = _r(eggs * 0.004)
                culls = _r(eggs * 0.006)
                saleable = _r(eggs * hatch_pct)
                # keep it internally consistent: saleable can't exceed what's left
                saleable = min(saleable, eggs - infertile - early_dead
                               - dead_in_shell - blasting - culls)
                total_saleable += saleable
                HatchHatcherOutput.objects.create(
                    hatch_setting=hs, hatcher_no=hno,
                    infertile_qty=infertile, early_dead_qty=early_dead,
                    blasting_qty=blasting, transfer_qty=eggs,
                    dead_in_shell_qty=dead_in_shell, culls_malf_qty=culls,
                    saleable_chicks=saleable,
                )

            # Sales lines: sell against saleable chicks (2% free-chick bonus).
            for cust, chicks_sold, rate, status in customers:
                chicks_sold = min(chicks_sold, total_saleable)
                total_saleable -= chicks_sold
                discount = Decimal("2.00")
                billed = _r(chicks_sold / (1 + discount / 100))
                free = chicks_sold - billed
                HatchSalesLine.objects.create(
                    hatch_setting=hs, trader_customer_name=cust,
                    chicks_sold=chicks_sold, discount_percent=discount,
                    free_chicks=free, billed_chicks=billed,
                    rate=Decimal(rate),
                    total_amount=(Decimal(billed) * Decimal(rate)).quantize(Decimal("0.01")),
                    payment_status=status,
                    delivery_notes="Dispatched by hatchery van",
                )
            register_count += 1

        self.stdout.write(self.style.SUCCESS(
            "Seeded hatchery dummy data:\n"
            f"  Hatcheries: {Hatchery.objects.count()} | "
            f"Setters: {Setter.objects.count()} | Hatchers: {Hatcher.objects.count()}\n"
            f"  Expense types: {ExpenseType.objects.count()} | "
            f"Expense entries: {HatcheryExpense.objects.count()} (+{expense_count} new)\n"
            f"  Hatch settings (register): {register_count} with "
            f"{HatchEggIntake.objects.count()} intake / "
            f"{HatchHatcherOutput.objects.count()} output / "
            f"{HatchSalesLine.objects.count()} sales rows\n"
        ))
