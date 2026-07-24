"""Seed foundational dummy data for the Broiler module: regions, breeds
(with a sample standard curve), branches, supervisors, farmers, farms, sheds,
batches, a few diseases and ~25 days of daily entries per active batch.

Self-contained — creates no account/inventory/sales/hr records, so it runs on
an empty database. It also lays the groundwork the other broiler seeders need
(farm / supervisor / branch), so you can follow it with `seed_gc_report` and
`seed_feed_ledger` once feed/chick items and an office mapping exist.

Idempotent — keyed on natural names, so re-running updates in place rather than
duplicating. Daily entries for the seeded batches are rebuilt each run. Run:
  python manage.py seed_broiler_dummy
"""
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.timezone import now

from broiler.models import (
    Region, Breed, BreedStandard, Branch, Supervisor, Farmer,
    BroilerFarm, BroilerFarmShed, BroilerBatch, BroilerDisease, DailyEntry,
)

# --- Master data definitions -------------------------------------------------
REGIONS = ["Uttar Pradesh", "Bihar"]

BREEDS = ["COBB 500", "Ross 308", "Vencobb 400"]

# A compact standard curve (age -> body_weight g, feed_intake g, adg g, fcr,
# cum_feed g) attached to the first breed so the Breed Standard master isn't empty.
STANDARD_CURVE = [
    # age, body_weight, feed_intake, avg_daily_gain, fcr, cum_feed
    (1,    42,   13,   0,    0.000,   13),
    (7,    176,  32,   24,   1.050,   180),
    (14,   465,  70,   45,   1.180,   540),
    (21,   930,  110,  66,   1.320,   1150),
    (28,   1460, 150,  76,   1.480,   2050),
    (35,   1980, 175,  74,   1.610,   3200),
    (42,   2450, 190,  67,   1.720,   4450),
]

# branch_name, prefix, region index
BRANCHES = [
    ("Gorakhpur", "GKP", 0),
    ("Lucknow", "LKO", 0),
    ("Patna", "PAT", 1),
]

# name, phone, branch index
SUPERVISORS = [
    ("Ramesh Yadav", "9876500011", 0),
    ("Suresh Gupta", "9876500022", 0),
    ("Anil Verma", "9876500033", 1),
    ("Manoj Singh", "9876500044", 2),
]

# farmer_name, mobile_no
FARMERS = [
    ("Rajkumar Prasad", "9812000001"),
    ("Dinesh Chaudhary", "9812000002"),
    ("Santosh Mishra", "9812000003"),
    ("Vijay Kushwaha", "9812000004"),
    ("Pramod Tiwari", "9812000005"),
    ("Sunil Rai", "9812000006"),
]

# farm_name, capacity, farm_type, branch index, supervisor index, farmer index,
# state, district, area, pincode
FARMS = [
    ("Sunrise Poultry Farm", 10000, "own", 0, 0, 0, "Uttar Pradesh", "Gorakhpur", "Campierganj", "273001"),
    ("Green Valley Farm", 8000, "integration", 0, 1, 1, "Uttar Pradesh", "Gorakhpur", "Pipraich", "273152"),
    ("Sharda Broilers", 12000, "own", 1, 2, 2, "Uttar Pradesh", "Lucknow", "Bakshi Ka Talab", "226201"),
    ("Ganga Poultry", 6000, "ec_shed", 2, 3, 3, "Bihar", "Patna", "Danapur", "801503"),
    ("Maa Sharda Farm", 9000, "own", 2, 3, 4, "Bihar", "Patna", "Fatuha", "803201"),
]

DISEASES = [
    ("NCD", "Newcastle Disease", "Respiratory distress, greenish diarrhoea, drop in feed intake",
     "Supportive care + strict biosecurity; vaccinated survivors isolated"),
    ("IBD", "Gumboro (Infectious Bursal Disease)", "Ruffled feathers, whitish watery droppings, dehydration",
     "Electrolytes + vitamins in water; culled severe cases"),
    ("CRD", "Chronic Respiratory Disease", "Rales, nasal discharge, sneezing, reduced weight gain",
     "Tylosin course for 5 days; improved ventilation"),
]

# Front-loaded mortality per age-day (index 0 == age 1).
MORTALITY = [12, 9, 8, 6, 5, 4, 3, 3, 2, 2, 2, 2, 1, 1, 1,
             1, 1, 1, 1, 1, 1, 1, 1, 1, 1]
WEIGHT_G = {1: 42, 7: 176, 14: 465, 21: 930, 25: 1180}


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
    help = "Seed foundational dummy data for the Broiler module (masters + sample transactions)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", type=int, default=25,
            help="Number of daily-entry days to generate per active batch (default 25).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        days = options["days"]

        # ---- Regions ----
        regions = [Region.objects.get_or_create(description=name)[0] for name in REGIONS]

        # ---- Breeds (+ one standard curve) ----
        breeds = [Breed.objects.get_or_create(description=name)[0] for name in BREEDS]
        for age, bw, fi, adg, fcr, cum in STANDARD_CURVE:
            BreedStandard.objects.update_or_create(
                breed=breeds[0], age=age,
                defaults=dict(
                    body_weight=Decimal(str(bw)), feed_intake=Decimal(str(fi)),
                    avg_daily_gain=Decimal(str(adg)), fcr=Decimal(str(fcr)),
                    cum_feed=Decimal(str(cum)),
                ),
            )

        # ---- Branches ----
        branches = []
        for branch_name, prefix, region_idx in BRANCHES:
            branch, _ = Branch.objects.get_or_create(
                branch_name=branch_name,
                defaults=dict(region=regions[region_idx], prefix=prefix),
            )
            branches.append(branch)

        # ---- Supervisors ----
        supervisors = []
        for name, phone, branch_idx in SUPERVISORS:
            sup, _ = Supervisor.objects.get_or_create(
                branch=branches[branch_idx], name=name,
                defaults=dict(phone_no=phone,
                              email=f"{name.split()[0].lower()}@example.com",
                              address="Farm colony, near main road"),
            )
            supervisors.append(sup)

        # ---- Farmers ----
        farmers = []
        for i, (farmer_name, mobile) in enumerate(FARMERS):
            farmer, _ = Farmer.objects.get_or_create(
                farmer_name=farmer_name,
                defaults=dict(mobile_no=mobile,
                              address="Village Rampur, PO Khalilabad",
                              account_holder_name=farmer_name,
                              bank_name="State Bank of India"),
            )
            farmers.append(farmer)

        # ---- Farms + sheds + batch + entries ----
        start = now().date() - timedelta(days=days - 1)
        created_farms, created_batches, created_entries = 0, 0, 0

        for (farm_name, capacity, ftype, b_idx, s_idx, f_idx,
             state, district, area, pincode) in FARMS:
            branch = branches[b_idx]
            supervisor = supervisors[s_idx]
            farmer = farmers[f_idx]

            farm, farm_new = BroilerFarm.objects.get_or_create(
                branch=branch, farm_name=farm_name,
                defaults=dict(
                    supervisor=supervisor, farmer=farmer,
                    region=branch.region.description, line=f"{branch.prefix} Line 1",
                    farm_capacity=capacity, farm_type=ftype,
                    state=state, district=district, area=area, farm_pincode=pincode,
                    farm_address=f"{area}, {district}, {state}",
                    agreement_start_date=start - timedelta(days=30),
                    agreement_months=12,
                ),
            )
            created_farms += int(farm_new)

            # ---- two sheds per farm (place birds in the first) ----
            half = capacity // 2
            for unit, occ in ((1, min(half, 5000)), (2, 0)):
                BroilerFarmShed.objects.get_or_create(
                    farm=farm, shed_name=f"{farm_name} Shed {unit}",
                    defaults=dict(
                        shed_type="broiler", length=Decimal("300"),
                        width=Decimal("40"), capacity=half, occupied=occ,
                    ),
                )

            # ---- one active batch per farm ----
            batch, _ = BroilerBatch.objects.get_or_create(
                broiler_farm=farm, book_number=f"DUMMY-{farm.farm_code}",
                defaults=dict(
                    lot_no=f"LOT-{farm.farm_code}", breed=breeds[b_idx % len(breeds)],
                    start_date=start,
                ),
            )
            created_batches += 1

            # ---- diseases on a couple of batches ----
            if f_idx % 2 == 0:
                dcode, dname, symptoms, diagnosis = DISEASES[f_idx % len(DISEASES)]
                BroilerDisease.objects.get_or_create(
                    batch=batch, disease_code=dcode,
                    defaults=dict(disease_name=dname, symptoms=symptoms,
                                  diagnosis=diagnosis),
                )

            # ---- daily entries (rebuilt each run for a clean series) ----
            DailyEntry.objects.filter(batch=batch).delete()
            for i in range(days):
                age = i + 1
                d = start + timedelta(days=i)
                mort = MORTALITY[i] if i < len(MORTALITY) else 0
                weight_g = Decimal(str(round(interp(WEIGHT_G, age), 2)))
                DailyEntry.objects.create(
                    date=d, supervisor=supervisor, farm=farm, batch=batch,
                    age_days=age, mortality=mort, culls=1 if age % 7 == 0 else 0,
                    avg_weight_gms=weight_g,
                    remarks="Seed daily entry",
                )
                created_entries += 1

        self.stdout.write(self.style.SUCCESS(
            "Seeded broiler dummy data:\n"
            f"  Regions: {len(regions)} | Breeds: {len(breeds)} "
            f"(+{len(STANDARD_CURVE)} standard rows)\n"
            f"  Branches: {len(branches)} | Supervisors: {len(supervisors)} | "
            f"Farmers: {len(farmers)}\n"
            f"  Farms: {BroilerFarm.objects.count()} (+{created_farms} new) | "
            f"Sheds: {BroilerFarmShed.objects.count()} | "
            f"Batches: {created_batches} active\n"
            f"  Daily entries generated: {created_entries} ({days} days/batch)\n"
        ))
