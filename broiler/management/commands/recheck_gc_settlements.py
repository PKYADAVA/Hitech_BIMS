"""Re-derive settled batches' figures and report — or apply — the differences.

A settlement freezes every figure the form showed. When a fault is found in
one of those calculations, fixing it reaches every batch settled afterwards and
none settled before, and the old ones cannot be put right by editing them:
editing a settlement touches what a person typed and deliberately leaves the
computed figures alone.

This walks settlements, works out what each one would say if it were computed
today, and shows the difference. It changes nothing unless ``--apply`` is
passed, because these are documents farmers were paid against.

    # what would change, across everything settled
    python manage.py recheck_gc_settlements

    # one batch, in detail
    python manage.py recheck_gc_settlements --batch AKB-1102-1 --verbose

    # put it right, saying why
    python manage.py recheck_gc_settlements --batch AKB-1102-1 --apply \\
        --note "Feed Out was missing farm-to-farm transfers"

Each applied correction writes a GCSettlementRecalculation row naming who ran
it and every field that moved.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from broiler.models import GrowingChargeSettlement
from broiler.services import gc_recalc


class Command(BaseCommand):
    help = "Re-derive settled batches' figures; report differences, or apply them."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Write the corrections. Off by default: without it this only "
                 "reports what a re-run would change.")
        parser.add_argument(
            "--batch", action="append", default=[],
            help="Batch name. Repeatable. Default: every settlement.")
        parser.add_argument(
            "--field", action="append", default=[],
            help="Only settlements where this field would change. Repeatable — "
                 "e.g. --field feed_balance, to find the batches one fault "
                 "actually touched.")
        parser.add_argument(
            "--keep-date", action="store_true",
            help="Leave gc_date alone. The closing date moves a voucher between "
                 "periods, which may be a decision rather than a correction.")
        parser.add_argument(
            "--note", default="",
            help="Recorded against each correction. Say why.")
        parser.add_argument(
            "--verbose", action="store_true",
            help="Print every field that would move, not just a count.")

    def handle(self, *args, **options):
        rows = (GrowingChargeSettlement.objects
                .select_related("batch", "scheme", "farm")
                .order_by("settlement_code"))
        if options["batch"]:
            rows = rows.filter(batch__batch_name__in=options["batch"])

        wanted = set(options["field"])
        include_date = not options["keep_date"]
        checked = affected = applied = 0

        for settlement in rows:
            checked += 1
            try:
                changes, _merged = gc_recalc.plan(settlement, include_date=include_date)
            except Exception as error:                      # noqa: BLE001
                # One unbuildable batch must not stop the sweep: the whole
                # point is to find out how far a fault reached.
                self.stderr.write(self.style.WARNING(
                    "%s (%s): could not be rebuilt — %s"
                    % (settlement.settlement_code, settlement.batch.batch_name, error)))
                continue

            if wanted:
                changes = {k: v for k, v in changes.items() if k in wanted}
            if not changes:
                continue

            affected += 1
            self.stdout.write("%s  %s  %d field(s)" % (
                settlement.settlement_code, settlement.batch.batch_name, len(changes)))
            if options["verbose"]:
                for name, move in sorted(changes.items()):
                    self.stdout.write("    %-28s %s -> %s"
                                      % (name, move["from"] or "-", move["to"] or "-"))

            if options["apply"]:
                with transaction.atomic():
                    gc_recalc.recalculate(
                        settlement, user=None, include_date=include_date,
                        note=options["note"] or "recheck_gc_settlements")
                applied += 1

        self.stdout.write("")
        self.stdout.write("%d settlement(s) checked, %d would change." % (checked, affected))
        if options["apply"]:
            self.stdout.write(self.style.SUCCESS("%d corrected." % applied))
        elif affected:
            self.stdout.write("Nothing written. Pass --apply to correct them.")
        else:
            self.stdout.write(self.style.SUCCESS("Every settlement already agrees "
                                                 "with its batch's records."))
