"""Recompute every stored running-stock figure against what was actually held.

Five documents keep a running stock column, and every one of them chained from
an opening balance of zero over its own rows -- which is not an opening balance
but an assumption that nothing had ever arrived. A farm sent 2,337 kg of feed
showed 0; a warehouse that had received 5,070 chicks showed its outflows as a
growing negative. What was on screen was cumulative movement with a minus sign.

  broiler   Daily Entry            feed_1_stock / feed_2_stock
  broiler   Medicine Consumption   stock
  inventory Stock Transfer         stock
  inventory Medicine Transfer      stock (per line)
  inventory Inventory Adjustment   stock (per line)

The calculations are fixed; this rewrites the rows already saved under the
old ones. It is idempotent — a second run reports nothing changed — so it is safe to
run again after a deploy, or to run with --dry-run first to see the damage
before touching anything.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from broiler.models import DailyEntry, MedicineVaccineEntry
from inventory.models import (InventoryAdjustmentItem, MedicineTransferItem,
                              StockTransfer)


class Command(BaseCommand):
    help = "Rebuild every stored running-stock figure from actual movements."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would change and write nothing.")
        parser.add_argument("--farm", type=int, default=None,
                            help="Limit the farm-side chains to one farm id.")

    def handle(self, *args, **options):
        from broiler.views import (_recompute_medicine_stock_chain,
                                   _recompute_stock_chain)
        from inventory.views import (
            _recompute_inventory_adjustment_chain,
            _recompute_medicine_stock_chain as _recompute_medicine_transfer_chain,
            _recompute_stock_transfer_chain)

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

        # Inventory's three chains are keyed by source location, not farm.
        transfers = StockTransfer.objects.exclude(item=None)
        med_transfers = MedicineTransferItem.objects.exclude(item=None)
        adjustments = InventoryAdjustmentItem.objects.exclude(item=None)
        keys = self._location_keys(transfers, med_transfers, adjustments)

        parts = (entries, medicines, transfers, med_transfers, adjustments)
        before = self._snapshot(*parts)

        with transaction.atomic():
            for farm_id, item_id in sorted(feed_pairs):
                _recompute_stock_chain(farm_id, item_id)
            for farm_id, item_id in sorted(med_pairs):
                _recompute_medicine_stock_chain(farm_id, item_id)
            for key in sorted(keys['transfer']):
                _recompute_stock_transfer_chain(*key)
            for key in sorted(keys['med_transfer']):
                _recompute_medicine_transfer_chain(*key)
            for key in sorted(keys['adjustment']):
                _recompute_inventory_adjustment_chain(*key)

            after = self._snapshot(*parts)
            changed = {k: (before[k], after[k]) for k in before
                       if before[k] != after[k]}

            self.stdout.write(
                f"chains: {len(feed_pairs)} feed, {len(med_pairs)} medicine, "
                f"{len(keys['transfer'])} transfer, "
                f"{len(keys['med_transfer'])} medicine-transfer, "
                f"{len(keys['adjustment'])} adjustment; "
                f"{len(changed)} stored figures change.")
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
    def _location_keys(transfers, med_transfers, adjustments):
        """(location_type, location_id, item_id) per inventory chain.

        A farm and a warehouse share the id space, so the type travels with
        the id or two different places would be rebuilt as one.
        """
        def pairs(qs, type_f, farm_f, wh_f):
            return {(t, f or w, i)
                    for t, f, w, i in qs.values_list(type_f, farm_f, wh_f, "item_id")
                    if t and (f or w) and i}

        return {
            "transfer": pairs(transfers, "from_location_type",
                              "from_farm_id", "from_warehouse_id"),
            "med_transfer": pairs(med_transfers, "transfer__from_location_type",
                                  "transfer__from_farm_id",
                                  "transfer__from_warehouse_id"),
            "adjustment": pairs(adjustments, "adjustment__location_type",
                                "adjustment__farm_id",
                                "adjustment__warehouse_id"),
        }

    @staticmethod
    def _snapshot(entries, medicines, transfers, med_transfers, adjustments):
        """Every stored balance, keyed so a change can be named."""
        shot = {}
        for pk, s1, s2 in entries.values_list("id", "feed_1_stock", "feed_2_stock"):
            shot[f"entry {pk} feed_1"] = s1
            shot[f"entry {pk} feed_2"] = s2
        for label, qs in (("medicine", medicines), ("transfer", transfers),
                          ("med-transfer", med_transfers),
                          ("adjustment", adjustments)):
            for pk, st in qs.values_list("id", "stock"):
                shot[f"{label} {pk}"] = st
        return shot
