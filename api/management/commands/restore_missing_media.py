"""Stand in for files the database still points at but the disk has lost.

A missing file is not a missing record: the row knows the farm, the date, the
payee and the filename -- only the bytes are gone. Left alone it shows as a
broken image or a 404 on a page that plainly has a photograph, which reads as
a bug in the page rather than as what it is.

This writes a marker at each lost key, saying so in as many words: the
filename it stood for, and that the record itself is intact. It is deliberately
not a blank image. Anyone who opens one must be able to tell at a glance that
the original is gone, not think they are looking at it.

Nothing in the database changes. A real copy, if one turns up, overwrites the
marker at the same key and everything points at it again.

    python manage.py restore_missing_media --dry-run   # what is lost, and where
    python manage.py restore_missing_media             # write the markers
    python manage.py restore_missing_media --clear     # empty the fields instead
"""
from __future__ import annotations

import io

from django.apps import apps
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db.models import FileField

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}

WIDTH, HEIGHT = 720, 560
PAPER = (241, 243, 246)
INK = (71, 85, 105)
MARK = (185, 28, 28)

FONT_CANDIDATES = [
    ("C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
]


def _fonts():
    from PIL import ImageFont

    for bold, plain in FONT_CANDIDATES:
        try:
            return {
                "title": ImageFont.truetype(bold, 34),
                "body": ImageFont.truetype(plain, 20),
                "small": ImageFont.truetype(plain, 16),
            }
        except OSError:
            continue
    default = ImageFont.load_default()
    return {k: default for k in ("title", "body", "small")}


def _marker_image(key: str, where: str) -> bytes:
    from PIL import Image, ImageDraw

    font = _fonts()
    image = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(image)

    draw.rectangle([24, 24, WIDTH - 24, HEIGHT - 24], outline=MARK, width=3)
    draw.text((56, 64), "FILE MISSING", fill=MARK, font=font["title"])
    draw.text((56, 124), "The record is intact. The file it points at is not.",
              fill=INK, font=font["body"])

    draw.text((56, 200), "WAS", fill=(148, 163, 184), font=font["small"])
    name = key.rsplit("/", 1)[-1]
    draw.text((56, 224), name[:44], fill=INK, font=font["body"])
    draw.text((56, 268), "AT", fill=(148, 163, 184), font=font["small"])
    for i in range(0, len(key), 52):
        draw.text((56, 292 + (i // 52) * 26), key[i:i + 52], fill=INK, font=font["small"])
    draw.text((56, 380), "ON", fill=(148, 163, 184), font=font["small"])
    draw.text((56, 404), where, fill=INK, font=font["small"])

    draw.text((56, HEIGHT - 76),
              "Put the real file back at this path and it will be used instead.",
              fill=(148, 163, 184), font=font["small"])

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _marker_pdf(key: str, where: str) -> bytes:
    """A one-page PDF saying the same thing, hand-built.

    Small enough to write without a PDF library, and every reader opens it.
    """
    text = (f"FILE MISSING. The record is intact; the file it points at is not. "
            f"Was: {key.rsplit('/', 1)[-1]}. At: {key}. On: {where}.")
    stream = (f"BT /F1 12 Tf 48 760 Td ({text[:90]}) Tj 0 -20 Td "
              f"({text[90:180]}) Tj 0 -20 Td ({text[180:270]}) Tj ET")
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.StringIO()
    out.write("%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n{body}\nendobj\n")
    start = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n")
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n")
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
              f"startxref\n{start}\n%%EOF\n")
    return out.getvalue().encode("latin-1", errors="replace")


class Command(BaseCommand):
    help = "Write a visible marker where a stored file has gone missing."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="List what is missing and change nothing.")
        parser.add_argument("--clear", action="store_true",
                            help="Empty the field instead of writing a marker.")

    def handle(self, *args, **options):
        lost = []
        for model in apps.get_models():
            fields = [f for f in model._meta.get_fields() if isinstance(f, FileField)]
            if not fields:
                continue
            for obj in model.objects.all().iterator():
                for field in fields:
                    value = getattr(obj, field.name, None)
                    if not value or not value.name:
                        continue
                    try:
                        there = value.storage.exists(value.name)
                    except Exception:
                        there = False
                    if not there:
                        lost.append((obj, field, value.name))

        if not lost:
            self.stdout.write(self.style.SUCCESS(
                "Every stored file the database points at is on disk."))
            return

        if options["dry_run"]:
            self.stdout.write(f"{len(lost)} files are missing:")
            for obj, field, key in lost:
                self.stdout.write(f"  {obj._meta.label}.{field.name} #{obj.pk}  {key}")
            return

        written, cleared = 0, 0
        # Rows often share a key -- four daily entries can point at the same
        # sample photograph. Writing per row would leave three files nothing
        # points at, because storage renames rather than overwrites.
        done: set[str] = set()
        for obj, field, key in lost:
            where = f"{obj._meta.label} #{obj.pk} ({field.name})"
            value = getattr(obj, field.name)
            if options["clear"]:
                setattr(obj, field.name, "")
                obj.save(update_fields=[field.name])
                cleared += 1
                continue
            if key in done:
                continue
            suffix = ("." + key.rsplit(".", 1)[-1].lower()) if "." in key else ""
            body = (_marker_pdf(key, where) if suffix == ".pdf"
                    else _marker_image(key, where))
            # Written at the key the row already holds, so nothing in the
            # database moves and a real copy can replace it in place.
            saved = value.storage.save(key, ContentFile(body))
            if saved != key:
                # Storage refused the name and chose its own: the marker would
                # sit where nothing points. Put it back where it belongs.
                value.storage.delete(saved)
                with value.storage.open(key, "wb") as fh:
                    fh.write(body)
            done.add(key)
            written += 1

        if written:
            self.stdout.write(self.style.SUCCESS(
                f"Wrote {written} markers. Each says which file was lost and where."))
        if cleared:
            self.stdout.write(self.style.SUCCESS(f"Cleared {cleared} fields."))
