"""Say why a user's lists are empty.

Data scoping has two ways of showing nothing, and they look identical from the
phone. Either the scope permits nothing — "not All" was ticked and no rows were
chosen — or it permits something but every row is excluded, most often because
the column the scope reads is NULL on the rows themselves. A farm with no
branch, an employee with no warehouse: `scope_multi` filters with
``field__in=ids``, which drops a NULL rather than keeping it, so the moment any
scope is applied those rows disappear from every list built on them.

Guessing between the two from a screenshot is not possible, and loosening the
wrong one widens access for everybody. This prints the answer for one named
user: what each scope resolves to, how many rows each phone list returns
against how many exist, and — the part that usually explains it — how many of
the hidden rows were hidden only because their scope column is empty.

    python manage.py explain_access <username>
    python manage.py explain_access <username> --resource broiler/daily-entries
    python manage.py explain_access <username> --app

``--app`` answers the other half. Scoping decides which *rows* reach a screen;
the phone has two gates in front of that deciding whether the screen appears at
all — the web tab matrix, and Mobile Access on top of it. A tab missing from
the app and a tab full of nothing look the same to whoever reports it, so this
prints the payload the phone is actually served and names the gate that closed
each screen.
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q


class Command(BaseCommand):
    help = "Explain what a user's data scoping lets them see, and why rows are missing."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--resource", default=None,
                            help="Only report this API prefix, e.g. broiler/daily-entries")
        parser.add_argument("--app", action="store_true",
                            help="Also report which phone tabs this user is served, "
                                 "and which gate hides the rest")

    def handle(self, *args, **options):
        from api.viewsets import API_SCOPES
        from user.services.scoping import SCOPES, allowed_ids, is_unscoped

        try:
            user = User.objects.get(username=options["username"])
        except User.DoesNotExist:
            raise CommandError(f"No user named {options['username']!r}.")

        self.stdout.write(self.style.MIGRATE_HEADING(f"\nUser: {user.username}"))
        groups = list(user.groups.values_list("name", flat=True))
        self.stdout.write(f"  Groups        : {', '.join(groups) or '(none)'}")
        self.stdout.write(f"  Superuser     : {user.is_superuser}")
        self.stdout.write(f"  Active        : {user.is_active}")

        # Before the scoping: which tabs reach the phone at all is a separate
        # question, and it is answered even for a user nothing is scoped for.
        if options["app"]:
            self._app_report(user)

        if is_unscoped(user):
            self.stdout.write(self.style.SUCCESS(
                "\n  Not scoped at all — superuser, an Admin access type, or no group "
                "carries an access profile. Empty lists are not scoping's doing."))
            return

        # ---- what each dimension resolves to -----------------------------
        self.stdout.write(self.style.MIGRATE_HEADING("\nScopes"))
        empty_scopes = []
        for scope in SCOPES:
            ids = allowed_ids(user, scope)
            if ids is None:
                self.stdout.write(f"  {scope:17} ALL")
            elif not ids:
                empty_scopes.append(scope)
                self.stdout.write(self.style.ERROR(
                    f"  {scope:17} NOTHING  <-- 'All' is off and no rows are chosen"))
            else:
                self.stdout.write(f"  {scope:17} {len(ids)} selected")

        if empty_scopes:
            self.stdout.write(self.style.WARNING(
                "\n  A scope set to NOTHING permits nothing — it is not the same as "
                "leaving it on 'All'.\n  Every list that reads "
                + ", ".join(empty_scopes) + " will be empty until it is fixed\n"
                "  in Users > User Access Groups > the group > Data Scope."))

        # ---- what each list actually returns -----------------------------
        self.stdout.write(self.style.MIGRATE_HEADING("\nLists"))
        self.stdout.write(f"  {'model':38} {'visible':>8} {'total':>8}  why hidden")

        wanted = options["resource"]
        for label, scopes in sorted(API_SCOPES.items()):
            model = _model_for(label)
            if model is None:
                continue
            if wanted and wanted.lower() not in label.lower():
                continue
            self._report(user, label, model, dict(scopes))

    # ------------------------------------------------------------------
    def _app_report(self, user):
        """What the phone is served, and what closed the rest.

        Built from the same helpers ``api.auth.PermissionsView`` calls, so this
        cannot drift from the payload the app actually receives.
        """
        from user.access import allowed_nav_groups, allowed_view_tabs
        from user.services.mobile_access import (NAV_MODULE, PHONE_REPORTS,
                                                 PHONE_SCREENS,
                                                 allowed_mobile_navs,
                                                 screen_perms)

        web_navs = allowed_nav_groups(user)
        navs = allowed_mobile_navs(user, web_navs)
        tabs = allowed_view_tabs(user)
        mobile = screen_perms(user)

        self.stdout.write(self.style.MIGRATE_HEADING(
            "\nPhone modules for %s" % user.username))
        self.stdout.write("  shown : " + (", ".join(sorted(navs)) or "(none)"))
        off_here = sorted(n for n in web_navs if n not in navs)
        if off_here:
            self.stdout.write(self.style.WARNING(
                "  hidden by Mobile Access: " + ", ".join(off_here)))

        self.stdout.write(self.style.MIGRATE_HEADING("\nPhone screens"))
        shown, hidden = [], []
        for key, tab in list(PHONE_SCREENS) + list(PHONE_REPORTS):
            nav = next((n for n, codes in _nav_groups().items()
                        if tab in codes and n in NAV_MODULE), None)
            if tab not in tabs:
                hidden.append((key, "the web matrix does not grant View on this tab"))
            elif nav and nav not in navs:
                hidden.append((key, f"Mobile Access has the {nav} module switched off"))
            elif mobile is not None and mobile.get(tab) == set():
                hidden.append((key, "Mobile Access has this screen switched off"))
            else:
                shown.append(key)

        self.stdout.write(f"  shown : {len(shown)}")
        if hidden:
            self.stdout.write(self.style.WARNING(f"  hidden: {len(hidden)}"))
            for key, why in hidden:
                self.stdout.write(f"    {key:34} {why}")
        else:
            self.stdout.write("  hidden: none — every phone screen is available")

    def _report(self, user, label, model, scopes):
        from api.viewsets import scope_api_queryset

        total = model.objects.count()
        visible = scope_api_queryset(user, model.objects.all()).count()
        hidden = total - visible

        line = f"  {label:38} {visible:>8} {total:>8}"
        if hidden <= 0:
            self.stdout.write(line)
            return

        # Of the hidden rows, how many are hidden because the column the scope
        # reads is empty on the row itself? That is the one cause an admin
        # cannot see from the editor — the group looks correctly configured and
        # the rows still vanish — and it is usually the answer.
        nulls, culprits = _null_scoped_rows(user, model, scopes)
        note = f"  {hidden} hidden"
        if nulls:
            note += f"; {nulls} because their {' / '.join(culprits)} is empty"
            self.stdout.write(self.style.WARNING(line + note))
        else:
            self.stdout.write(line + note)


def _nav_groups():
    from user.access import NAV_GROUPS

    return NAV_GROUPS


def _model_for(label):
    from django.apps import apps

    try:
        app_label, name = label.split(".", 1)
        return apps.get_model(app_label, name)
    except Exception:
        return None


def _null_scoped_rows(user, model, scopes):
    """Rows dropped because a *limiting* scope's column is NULL on the row.

    Only the scopes actually narrowing this user count: one left on "All"
    filters nothing, so a null there hides nothing either. And only ``all``
    mode — ``scope_any`` already keeps a row whose fields are all empty, on
    purpose, so there is nothing to report for those.

    Returns ``(count, paths)``.
    """
    from user.services.scoping import allowed_ids

    # Neither of these hides a NULL: "any" keeps a row whose fields are all
    # empty, and "keep" keeps one whose column is empty. Reporting either would
    # send the admin after a column that is not the problem.
    if scopes.pop("mode", "all") == "any" or scopes.pop("nulls", None) == "keep":
        return 0, []
    scopes.pop("nulls", None)

    q, culprits = Q(), []
    for scope, paths in scopes.items():
        if allowed_ids(user, scope) is None:
            continue                              # left on "All"; filters nothing
        for path in (paths if isinstance(paths, (tuple, list)) else (paths,)):
            q |= Q(**{f"{path}__isnull": True})
            culprits.append(path)
    if not culprits:
        return 0, []
    try:
        return model.objects.filter(q).count(), culprits
    except Exception:
        # A path that cannot be asked about as a null is not worth failing the
        # whole report for.
        return 0, []
