# pylint: disable=no-member
"""Bootstrap hr.Employee records from a tracking provider's vendor directory.

One-time commissioning helper for environments where HR has no employee
records yet for the people TrackoLap already tracks (each deployment has its
own database — local, staging, production — so this may be needed more than
once). Creates plain ``hr.Employee`` rows (full name + phone only); nothing
provider-specific is stored on them, and they're editable/deletable
afterwards from HR → Employee List like any other employee.

Safe by construction:
    * Read-only by default (``--dry-run`` is implied unless ``--apply`` is
      passed) — running it bare always just previews what would happen.
    * Skips any vendor person whose name already matches an existing
      employee (case-insensitive), so it never creates duplicates.
    * Creates nothing else — no mappings, no tracking rows. Run the
      Employee Mapping card in Tracking Settings afterwards to link vendor
      identities to the employees this command created.

Examples:
    python manage.py seed_employees_from_provider                 # preview
    python manage.py seed_employees_from_provider --apply          # commit
    python manage.py seed_employees_from_provider --provider "TrackWick" --apply
"""

from django.core.management.base import BaseCommand, CommandError

from hr.models import Employee
from tracking.exceptions import TrackingError
from tracking.models import TrackingProvider
from tracking.providers import get_adapter


class Command(BaseCommand):
    help = "Preview/create hr.Employee records from a provider's vendor directory."

    def add_arguments(self, parser):
        parser.add_argument("--provider", default=None,
                            help="Provider id or name (default: first active).")
        parser.add_argument("--apply", action="store_true",
                            help="Actually create the records (default: preview only).")

    def handle(self, *args, **options):
        provider = self._provider(options["provider"])
        try:
            adapter = get_adapter(provider)
            people = adapter.fetch_employees()
        except TrackingError as exc:
            raise CommandError(f"Could not fetch the vendor directory: {exc}") from exc

        if not people:
            self.stdout.write("Vendor directory is empty; nothing to do.")
            return

        existing_names = set(
            Employee.objects.values_list("full_name", flat=True)
        )
        existing_lower = {(name or "").strip().lower() for name in existing_names}

        to_create, already_present = [], []
        for person in people:
            name = (person.name or "").strip()
            if not name:
                self.stdout.write(self.style.WARNING(
                    f"Skipping vendor id {person.external_id}: no name reported."))
                continue
            if name.lower() in existing_lower:
                already_present.append(name)
                continue
            to_create.append(person)

        for name in already_present:
            self.stdout.write(f"exists : {name}")

        if not to_create:
            self.stdout.write(self.style.SUCCESS(
                "\nEvery vendor person already has a matching HR employee. "
                "Nothing to create — go map them in Tracking Settings."
            ))
            return

        self.stdout.write(
            f"\n{'Would create' if not options['apply'] else 'Creating'} "
            f"{len(to_create)} employee(s):"
        )
        for person in to_create:
            digits = "".join(ch for ch in person.phone if ch.isdigit())[-10:]
            phone = int(digits) if len(digits) == 10 else None
            if options["apply"]:
                employee = Employee.objects.create(
                    full_name=person.name.strip(), personal_contact=phone
                )
                self.stdout.write(self.style.SUCCESS(
                    f"  created: #{employee.employee_id} {employee.full_name} "
                    f"phone={phone or '-'}"
                ))
            else:
                self.stdout.write(f"  {person.name}  phone={phone or '-'}")

        if not options["apply"]:
            self.stdout.write(self.style.WARNING(
                "\nPreview only — nothing was created. Re-run with --apply to commit."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                "\nDone. Now go to Tracking Settings → Employee Mapping to link "
                "each vendor identity to these employees."
            ))

    @staticmethod
    def _provider(identifier):
        providers = TrackingProvider.objects.filter(is_active=True)
        if identifier:
            providers = (providers.filter(pk=int(identifier))
                         if str(identifier).isdigit()
                         else providers.filter(name__iexact=identifier))
        provider = providers.order_by("priority", "id").first()
        if provider is None:
            raise CommandError("No matching active provider found.")
        return provider
