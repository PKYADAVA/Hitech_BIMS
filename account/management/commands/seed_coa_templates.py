from django.core.management.base import BaseCommand

from account.coa_seed import seed_coa_templates


class Command(BaseCommand):
    help = "Seed account types, account groups and the standard COA template for every industry."

    def add_arguments(self, parser):
        parser.add_argument(
            "--rebuild",
            action="store_true",
            help="Replace existing template account rows with the current seed definition.",
        )

    def handle(self, *args, **options):
        created = seed_coa_templates(rebuild=options["rebuild"])
        if created:
            self.stdout.write(self.style.SUCCESS(f"Seeded templates: {', '.join(created)}"))
        else:
            self.stdout.write("All templates already present; nothing to do (use --rebuild to refresh).")
