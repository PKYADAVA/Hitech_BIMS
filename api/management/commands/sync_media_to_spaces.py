"""Copy files already sitting in the local ``media/`` folder up to their
configured storage (DigitalOcean Spaces when ``USE_SPACES=True``).

Each file is uploaded through the *field's own* storage, so it lands in the
right place automatically — public images under the ``media/`` prefix, sensitive
documents under the private ``private/`` prefix — each keeping its field's
``upload_to`` sub-folder (e.g. ``farmer/pan/``, ``farm/cheques/``). The object
key (the value stored in the DB) is preserved, so existing records keep working.

Usage:
    python manage.py sync_media_to_spaces --dry-run   # preview, change nothing
    python manage.py sync_media_to_spaces             # upload missing files
    python manage.py sync_media_to_spaces --overwrite # replace remote copies too
"""

from django.apps import apps
from django.conf import settings
from django.core.files import File
from django.core.files.storage import FileSystemStorage
from django.core.management.base import BaseCommand
from django.db import models


class Command(BaseCommand):
    help = "Upload existing local media/ files into their configured (Spaces) storage."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List what would be uploaded without changing anything.",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Re-upload even when the target storage already has the file.",
        )

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        overwrite = opts["overwrite"]

        if not getattr(settings, "USE_SPACES", False):
            self.stdout.write(
                self.style.WARNING(
                    "USE_SPACES is not enabled — the field storages point at the "
                    "local filesystem, so this command has nothing to move. Enable "
                    "Spaces first, then run it again."
                )
            )
            return

        # Read the source bytes from the on-disk media root explicitly, since the
        # field storages now resolve to Spaces.
        local = FileSystemStorage(location=settings.MEDIA_ROOT)

        uploaded = skipped = missing = renamed = 0

        for model in apps.get_models():
            if model._meta.proxy:  # proxies share the concrete model's fields
                continue
            file_fields = [
                f for f in model._meta.get_fields() if isinstance(f, models.FileField)
            ]
            if not file_fields:
                continue

            for obj in model._base_manager.all().iterator():
                for field in file_fields:
                    filefield = getattr(obj, field.name, None)
                    name = getattr(filefield, "name", "") or ""
                    if not name:
                        continue

                    target = filefield.storage
                    label = f"{model._meta.label}.{field.name} -> {name}"

                    if not local.exists(name):
                        missing += 1
                        self.stdout.write(self.style.WARNING(f"  missing locally: {label}"))
                        continue

                    if not overwrite and target.exists(name):
                        skipped += 1
                        continue

                    if dry:
                        self.stdout.write(f"  would upload: {label}")
                        uploaded += 1
                        continue

                    if overwrite and target.exists(name):
                        target.delete(name)

                    with local.open(name, "rb") as fh:
                        saved = target.save(name, File(fh))

                    if saved != name:
                        # Target renamed to avoid a collision — keep the DB pointer
                        # in sync so the record still resolves its file.
                        setattr(obj, field.name, saved)
                        obj.save(update_fields=[field.name])
                        renamed += 1
                        self.stdout.write(
                            self.style.WARNING(f"  uploaded (renamed): {name} -> {saved}")
                        )
                    else:
                        self.stdout.write(f"  uploaded: {label}")
                    uploaded += 1

        summary = (
            f"Done. uploaded={uploaded} skipped(existing)={skipped} "
            f"missing_locally={missing} renamed={renamed}"
        )
        self.stdout.write(self.style.SUCCESS(summary + (" (dry-run)" if dry else "")))
