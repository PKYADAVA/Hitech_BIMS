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
