from django.core.management.base import BaseCommand

from account.services.auto_posting import _existing_voucher, post_document


class Command(BaseCommand):
    help = (
        "Post (or re-post) vouchers for business documents. By default only "
        "documents without a posted voucher are processed; --all re-checks "
        "every document and replaces vouchers whose amounts changed."
    )

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true",
                            help="Re-check documents that already have a voucher.")

    def handle(self, *args, **options):
        from hatchery.models import ChickSale, EggPurchase

        posted = skipped = failed = 0
        for model in (EggPurchase, ChickSale):
            for document in model.objects.all().order_by("date", "id"):
                if not options["all"] and _existing_voucher(document):
                    skipped += 1
                    continue
                voucher = post_document(document)
                if voucher:
                    posted += 1
                    self.stdout.write(f"  {document} -> {voucher.voucher_no}")
                else:
                    failed += 1
                    self.stderr.write(f"  {document} -> FAILED (see logs)")
        self.stdout.write(self.style.SUCCESS(
            f"Done: {posted} posted, {skipped} already posted, {failed} failed."
        ))
