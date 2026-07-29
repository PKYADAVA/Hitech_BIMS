"""Give every item a baseline entry in Item Price Master.

Stock Transfer values a line at the Item Price Master rate and refuses to save
when the item has no price for that date. This backfills a starting price —
each item's standard cost — for items that have none, so that rule can be
switched on without stopping work while the real prices are entered.

The entry is dated before the earliest existing transaction so historic records
can still be edited. Items that already have any price entry are left alone,
and so are items with no standard cost: seeding those at zero would put a
meaningless figure into stock valuation, which is the very thing the rule
exists to prevent — they are reported instead.
"""

from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction

from inventory.models import Item, ItemPriceList, StockTransfer


class Command(BaseCommand):
    help = "Seed Item Price Master from each item's standard cost where no price exists."

    def add_arguments(self, parser):
        parser.add_argument(
            "--effective-date",
            help="Date to record the baseline against (default: the day before "
                 "the earliest existing stock transfer, else today).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Show what would be created without writing anything.",
        )

    def handle(self, *args, **options):
        if options.get("effective_date"):
            effective = date.fromisoformat(options["effective_date"])
        else:
            earliest = (StockTransfer.objects.order_by("date")
                        .values_list("date", flat=True).first())
            effective = (earliest - timedelta(days=1)) if earliest else date.today()

        priced = set(ItemPriceList.objects.values_list("item_id", flat=True))
        to_create, skipped = [], []
        for item in Item.objects.order_by("description"):
            if item.id in priced:
                continue
            if not item.standard_cost_per_unit:
                skipped.append(item)
                continue
            to_create.append(ItemPriceList(
                item=item, price=item.standard_cost_per_unit, effective_date=effective))

        self.stdout.write("Effective date: %s" % effective)
        for entry in to_create:
            self.stdout.write("  + %-30s %s" % (entry.item.description[:30], entry.price))
        for item in skipped:
            self.stdout.write(self.style.WARNING(
                "  ! %-30s no standard cost — add a price manually"
                % item.description[:30]))

        if options["dry_run"]:
            self.stdout.write(self.style.NOTICE(
                "Dry run: %d would be created, %d need manual entry."
                % (len(to_create), len(skipped))))
            return

        with transaction.atomic():
            ItemPriceList.objects.bulk_create(to_create)
        self.stdout.write(self.style.SUCCESS(
            "Created %d price entr%s; %d item(s) still need one."
            % (len(to_create), "y" if len(to_create) == 1 else "ies", len(skipped))))
