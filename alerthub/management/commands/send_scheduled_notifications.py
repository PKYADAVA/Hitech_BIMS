"""Send the notifications whose scheduled hour has arrived.

Run this on a timer — the project already drives ``sync_tracking`` from Windows
Task Scheduler, and this belongs on the same footing. Every five minutes is
ample: the page only offers minute precision and a message that goes out four
minutes late is not a message that failed.

    python manage.py send_scheduled_notifications

Safe to overlap. :func:`alerthub.dispatch.send_due` claims its rows by flipping
them to ``SENDING`` in one UPDATE before doing any work, so a second run that
starts while the first is still going finds nothing left to claim rather than
sending everything twice.

**Without this command scheduled, "Schedule for Later" never fires.** Nothing
in a web request can wake up at 6pm on its own. The Send Notification page says
so where a message is scheduled, so the gap is visible rather than discovered a
day later by whoever was waiting for it.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from alerthub.dispatch import send_due
from alerthub.models import OutgoingNotification


class Command(BaseCommand):
    help = "Dispatch scheduled notifications that are now due."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit", type=int, default=200,
            help="Most messages to send in one run (default 200).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="List what is due without sending anything.",
        )

    def handle(self, *args, **options):
        now = timezone.now()

        if options["dry_run"]:
            due = (OutgoingNotification.objects
                   .filter(status=OutgoingNotification.SCHEDULED, send_at__lte=now)
                   .order_by("send_at")[:options["limit"]])
            if not due:
                self.stdout.write("Nothing due.")
                return
            for row in due:
                self.stdout.write(
                    f"  #{row.pk}  {timezone.localtime(row.send_at):%d %b %H:%M}  "
                    f"{row.title}"
                )
            self.stdout.write(self.style.WARNING(
                f"{len(due)} due — nothing sent (--dry-run)."
            ))
            return

        sent = send_due(now=now, limit=options["limit"])
        if not sent:
            self.stdout.write("Nothing due.")
            return

        for row in sent:
            line = (f"#{row.pk}  {row.get_status_display():<15} "
                    f"{row.success_count}/{row.recipient_count}  {row.title}")
            if row.status == OutgoingNotification.SENT:
                self.stdout.write(self.style.SUCCESS(line))
            elif row.status == OutgoingNotification.PARTIAL:
                self.stdout.write(self.style.WARNING(f"{line} — {row.error}"))
            else:
                self.stderr.write(self.style.ERROR(f"{line} — {row.error}"))

        ok = sum(1 for r in sent if r.status == OutgoingNotification.SENT)
        self.stdout.write(self.style.SUCCESS(
            f"Dispatched {len(sent)} scheduled notification(s); {ok} fully sent."
        ))
