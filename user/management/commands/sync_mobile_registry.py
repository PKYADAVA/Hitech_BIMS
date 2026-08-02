"""Write the phone's permission maps from the server registry.

``PHONE_SCREENS`` / ``PHONE_REPORTS`` in ``user.services.mobile_access`` and
``RESOURCE_TABS`` / ``REPORT_TABS`` in ``mobile/src/api/permissions.ts`` are two
copies of one fact. They cannot be merged — the client needs them at runtime
with no server round-trip — so the next best thing is that only one is written
by hand.

    python manage.py sync_mobile_registry           # rewrite the client
    python manage.py sync_mobile_registry --check   # fail if out of date

Tests already compare the two, so drift is caught either way. This makes it a
one-command fix rather than a hand edit in a second file that is easy to forget
— which is how inventory and account went unmapped for a day.
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from user.services.mobile_access import PHONE_REPORTS, PHONE_SCREENS

CLIENT = Path(settings.BASE_DIR) / "mobile" / "src" / "api" / "permissions.ts"

#: The comment banner each group of entries gets, keyed by resource prefix, so
#: the generated block reads like the hand-written one it replaces.
GROUPS = [
    ("broiler", "Broiler"), ("hatchery", "Hatchery"), ("inventory", "Inventory"),
    ("account", "Account"), ("sales", "Sales"), ("purchase", "Purchase"),
    ("hr", "HR"), ("user", "Users"), ("sms", "SMS"),
]


def _render(pairs, indent="  "):
    """The body of a TS object literal, grouped and commented like the original."""
    remaining = list(pairs)
    lines = []
    for prefix, label in GROUPS:
        block = [(k, v) for k, v in remaining if k.split("-")[0] == prefix]
        if not block:
            continue
        remaining = [p for p in remaining if p not in block]
        lines.append(f"{indent}// {label}")
        for key, tab in block:
            # Always quote. Most keys contain hyphens and must be quoted, so
            # quoting the handful that need not keeps the generated block
            # uniform and the output byte-stable.
            lines.append(f'{indent}"{key}": "{tab}",')
    for key, tab in remaining:            # anything a group does not claim
        lines.append(f'{indent}"{key}": "{tab}",')
    return "\n".join(lines)


def _splice(text, const, body):
    """Replace the body of ``export const <const>: … = { … };``."""
    start = text.index(f"export const {const}")
    open_brace = text.index("{", start)
    close = text.index("\n};", open_brace)
    return text[: open_brace + 1] + "\n" + body + "\n" + text[close + 1 :]


class Command(BaseCommand):
    help = "Regenerate the phone's RESOURCE_TABS / REPORT_TABS from the server registry."

    def add_arguments(self, parser):
        parser.add_argument(
            "--check", action="store_true",
            help="Exit non-zero if the client is out of date; write nothing.")

    def handle(self, *args, **options):
        if not CLIENT.exists():
            raise CommandError(f"client not found: {CLIENT}")

        original = CLIENT.read_text(encoding="utf-8")
        updated = _splice(original, "RESOURCE_TABS", _render(PHONE_SCREENS))
        updated = _splice(updated, "REPORT_TABS", _render(PHONE_REPORTS))

        if updated == original:
            self.stdout.write(self.style.SUCCESS("Client registry is up to date."))
            return

        if options["check"]:
            raise CommandError(
                "mobile/src/api/permissions.ts is out of date — run "
                "`python manage.py sync_mobile_registry`.")

        CLIENT.write_text(updated, encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(
            f"Wrote {len(PHONE_SCREENS)} screens and {len(PHONE_REPORTS)} reports "
            f"to {CLIENT.relative_to(settings.BASE_DIR)}."))
