"""Recompute every saved farm stock figure against what the farm was sent.

Daily Entry and Medicine Consumption both stored a running stock that chained
from an opening balance of zero over their own entries, so nothing delivered to
the farm ever entered the figure: a farm with 2,337 kg of Starter Feed showed 0
and went further negative every day it was fed. What was on screen was
cumulative consumption with a minus sign.

The calculation is fixed; this rewrites the rows already saved under the old
one. It is idempotent — a second run reports nothing changed — so it is safe to
run again after a deploy, or to run with --dry-run first to see the damage
before touching anything.
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from broiler.models import DailyEntry, MedicineVaccineEntry


class Command(BaseCommand):
    help = "Rebuild stored feed and medicine stock on farms from actual receipts."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would change and write nothing.")
        parser.add_argument("--farm", type=int, default=None,
                            help="Limit to one farm id.")

    def handle(self, *args, **options):
        from broiler.views import (_recompute_medicine_stock_chain,
                                   _recompute_stock_chain)

        dry = options["dry_run"]
        farm = options["farm"]

        # Every (farm, item) pair that carries a stored balance. Both feed
        # slots, because the same item can sit in either.
        entries = DailyEntry.objects.all()
        medicines = MedicineVaccineEntry.objects.all()
        if farm:
            entries = entries.filter(farm_id=farm)
            medicines = medicines.filter(farm_id=farm)

        feed_pairs = set()
        for f, i1, i2 in entries.values_list("farm_id", "feed_1_id", "feed_2_id"):
            feed_pairs.update((f, i) for i in (i1, i2) if i)
        med_pairs = set(medicines.values_list("farm_id", "item_id"))
        med_pairs = {(f, i) for f, i in med_pairs if i}

        before = self._snapshot(entries, medicines)

        with transaction.atomic():
            for farm_id, item_id in sorted(feed_pairs):
                _recompute_stock_chain(farm_id, item_id)
            for farm_id, item_id in sorted(med_pairs):
                _recompute_medicine_stock_chain(farm_id, item_id)

            after = self._snapshot(entries, medicines)
            changed = {k: (before[k], after[k]) for k in before
                       if before[k] != after[k]}

            self.stdout.write(
                f"{len(feed_pairs)} feed and {len(med_pairs)} medicine "
                f"farm/item chains; {len(changed)} stored figures change.")
            for key, (was, now) in sorted(changed.items())[:20]:
                self.stdout.write(f"   {key}: {was} -> {now}")
            if len(changed) > 20:
                self.stdout.write(f"   … and {len(changed) - 20} more")

            if dry:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING("--dry-run: nothing written."))
                return

        self.stdout.write(self.style.SUCCESS("Stored stock rebuilt."))

    @staticmethod
    def _snapshot(entries, medicines):
        """Every stored balance, keyed so a change can be named."""
        shot = {}
        for pk, s1, s2 in entries.values_list("id", "feed_1_stock", "feed_2_stock"):
            shot[f"entry {pk} feed_1"] = s1
            shot[f"entry {pk} feed_2"] = s2
        for pk, st in medicines.values_list("id", "stock"):
            shot[f"medicine {pk}"] = st
        return shot
