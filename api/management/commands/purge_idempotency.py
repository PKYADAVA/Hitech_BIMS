"""Drop idempotency keys old enough that no phone could still be holding one.

Every write the phone queues leaves a row behind so a replay can be answered
without doing the work twice. They are only useful while a phone might still
retry: the outbox gives up long before a week is out, so anything older is a
record of work already done and acknowledged, and only takes up room.

Safe to run on a schedule. Nothing depends on these rows once their write has
been acknowledged — the worst a too-eager purge could do is let a very stale
retry through, which is why the default window is generous.

    python manage.py purge_idempotency
    python manage.py purge_idempotency --days 30 --dry-run
"""
from django.core.management.base import BaseCommand

from api.middleware import purge_idempotency_records
from api.models import IdempotencyRecord


class Command(BaseCommand):
    help = "Delete idempotency keys older than the given number of days."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=7,
                            help="Keep keys newer than this (default 7).")
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would go and delete nothing.")

    def handle(self, *args, **options):
        days = options["days"]
        if options["dry_run"]:
            from datetime import timedelta

            from django.utils import timezone

            cutoff = timezone.now() - timedelta(days=days)
            count = IdempotencyRecord.objects.filter(created_at__lt=cutoff).count()
            self.stdout.write(f"{count} of {IdempotencyRecord.objects.count()} "
                              f"keys are older than {days} days.")
            self.stdout.write(self.style.WARNING("--dry-run: nothing deleted."))
            return

        deleted = purge_idempotency_records(days)
        self.stdout.write(self.style.SUCCESS(
            f"Deleted {deleted} idempotency key(s) older than {days} days."))
