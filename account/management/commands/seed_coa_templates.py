from django.core.management.base import BaseCommand, CommandError

from account.coa_seed import seed_coa_templates
from account.models import CoATemplate


class Command(BaseCommand):
    help = "Seed account types, account groups and the standard COA template for every industry."

    def add_arguments(self, parser):
        parser.add_argument(
            "--rebuild",
            action="store_true",
            help="Replace existing template account rows with the current seed definition.",
        )
        parser.add_argument(
            "--only",
            metavar="INDUSTRY",
            help="After seeding, leave only this industry's template active "
                 "(e.g. --only General); the rest are set Inactive and can be "
                 "re-activated in admin later.",
        )

    def handle(self, *args, **options):
        created = seed_coa_templates(rebuild=options["rebuild"])
        if created:
            self.stdout.write(self.style.SUCCESS(f"Seeded templates: {', '.join(created)}"))
        else:
            self.stdout.write("All templates already present; nothing to do (use --rebuild to refresh).")

        if options["only"]:
            industry = options["only"]
            valid = dict(CoATemplate.INDUSTRY_CHOICES)
            if industry not in valid:
                raise CommandError(
                    f"Unknown industry '{industry}'. Choose from: {', '.join(valid)}"
                )
            CoATemplate.objects.filter(industry=industry).update(status="Active")
            deactivated = CoATemplate.objects.exclude(industry=industry).update(status="Inactive")
            self.stdout.write(self.style.SUCCESS(
                f"Only '{industry}' left active ({deactivated} templates set Inactive)."
            ))
