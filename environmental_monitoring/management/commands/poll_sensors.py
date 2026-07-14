"""Poll every active Hub for fresh sensor readings.

Intended to be scheduled externally (Windows Task Scheduler in dev, cron or a
systemd timer in prod) every ~60 seconds - not run via an in-process scheduler
like django-apscheduler, since CACHES is LocMemCache (process-local) and would
give every Gunicorn worker its own scheduler thread with no cheap way to stop
them all polling the same hubs at once. PollLock (backed by Postgres, which
*is* shared) guards against overlapping runs of this command instead.
"""

import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from environmental_monitoring.models import Hub, PollLock
from environmental_monitoring.services.alert_service import AlertService
from environmental_monitoring.services.hub_service import HubService
from environmental_monitoring.services.sensor_service import SensorService

logger = logging.getLogger("environmental_monitoring.poll")

STALE_LOCK_MINUTES = 10


class Command(BaseCommand):
    help = "Poll all active Environmental Monitoring hubs for fresh sensor readings."

    def handle(self, *args, **options):
        if not self._acquire_lock():
            self.stdout.write("Poll already in progress; skipping.")
            return

        try:
            hub_service = HubService()
            sensor_service = SensorService()
            polled = 0
            for hub in Hub.objects.filter(is_active=True):
                try:
                    readings = hub_service.poll_hub(hub)
                    sensor_service.sync_readings(hub, readings)
                    polled += 1
                except Exception:
                    logger.exception("Unhandled error polling hub %s", hub.name)
            AlertService().evaluate_offline_all()
            self.stdout.write(self.style.SUCCESS(f"Polled {polled} hub(s)."))
        finally:
            self._release_lock()

    @staticmethod
    def _acquire_lock() -> bool:
        with transaction.atomic():
            lock, _created = PollLock.objects.select_for_update().get_or_create(pk=1)
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
        PollLock.objects.filter(pk=1).update(is_running=False)
