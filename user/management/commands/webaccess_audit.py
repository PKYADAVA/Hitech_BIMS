"""Read back what the Web-Access guard would have refused.

Enforcement ships dark (settings.WEB_ACCESS_ENFORCE): every request to a URL no
tab claims is recorded rather than refused. Run this after a normal day's work
to see the surface that is currently open, grouped so the decisions are obvious:

    python manage.py webaccess_audit                # summary
    python manage.py webaccess_audit --verdict denied
    python manage.py webaccess_audit --app broiler --full
    python manage.py webaccess_audit --clear        # start a fresh window
"""
from collections import defaultdict

from django.core.management.base import BaseCommand

from user.access import ALL_TAB_CODES
from user.models import WebAccessAudit


class Command(BaseCommand):
    help = "Summarise the Web-Access audit table (what enforcement would refuse)."

    def add_arguments(self, parser):
        parser.add_argument("--verdict", choices=["unmapped", "denied"],
                            help="Only this verdict.")
        parser.add_argument("--app", help="Only urls served by this app.")
        parser.add_argument("--full", action="store_true",
                            help="List every row rather than one line per url.")
        parser.add_argument("--clear", action="store_true",
                            help="Delete the recorded rows and start again.")

    def handle(self, *args, **options):
        if options["clear"]:
            count = WebAccessAudit.objects.count()
            WebAccessAudit.objects.all().delete()
            self.stdout.write(self.style.WARNING(f"Cleared {count} audit row(s)."))
            return

        rows = WebAccessAudit.objects.all()
        if options["verdict"]:
            rows = rows.filter(verdict=options["verdict"])
        if options["app"]:
            rows = rows.filter(view__startswith=options["app"] + ".")
        rows = list(rows)

        if not rows:
            self.stdout.write("Nothing recorded yet. The audit only fills as "
                              "people use the system.")
            return

        if options["full"]:
            self._full(rows)
        else:
            self._summary(rows)

    def _summary(self, rows):
        by_url = defaultdict(lambda: {"hits": 0, "users": set(), "methods": set(),
                                      "verdict": "", "view": ""})
        for r in rows:
            e = by_url[r.url_name]
            e["hits"] += r.hits
            e["users"].add(r.username)
            e["methods"].add(r.method)
            e["verdict"] = r.verdict
            e["view"] = r.view

        writes = {u: e for u, e in by_url.items() if e["methods"] - {"GET", "HEAD"}}
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n{len(by_url)} url(s) recorded — {len(writes)} of them accept writes\n"))

        # Writes first: an unguarded mutation is worse than an unguarded read.
        for title, subset in (("WRITE endpoints (close these first)", writes),
                              ("READ endpoints", {u: e for u, e in by_url.items()
                                                  if u not in writes})):
            if not subset:
                continue
            self.stdout.write(self.style.MIGRATE_LABEL(f"\n{title}"))
            self.stdout.write("  %-42s %-9s %6s %5s  %s" %
                              ("URL NAME", "VERDICT", "HITS", "USERS", "GUESSED TAB"))
            for url in sorted(subset):
                e = subset[url]
                self.stdout.write("  %-42s %-9s %6d %5d  %s" % (
                    url[:42], e["verdict"], e["hits"], len(e["users"]),
                    self._guess_tab(url) or "-"))

        self.stdout.write(
            "\nGUESSED TAB is the registry tab whose code prefixes the url name; "
            "it is a starting point for the mapping, not an answer.\n"
            "Add each url to its tab's extra_urls in user/access.py, then set "
            "WEB_ACCESS_ENFORCE=True.\n")

    def _full(self, rows):
        self.stdout.write("  %-38s %-6s %-9s %-16s %6s  %s" %
                          ("URL NAME", "METHOD", "VERDICT", "USER", "HITS", "LAST SEEN"))
        for r in sorted(rows, key=lambda r: (r.url_name, r.username)):
            self.stdout.write("  %-38s %-6s %-9s %-16s %6d  %s" % (
                r.url_name[:38], r.method, r.verdict, r.username[:16], r.hits,
                r.last_seen.strftime("%d %b %H:%M")))

    @staticmethod
    def _guess_tab(url_name):
        """The longest tab code that prefixes this url name, if any."""
        candidates = [t for t in ALL_TAB_CODES
                      if url_name == t or url_name.startswith(t.rstrip("_") + "_")]
        return max(candidates, key=len) if candidates else None
