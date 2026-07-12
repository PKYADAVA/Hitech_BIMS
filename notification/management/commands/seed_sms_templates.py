"""Seed editable SMS templates from the built-in catalogue.

Idempotent: missing templates are created; existing rows are left untouched so
admin edits are preserved. Pass ``--force`` to reset every row back to the
catalogue body/name/description.
"""

from django.core.management.base import BaseCommand

from notification.models import SmsTemplate
from notification.templates_catalog import DEFAULT_TEMPLATES


class Command(BaseCommand):
    help = "Create or refresh SMS templates from the built-in catalogue."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite existing templates with catalogue defaults.",
        )

    def handle(self, *args, **options):
        created, updated, skipped = 0, 0, 0
        for template in DEFAULT_TEMPLATES:
            defaults = {
                "module": template.module,
                "name": template.name,
                "body": template.body,
                "description": template.description,
                "dlt_template_id": template.dlt_template_id,
            }
            obj, was_created = SmsTemplate.objects.get_or_create(
                key=template.key, defaults=defaults,
            )
            if was_created:
                created += 1
            elif options["force"]:
                for attr, value in defaults.items():
                    setattr(obj, attr, value)
                obj.save(update_fields=[*defaults.keys(), "updated_at"])
                updated += 1
            else:
                skipped += 1

        self.stdout.write(self.style.SUCCESS(
            f"SMS templates seeded: {created} created, {updated} updated, {skipped} skipped."
        ))
