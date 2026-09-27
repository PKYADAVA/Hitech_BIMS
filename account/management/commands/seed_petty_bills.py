"""Sample bills, so the register has pictures to show.

The attachment columns on the register, the report and the phone all draw the
bill itself, and a database with no bills in it shows an empty strip that
looks exactly like a broken one. This hangs a drawn receipt on each expense
that has none -- a real file, written through the same field the upload
writes, so what the screens read is what an upload would have left.

Every file it writes is named ``sample-bill-*`` and every attachment it makes
is recorded under that name, so ``--undo`` removes precisely those and
nothing else.

    python manage.py seed_petty_bills            # hang a bill on each expense
    python manage.py seed_petty_bills --undo     # take them away again
    python manage.py seed_petty_bills --count 3  # up to three on each
"""
from __future__ import annotations

import io
import random

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction

from account.models import PettyExpense, PettyExpenseAttachment

PREFIX = "sample-bill"

#: Drawn small and dense on purpose. A receipt with a lot of paper around it
#: is legible full size and a white square at the 26px the register draws it,
#: which is the one thing a bill column must not look like.
WIDTH, HEIGHT = 560, 680

#: A band of ink across the top, so a thumbnail reads as a bill before any of
#: its words are legible.
BAND = (30, 41, 59)
PAPER = (252, 251, 247)
INK = (26, 32, 44)
FAINT = (122, 130, 142)
RULE = (214, 218, 224)

FONT_CANDIDATES = [
    ("C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
]


def _fonts():
    """A real typeface where the machine has one, the bitmap default otherwise.

    The default font draws at a fixed dozen pixels whatever size is asked for,
    which on a 560px-wide receipt is a line of ants, and it has no em dash --
    it draws a box where one appears.
    """
    from PIL import ImageFont

    for bold_path, plain_path in FONT_CANDIDATES:
        try:
            return {
                "title": ImageFont.truetype(bold_path, 34),
                "head": ImageFont.truetype(bold_path, 22),
                "body": ImageFont.truetype(plain_path, 21),
                "small": ImageFont.truetype(plain_path, 17),
                "total": ImageFont.truetype(bold_path, 28),
            }
        except OSError:
            continue
    default = ImageFont.load_default()
    return {k: default for k in ("title", "head", "body", "small", "total")}


def _shop_names():
    return [
        "BAHRAICH STATIONERS", "GUPTA TEA STALL", "SHARMA TRADERS",
        "IRFAN WELDING WORKS", "RAM FUEL DEPOT", "SINGH WATER SUPPLY",
        "NEW BHARAT HARDWARE", "AKBARPUR MEDICAL STORE",
    ]


def _draw_bill(expense, index, rng):
    """A receipt, drawn to look like the thing somebody photographed.

    It carries this expense's own number, payee, lines and total, so a seeded
    register reads as a consistent set rather than the same stock picture
    sixteen times.
    """
    from PIL import Image, ImageDraw

    font = _fonts()
    image = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(image)

    # The band, and a torn edge under it: a till slip, not a form.
    draw.rectangle([0, 0, WIDTH, 104], fill=BAND)
    shop = (expense.paid_to_name or rng.choice(_shop_names())).upper()
    draw.text((28, 24), shop[:24], fill=PAPER, font=font["title"])
    draw.text((28, 66), "MAIN ROAD, BAHRAICH · UP", fill=(168, 178, 194),
              font=font["small"])
    for x in range(0, WIDTH, 22):
        draw.polygon([(x, 104), (x + 11, 120), (x + 22, 104)], fill=PAPER)

    def rule(y):
        draw.line([(28, y), (WIDTH - 28, y)], fill=RULE, width=2)

    def pair(y, label, value, f=None, colour=INK):
        draw.text((28, y), label, fill=FAINT, font=font["small"])
        draw.text((180, y - 2), value, fill=colour, font=f or font["body"])

    pair(146, "BILL NO", f"{PREFIX.upper()}-{expense.pk}-{index + 1}")
    pair(184, "DATE", f"{expense.expense_date:%d-%m-%Y}")
    pair(222, "REF", expense.expense_no)
    rule(262)

    draw.text((28, 274), "ITEM", fill=FAINT, font=font["small"])
    draw.text((WIDTH - 150, 274), "AMOUNT", fill=FAINT, font=font["small"])
    y = 306
    for item in expense.items.all()[:5]:
        draw.text((28, y), (item.description or "Item")[:26], fill=INK, font=font["body"])
        draw.text((WIDTH - 150, y), f"{item.amount:,.2f}", fill=INK, font=font["body"])
        y += 36
    rule(y + 8)

    draw.text((28, y + 24), "TOTAL", fill=INK, font=font["head"])
    draw.text((WIDTH - 190, y + 20), f"₹ {expense.net_amount:,.2f}", fill=INK,
              font=font["total"])

    # A stamp, because a paid bill usually carries one, and because it gives
    # the thumbnail a second thing to be at 26px.
    draw.rectangle([WIDTH - 210, y + 92, WIDTH - 40, y + 150], outline=(180, 60, 60),
                   width=3)
    draw.text((WIDTH - 192, y + 108), "PAID", fill=(180, 60, 60), font=font["head"])
    draw.text((28, y + 110), "Paid in cash", fill=FAINT, font=font["small"])
    draw.text((28, HEIGHT - 44), "SAMPLE — seeded for demonstration", fill=FAINT,
              font=font["small"])

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=72)
    return buffer.getvalue()


class Command(BaseCommand):
    help = "Hang sample bill images on petty expenses that have none."

    def add_arguments(self, parser):
        parser.add_argument("--undo", action="store_true",
                            help="Delete the sample bills and their files.")
        parser.add_argument("--count", type=int, default=2, metavar="N",
                            help="At most this many bills per expense (default 2).")
        parser.add_argument("--all", action="store_true",
                            help="Include expenses that already have a bill.")

    @transaction.atomic
    def handle(self, *args, **options):
        if options["undo"]:
            return self._undo()

        expenses = PettyExpense.objects.prefetch_related("items").order_by("-expense_date")
        if not options["all"]:
            expenses = expenses.filter(attachments__isnull=True)
        expenses = list(expenses.distinct())
        if not expenses:
            self.stdout.write(self.style.WARNING(
                "Every expense already carries a bill. Use --all to add more."))
            return

        rng = random.Random(4)          # the same set every time it is run
        made = 0
        for expense in expenses:
            # One bill on most, two on some: a register where every row looks
            # identical teaches nothing about how the column behaves.
            wanted = 1 if rng.random() < 0.6 else max(1, options["count"])
            for index in range(wanted):
                attachment = PettyExpenseAttachment(
                    petty_expense=expense,
                    file_name=f"{PREFIX}-{expense.expense_no}-{index + 1}.jpg",
                    file_type="image/jpeg",
                    uploaded_by=expense.created_by,
                )
                attachment.file.save(
                    f"{PREFIX}-{expense.pk}-{index + 1}.jpg",
                    ContentFile(_draw_bill(expense, index, rng)),
                    save=True,
                )
                made += 1

        self.stdout.write(self.style.SUCCESS(
            f"Hung {made} sample bills on {len(expenses)} expenses. "
            f"`--undo` takes them away again."))

    # ------------------------------------------------------------------

    def _undo(self):
        rows = list(PettyExpenseAttachment.objects.filter(file_name__startswith=PREFIX))
        for attachment in rows:
            # The row and the file both, or the media folder fills up with
            # pictures nothing points at.
            attachment.file.delete(save=False)
            attachment.delete()
        self.stdout.write(self.style.SUCCESS(
            f"Removed {len(rows)} sample bills and their files."))
