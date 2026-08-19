"""Point the active alert rules at a group instead of at everybody.

A rule with no ``notify_groups`` goes to every active user — the deliberate
fail-open that let the module be configured before anyone had decided who
should hear from it. That default is harmless while nothing runs the scan and
loud the moment something does: eight rules, nine inboxes and a push to every
registered handset, all in the first minute.

So this exists to be run once before the schedule is switched on, and again
whenever the answer to "who deals with this?" changes:

    python manage.py set_alert_audience --group "Managers" --dry-run
    python manage.py set_alert_audience --group "Managers"
    python manage.py set_alert_audience --group "Managers" --rule-key inventory.negative_stock

It only ever *adds* the group to rules that name nobody. A rule somebody has
already aimed at a group is left exactly as it is — this is a safety net for
the unconfigured ones, not a tool that quietly re-points a considered choice.
Pass ``--replace`` to mean it.
"""
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError

from alerthub.models import AlertRule


class Command(BaseCommand):
    help = "Restrict active alert rules to a notification group."

    def add_arguments(self, parser):
        parser.add_argument("--group", required=True,
                            help="Name of the group to notify, e.g. Managers.")
        parser.add_argument("--rule-key",
                            help="Only this catalogue key, e.g. "
                                 "inventory.negative_stock.")
        parser.add_argument("--include-inactive", action="store_true",
                            help="Also touch rules that are switched off.")
        parser.add_argument("--replace", action="store_true",
                            help="Also re-point rules that already name a "
                                 "group. Off by default: a considered choice "
                                 "should not be overwritten by a bulk command.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Say what would change and change nothing.")

    def handle(self, *args, **options):
        name = options["group"]
        try:
            group = Group.objects.get(name=name)
        except Group.DoesNotExist:
            raise CommandError(
                f"No group named {name!r}. Existing groups: "
                + ", ".join(Group.objects.values_list("name", flat=True)))

        members = group.user_set.filter(is_active=True).count()
        if not members:
            # Not an error — an empty group is a real answer, and raising an
            # alert nobody receives writes nothing at all. Say so, loudly,
            # because it is far more likely to be a mistake than an intention.
            self.stdout.write(self.style.WARNING(
                f"{name!r} has no active members. Rules pointed at it will "
                "reach nobody, and an alert with no audience is not written."))

        rules = AlertRule.objects.all()
        if not options["include_inactive"]:
            rules = rules.filter(is_active=True)
        if options["rule_key"]:
            rules = rules.filter(rule_key=options["rule_key"])
            if not rules.exists():
                raise CommandError(f"No rule with key {options['rule_key']!r}.")

        changed = skipped = already = 0
        for rule in rules.order_by("rule_key"):
            current = list(rule.notify_groups.values_list("name", flat=True))
            if group.name in current:
                already += 1
                continue
            if current and not options["replace"]:
                skipped += 1
                self.stdout.write(
                    f"  keeping  {rule.rule_key:<38} -> {', '.join(current)}")
                continue
            changed += 1
            self.stdout.write(self.style.SUCCESS(
                f"  {'would set' if options['dry_run'] else 'set'}"
                f"      {rule.rule_key:<38} -> {name}"))
            if not options["dry_run"]:
                if options["replace"]:
                    rule.notify_groups.set([group])
                else:
                    rule.notify_groups.add(group)

        verb = "Would change" if options["dry_run"] else "Changed"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {changed} rule(s); {already} already pointed there, "
            f"{skipped} left alone (pass --replace to include them)."))
