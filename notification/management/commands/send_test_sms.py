"""Send a single test SMS from the command line.

Useful for verifying credentials and connectivity in a real environment
without wiring SMS into any view. Respects ``SMS_ENABLED``/``SMS_MOCK``.
"""

from django.core.management.base import BaseCommand, CommandError

from notification.services import get_sms_service


class Command(BaseCommand):
    help = "Send a test SMS to a phone number."

    def add_arguments(self, parser):
        parser.add_argument("phone", help="Recipient phone number.")
        parser.add_argument(
            "--message",
            default="Hi Tech Farms SMS test message.",
            help="Message text to send.",
        )

    def handle(self, *args, **options):
        result = get_sms_service().send_sms(options["phone"], options["message"])
        if result.success:
            self.stdout.write(self.style.SUCCESS(
                f"Sent (status={result.status}, message_id={result.message_id})."
            ))
            return
        raise CommandError(
            f"Send failed (status={result.status}, error={result.error})."
        )
