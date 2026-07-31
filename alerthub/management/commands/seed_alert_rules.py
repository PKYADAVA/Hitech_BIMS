"""Create one starter rule for every alert that has a detector.

An empty Alert Configuration master means an empty feed, which reads as a broken
module rather than an unconfigured one. This gives the system something sensible
to say on day one, using each catalogue entry's own default threshold and
priority.

Rules are created **inactive** unless ``--activate`` is passed. Switching
seventy watches on against live production data without anyone choosing the
thresholds would bury the feed on the first scan — the operator should read the
list, tune it, and enable what they want.

Idempotent: a rule whose name already exists is left alone, so re-running after
a catalogue addition only adds what is new.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from alerthub.catalog import CATALOG
from alerthub.models import AlertRule


class Command(BaseCommand):
    help = "Seed a default alert rule for every supported catalogue entry."

    def add_arguments(self, parser):
        parser.add_argument(
            "--activate", action="store_true",
            help="Create the rules enabled. Off by default so nothing fires "
                 "until someone has reviewed the thresholds.",
        )
        parser.add_argument(
            "--group", action="append", default=[],
            help="Notify this group by name. Repeatable. With no group, the "
                 "rules notify everyone whose data scope matches.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        from django.contrib.auth.models import Group

        groups = list(Group.objects.filter(name__in=options["group"]))
        missing = set(options["group"]) - {g.name for g in groups}
        for name in sorted(missing):
            self.stdout.write(self.style.WARNING(f"No such group: {name}"))

        created = skipped = 0
        for spec in CATALOG:
            if not spec.supported:
                continue
            name = f"{spec.label} — default"
            if AlertRule.objects.filter(name=name).exists():
                skipped += 1
                continue

            rule = AlertRule.objects.create(
                name=name,
                rule_key=spec.key,
                priority=spec.priority,
                threshold=spec.threshold.default if spec.threshold else None,
                operator=spec.threshold.operator if spec.threshold else "gte",
                is_active=options["activate"],
            )
            if groups:
                rule.notify_groups.set(groups)
            created += 1

        state = "enabled" if options["activate"] else "disabled"
        self.stdout.write(self.style.SUCCESS(
            f"Created {created} rule(s) ({state}); {skipped} already existed."
        ))
        if created and not options["activate"]:
            self.stdout.write(
                "Review the thresholds in Alerts > Alert Configuration, then "
                "enable the ones you want."
            )
