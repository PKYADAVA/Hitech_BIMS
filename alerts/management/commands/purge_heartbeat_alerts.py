"""Purge heartbeat-noise alerts that predate the ``last_seen_at`` IGNORE_FIELDS
fix (settings.ALERT_SETTINGS).

The tracking sync bumps ``EmployeeProviderMapping.last_seen_at`` every cycle; before
that field was ignored, each bump wrote an "Object Updated" alert, flooding the
feed. This command removes those already-written rows.

Safe by default:
  * Only touches the Alert feed, never the immutable AuditLog (opt in with
    --include-audit if you really want the audit rows gone too).
  * "Surgical" by default: deletes only update-alerts whose *entire* changed-field
    set is heartbeat fields (--fields, default last_seen_at), so an alert that also
    recorded a real change (e.g. a re-map to another employee) is preserved.
  * --dry-run shows exactly what would go, deleting nothing.

Examples:
  python manage.py purge_heartbeat_alerts --dry-run
  python manage.py purge_heartbeat_alerts --yes
  python manage.py purge_heartbeat_alerts --all-updates --include-audit --yes
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from alerts.models import Alert, AuditLog

DEFAULT_MODEL = "tracking.EmployeeProviderMapping"
DEFAULT_FIELDS = ["last_seen_at"]


class Command(BaseCommand):
    help = "Delete heartbeat-only 'updated' alerts (e.g. EmployeeProviderMapping.last_seen_at) that flooded the feed."

    def add_arguments(self, parser):
        parser.add_argument(
            "--model", default=DEFAULT_MODEL,
            help=f"Target model_name (app_label.Model). Default: {DEFAULT_MODEL}",
        )
        parser.add_argument(
            "--fields", nargs="+", default=DEFAULT_FIELDS,
            help="Heartbeat field names that define 'noise'. An update alert is purged "
                 f"only if its changed fields are a subset of these. Default: {DEFAULT_FIELDS}",
        )
        parser.add_argument(
            "--all-updates", action="store_true",
            help="Delete ALL 'update' alerts for the model, ignoring --fields "
                 "(broader; use only if you're sure none carry real changes).",
        )
        parser.add_argument(
            "--include-audit", action="store_true",
            help="Also delete matching AuditLog rows. NOTE: the audit trail is "
                 "immutable by contract — only use this if you accept that.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would be deleted without deleting anything.",
        )
        parser.add_argument(
            "--yes", action="store_true",
            help="Skip the interactive confirmation (for scripted/production runs).",
        )

    def _select_alert_ids(self, model, fields, all_updates):
        """Ids of Alert rows to purge for this model."""
        base = Alert.objects.filter(model_name=model, action="update")
        if all_updates:
            return list(base.values_list("id", flat=True))
        # Surgical: keep only rows whose changed_fields keys ⊆ heartbeat fields.
        field_set = set(fields)
        ids = []
        for pk, changed in base.values_list("id", "changed_fields"):
            keys = set((changed or {}).keys())
            if keys and keys <= field_set:
                ids.append(pk)
        return ids

    def _select_audit_ids(self, model, fields, all_updates):
        base = AuditLog.objects.filter(model_name=model, action="update")
        if all_updates:
            return list(base.values_list("id", flat=True))
        field_set = set(fields)
        ids = []
        for pk, changed in base.values_list("id", "changed_fields"):
            keys = set((changed or {}).keys())
            if keys and keys <= field_set:
                ids.append(pk)
        return ids

    @transaction.atomic
    def handle(self, *args, **options):
        model = options["model"]
        fields = options["fields"]
        all_updates = options["all_updates"]
        include_audit = options["include_audit"]
        dry_run = options["dry_run"]
        assume_yes = options["yes"]

        scope = ("all 'update' alerts" if all_updates
                 else f"update alerts changing only {fields}")
        self.stdout.write(f"Target model : {model}")
        self.stdout.write(f"Scope        : {scope}")

        alert_ids = self._select_alert_ids(model, fields, all_updates)
        self.stdout.write(self.style.WARNING(f"Alert rows matched   : {len(alert_ids)}"))

        audit_ids = []
        if include_audit:
            audit_ids = self._select_audit_ids(model, fields, all_updates)
            self.stdout.write(self.style.WARNING(
                f"AuditLog rows matched: {len(audit_ids)} "
                "(immutable trail — deleting on request)"))

        if not alert_ids and not audit_ids:
            self.stdout.write(self.style.SUCCESS("Nothing to purge. Feed is already clean."))
            return

        if dry_run:
            self.stdout.write(self.style.NOTICE(
                "\nDRY RUN — no rows deleted. Re-run without --dry-run to apply."))
            return

        if not assume_yes:
            total = len(alert_ids) + len(audit_ids)
            confirm = input(f"\nDelete {total} row(s)? This cannot be undone. Type 'yes' to proceed: ")
            if confirm.strip().lower() != "yes":
                self.stdout.write(self.style.ERROR("Aborted — nothing deleted."))
                return

        # Delete in id batches to keep the transaction / query size sane on large feeds.
        alert_deleted = self._delete_in_batches(Alert, alert_ids)
        audit_deleted = self._delete_in_batches(AuditLog, audit_ids) if audit_ids else 0

        msg = f"Deleted {alert_deleted} alert row(s)"
        if include_audit:
            msg += f" and {audit_deleted} audit row(s)"
        self.stdout.write(self.style.SUCCESS(msg + "."))

    @staticmethod
    def _delete_in_batches(model_cls, ids, batch_size=5000):
        total = 0
        for i in range(0, len(ids), batch_size):
            chunk = ids[i:i + batch_size]
            # queryset .delete() bypasses AuditLog's per-instance immutability guard,
            # which is intended here (bulk cleanup of known noise).
            deleted, _ = model_cls.objects.filter(id__in=chunk).delete()
            total += deleted
        return total
