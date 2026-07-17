"""Pull fresh data from every active GPS provider into the ERP database.

Intended to be scheduled externally (Windows Task Scheduler in dev, cron or a
systemd timer in prod) at the shortest configured provider refresh interval —
not via an in-process scheduler, for the same reason as
``environmental_monitoring.poll_sensors``: CACHES is LocMemCache
(process-local), so overlap protection must live in Postgres. SyncLock
(pk=1, ``select_for_update`` + stale takeover) guards concurrent runs.

Examples:
    python manage.py sync_tracking                        # everything
    python manage.py sync_tracking --kinds live           # fast live-only tick
    python manage.py sync_tracking --provider "TrackWick" --kinds history,visits
    python manage.py sync_tracking --lookback-hours 72    # first-run backfill
    python manage.py sync_tracking --kinds history --lookback-hours 48 --reset-cursor

A sensible production schedule is two entries: ``--kinds live`` every 1–2
minutes, and a full run (all kinds) every 15–30 minutes.

Cursor gotcha: ``--lookback-hours`` only takes effect on a sync type's very
first-ever run — once any run (even the recurring scheduled one) has
succeeded for that provider/kind, its ``window_end`` becomes the resume
point and the flag is silently ignored on later invocations. To force a
genuinely wider backfill (e.g. a newly-deployed environment whose scheduled
job already ticked a few times before you got to it), add ``--reset-cursor``
to discard prior sync-run history for the kinds being run first.
"""

import logging
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from tracking.models import SyncLock, TrackingSettings, TrackingSync
from tracking.services.sync_service import DEFAULT_KINDS, SyncService

logger = logging.getLogger("tracking.sync")

STALE_LOCK_MINUTES = 10


class Command(BaseCommand):
    help = "Sync employee-tracking data (live locations, history, visits, …) from all active providers."

    def add_arguments(self, parser):
        parser.add_argument(
            "--provider", default=None,
            help="Limit to one provider, by id or name (default: all active).",
        )
        parser.add_argument(
            "--kinds", default=None,
            help=f"Comma-separated data kinds to sync (default: all). "
                 f"Choices: {', '.join(DEFAULT_KINDS)}.",
        )
        parser.add_argument(
            "--lookback-hours", type=int, default=None,
            help="First-sync lookback window in hours (default 24). Only used "
                 "for kinds that have never synced successfully.",
        )
        parser.add_argument(
            "--trigger", default="scheduler", choices=["scheduler", "manual"],
            help="Recorded on the sync runs (default: scheduler).",
        )
        parser.add_argument(
            "--reset-cursor", action="store_true",
            help="Discard prior TrackingSync history for the kind(s)/provider(s) "
                 "about to run, so --lookback-hours actually takes effect instead "
                 "of resuming from an already-advanced cursor. Use when a "
                 "scheduled job already ticked before you got to run a wider "
                 "manual backfill.",
        )

    def handle(self, *args, **options):
        settings_row = TrackingSettings.get_solo()
        if not settings_row.enabled:
            self.stdout.write(
                "Employee tracking is disabled in Tracking Settings; nothing to do."
            )
            return

        kinds = self._parse_kinds(options["kinds"])
        lookback = (
            timedelta(hours=options["lookback_hours"])
            if options["lookback_hours"] else None
        )

        if options["reset_cursor"]:
            self._reset_cursor(kinds, options["provider"])

        if not self._acquire_lock():
            self.stdout.write("Tracking sync already in progress; skipping.")
            return
        try:
            service = SyncService(lookback=lookback)
            runs = service.sync_all(
                kinds=kinds, trigger=options["trigger"],
                provider_filter=options["provider"],
            )
            for run in runs:
                self.stdout.write(
                    f"{run.provider.name:<25} {run.sync_type:<11} {run.status:<8}"
                    f" fetched={run.records_fetched} created={run.records_created}"
                    f" updated={run.records_updated} skipped={run.records_skipped}"
                    + (f" error={run.error_message}" if run.error_message else "")
                )
            failed = sum(1 for run in runs if run.status == "failed")
            summary = f"Completed {len(runs)} sync run(s), {failed} failed."
            style = self.style.WARNING if failed else self.style.SUCCESS
            self.stdout.write(style(summary))
        finally:
            self._release_lock()

    def _reset_cursor(self, kinds, provider_identifier):
        from tracking.models import TrackingProvider

        queryset = TrackingSync.objects.filter(
            sync_type__in=(kinds or DEFAULT_KINDS)
        )
        if provider_identifier:
            providers = TrackingProvider.objects.filter(is_active=True)
            providers = (providers.filter(pk=int(provider_identifier))
                        if str(provider_identifier).isdigit()
                        else providers.filter(name__iexact=provider_identifier))
            queryset = queryset.filter(provider__in=providers)
        deleted, _ = queryset.delete()
        self.stdout.write(
            f"--reset-cursor: discarded {deleted} prior sync run(s) for "
            f"{', '.join(kinds or DEFAULT_KINDS)}; the next run starts fresh."
        )

    @staticmethod
    def _parse_kinds(raw):
        if not raw:
            return None
        kinds = [kind.strip().lower() for kind in raw.split(",") if kind.strip()]
        invalid = [kind for kind in kinds if kind not in DEFAULT_KINDS]
        if invalid:
            raise CommandError(
                f"Unknown kind(s): {', '.join(invalid)}. "
                f"Choices: {', '.join(DEFAULT_KINDS)}."
            )
        return kinds

    @staticmethod
    def _acquire_lock() -> bool:
        with transaction.atomic():
            lock, _created = SyncLock.objects.select_for_update().get_or_create(pk=1)
            stale = lock.started_at is None or (
                timezone.now() - lock.started_at > timedelta(minutes=STALE_LOCK_MINUTES)
            )
            if lock.is_running and not stale:
                return False
            lock.is_running = True
            lock.started_at = timezone.now()
            lock.save(update_fields=["is_running", "started_at"])
            return True

    @staticmethod
    def _release_lock() -> None:
        SyncLock.objects.filter(pk=1).update(is_running=False)
