"""Evaluate hub/sensor offline alerts independent of any single poll or push.

Under the push (ingest) architecture, each request only touches the one hub
that just pushed - nothing else notices a hub going silent unless this runs
on its own schedule. Run this on the cloud side every few minutes (cron /
platform scheduled job), separate from any on-site collector's push cadence.

(poll_sensors still calls this same evaluation itself for the local-poll
deployment path, where the process already knows about every hub each run.)
"""

from django.core.management.base import BaseCommand

from environmental_monitoring.services.alert_service import AlertService


class Command(BaseCommand):
    help = "Evaluate hub/sensor offline connectivity alerts."

    def handle(self, *args, **options):
        AlertService().evaluate_offline_all()
        self.stdout.write(self.style.SUCCESS("Offline alert evaluation complete."))
