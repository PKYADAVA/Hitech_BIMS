"""Evaluate the configured alert rules.

Run it on a schedule — every 15 minutes suits the operational rules, and the
per-rule cooldown stops a frequent scan from repeating itself:

    python manage.py run_alert_scan

On Windows, a Scheduled Task; on the DigitalOcean droplet, a cron entry. The
command is safe to run concurrently with itself in the sense that duplicates are
suppressed by the cooldown, but there is no lock — overlapping runs will both do
the work, so keep the interval longer than a scan takes.
"""
from django.core.management.base import BaseCommand

from alerthub.services import scan


class Command(BaseCommand):
    help = "Evaluate active alert rules and raise notifications."

    def add_arguments(self, parser):
        parser.add_argument(
            "--rule-key",
            help="Only run rules for this catalogue key, e.g. "
                 "production.high_mortality.",
        )
        parser.add_argument(
            "--rule-id", type=int,
            help="Only run one configured rule, by id.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report which rules would run without evaluating them.",
        )

    def handle(self, *args, **options):
        result = scan(
            rule_key=options.get("rule_key"),
            rule_id=options.get("rule_id"),
            dry_run=options.get("dry_run", False),
        )

        if options.get("dry_run"):
            self.stdout.write(f"Would run {result.rules_run} rule(s).")
        else:
            self.stdout.write(self.style.SUCCESS(result.summary()))

        for key in sorted(set(result.skipped_unsupported)):
            self.stdout.write(
                self.style.WARNING(f"  skipped {key} — awaiting a data source")
            )
        for key in sorted(set(result.skipped_no_detector)):
            self.stdout.write(
                self.style.ERROR(f"  skipped {key} — no detector registered")
            )
        for key in sorted(set(result.failed)):
            self.stdout.write(
                self.style.ERROR(f"  failed  {key} — see logs for the traceback")
            )
