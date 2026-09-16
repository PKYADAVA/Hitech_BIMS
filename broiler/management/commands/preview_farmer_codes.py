"""Show the farmer codes the migration would issue, before it issues them.

Run this on a copy of live data to check the numbering reads the way you
expect — FRM-0001 being the farmer who has been on the books longest — and to
see the farms each farmer holds beside it.

Read-only: it writes nothing, and can be run against production safely.

    python manage.py preview_farmer_codes
    python manage.py preview_farmer_codes --limit 50
    python manage.py preview_farmer_codes --disagreements

On the question of checking the order against farm codes: a farm code cannot
settle it. It is a per-branch serial (AKB-02*03* is the third farm of that
branch, not the third farm overall), so two farms at different branches carry
numbers that say nothing about which came first; farms created before the
current scheme carry codes in older formats that hold no serial at all; and a
farmer with no farm yet has no code to be checked against. What the farms *can*
offer is their own creation dates, which is what --disagreements compares.
"""
import re

from django.core.management.base import BaseCommand
from django.db.models import Count, Min

from broiler.models import BroilerFarm, Farmer

# The current scheme: <branch prefix>-<branch suffix><serial>, e.g. AKB-0203.
SERIAL_CODE = re.compile(r"^[A-Z]+-\d+$")


class Command(BaseCommand):
    help = "Preview the farmer codes the backfill would issue (writes nothing)."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=40,
                            help="How many farmers to print (default 40; 0 for all).")
        parser.add_argument("--disagreements", action="store_true",
                            help="Print only farmers whose first farm is out of step "
                                 "with the code order.")

    def handle(self, *args, **options):
        farmers = list(
            Farmer.objects.annotate(farms=Count("broiler_farms"),
                                    first_farm=Min("broiler_farms__created_at"))
            .order_by("created_at", "id")
            .values("id", "farmer_name", "farmer_code", "created_at", "farms", "first_farm"))
        if not farmers:
            self.stdout.write("No farmers on file.")
            return

        first_codes = self._first_farm_codes([f["id"] for f in farmers])

        # A farmer whose first farm predates the previous farmer's first farm is
        # "out of step" — worth a look, though not wrong on its own: a farmer can
        # be entered long before their farm is, or take over an existing one.
        out_of_step, seen = set(), None
        for farmer in farmers:
            if farmer["first_farm"]:
                if seen and farmer["first_farm"] < seen:
                    out_of_step.add(farmer["id"])
                seen = max(seen, farmer["first_farm"]) if seen else farmer["first_farm"]

        shown = [f for f in farmers if f["id"] in out_of_step] if options["disagreements"] else farmers
        limit = options["limit"] or len(shown)

        self.stdout.write(f"{'WOULD BE':<10} {'CURRENT':<10} {'FARMER':<28} "
                          f"{'ON BOOKS SINCE':<17} {'FARMS':>5}  FIRST FARM")
        self.stdout.write("-" * 104)
        for serial, farmer in enumerate(farmers, start=1):
            if farmer not in shown:
                continue
            if serial > limit and not options["disagreements"]:
                break
            code = first_codes.get(farmer["id"], "")
            note = " (older code format)" if code and not SERIAL_CODE.match(code) else ""
            mark = " <-- out of step" if farmer["id"] in out_of_step else ""
            self.stdout.write(
                f"FRM-{serial:04d}   {farmer['farmer_code'] or '-':<10} "
                f"{(farmer['farmer_name'] or '')[:27]:<28} "
                f"{farmer['created_at']:%Y-%m-%d %H:%M}  {farmer['farms']:>5}  "
                f"{code or '-'}{note}{mark}")

        self._summary(farmers, first_codes, out_of_step)

    def _first_farm_codes(self, farmer_ids):
        """Each farmer's earliest farm, by the farm's own creation date."""
        codes = {}
        for farm in (BroilerFarm.objects.filter(farmer_id__in=farmer_ids)
                     .order_by("farmer_id", "created_at", "id")
                     .values("farmer_id", "farm_code")):
            codes.setdefault(farm["farmer_id"], farm["farm_code"])
        return codes

    def _summary(self, farmers, first_codes, out_of_step):
        legacy = [c for c in first_codes.values() if c and not SERIAL_CODE.match(c)]
        no_farms = [f for f in farmers if not f["farms"]]
        self.stdout.write("")
        self.stdout.write(f"{len(farmers)} farmers; FRM-0001 would go to "
                          f"{farmers[0]['farmer_name']} ({farmers[0]['created_at']:%Y-%m-%d}).")
        self.stdout.write(f"{len(no_farms)} have no farm, so no farm code can vouch for their place.")
        self.stdout.write(f"{len(legacy)} first-farm codes are in an older format with no serial to read.")
        self.stdout.write(f"{len(out_of_step)} farmers were added before someone whose farm is older.")
        if out_of_step:
            self.stdout.write(self.style.WARNING(
                "Out of step is not by itself wrong — a farmer can be entered long "
                "before their farm, or take over one that already existed."))
