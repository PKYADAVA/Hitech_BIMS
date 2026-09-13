"""The Action Required widget's own endpoints.

Kept apart from :mod:`alerthub.api`, which serves the bell and the notification
centre, for one reason worth naming: both modules have a "dismiss", and they
mean different things. The bell's clears one alert off one person's list and
touches nobody else; this one closes the alert for the whole operation and
demands a reason. Two verbs that read alike and behave differently should not
share a URL prefix.

Everything here starts from :meth:`Notification.for_user`, like everything in
:mod:`alerthub.api`, so an alert a user cannot see is an alert they cannot
acknowledge, resolve or escalate. The decisions themselves belong to
:mod:`alerthub.workflow`; this module is transport.
"""
from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Prefetch
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import workflow
from .constants import AlertStatus, Priority
from .models import AlertAction, Notification, NotificationRecipient
from .serializers import ActionAlertSerializer, AlertActionSerializer

#: How many alerts the card shows. The spec's number, and the reason for it is
#: sound: a list somebody is expected to work through has to be short enough
#: that they do. The count in the header says how many more there are.
WIDGET_LIMIT = 5


def _fail(error, code=status.HTTP_400_BAD_REQUEST):
    """Turn a validation failure into something the dialog can display.

    ``ValidationError`` carries its messages in a list; handing the raw repr to
    a toast puts brackets and quotes on screen in front of the person who has
    to read it.
    """
    messages = getattr(error, "messages", None) or [str(error)]
    return Response({"ok": False, "error": " ".join(messages)}, status=code)


class ActionRequiredViewSet(viewsets.GenericViewSet):
    """Open exceptions, and the moves that close them."""

    permission_classes = [IsAuthenticated]
    serializer_class = ActionAlertSerializer

    def get_queryset(self):
        user = self.request.user
        mine = Prefetch(
            "recipients",
            queryset=NotificationRecipient.objects.filter(user=user),
            to_attr="_my_recipients",
        )
        return (Notification.objects.for_user(user)
                .select_related("branch", "farm", "warehouse", "org_centre",
                                "status_changed_by")
                .prefetch_related(mine))

    def _rows(self, qs):
        """Attach each row's own recipient, the way the bell's viewset does."""
        rows = list(qs)
        for row in rows:
            mine = getattr(row, "_my_recipients", None)
            row._my_recipient = mine[0] if mine else None
        return rows

    def list(self, request):
        """The card: the most urgent open alerts, and what is behind them.

        The list is capped and the counts are not. A widget that showed five
        alerts and no total would let ninety go unmentioned, and the person
        reading it would have no way to know — which is how a dashboard starts
        being ignored.
        """
        qs = self.get_queryset().needing_action()

        counts = {row["priority"]: row["n"] for row in
                  qs.values("priority").order_by()
                    .annotate(n=Count("id", distinct=True))}
        states = {row["status"]: row["n"] for row in
                  qs.values("status").order_by()
                    .annotate(n=Count("id", distinct=True))}

        rows = self._rows(qs.by_urgency()[:WIDGET_LIMIT])
        total = sum(counts.values())

        return Response({
            "results": ActionAlertSerializer(
                rows, many=True, context={"request": request}).data,
            "summary": {
                "total": total,
                "shown": len(rows),
                "critical": counts.get(Priority.CRITICAL, 0),
                "high": counts.get(Priority.HIGH, 0),
                "medium": counts.get(Priority.MEDIUM, 0),
                "low": counts.get(Priority.LOW, 0),
                "unassigned": states.get(AlertStatus.OPEN, 0),
                "in_progress": states.get(AlertStatus.IN_PROGRESS, 0),
                "acknowledged": states.get(AlertStatus.ACKNOWLEDGED, 0),
                # Closed today, so the footer can say what the operation got
                # through rather than only what is left.
                "resolved_today": self._closed_today(),
            },
        })

    def _closed_today(self) -> int:
        from django.utils import timezone

        return (self.get_queryset()
                .filter(status=AlertStatus.RESOLVED,
                        status_changed_at__date=timezone.localdate())
                .distinct().count())

    # --- the moves ---------------------------------------------------------

    def _act(self, request, pk, fn, **kwargs):
        alert = self.get_queryset().filter(pk=pk).first()
        if alert is None:
            return Response({"ok": False, "error": "No such alert."},
                            status=status.HTTP_404_NOT_FOUND)
        try:
            entry = fn(alert, user=request.user, **kwargs)
        except PermissionDenied as error:
            return _fail(error, status.HTTP_403_FORBIDDEN)
        except ValidationError as error:
            return _fail(error)

        alert.refresh_from_db()
        alert._my_recipient = None
        return Response({
            "ok": True,
            "alert": ActionAlertSerializer(
                alert, context={"request": request}).data,
            "entry": AlertActionSerializer(entry).data,
        })

    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        return self._act(request, pk, workflow.acknowledge,
                         note=request.data.get("note", ""))

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        return self._act(request, pk, workflow.start,
                         note=request.data.get("note", ""))

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        return self._act(request, pk, workflow.resolve,
                         note=request.data.get("note", ""))

    @action(detail=True, methods=["post"])
    def dismiss(self, request, pk=None):
        """Close it without acting — and say why. The reason is the point."""
        return self._act(request, pk, workflow.dismiss,
                         reason=request.data.get("reason", ""))

    @action(detail=True, methods=["post"])
    def reopen(self, request, pk=None):
        return self._act(request, pk, workflow.reopen,
                         note=request.data.get("note", ""))

    # --- escalation --------------------------------------------------------

    @action(detail=True, methods=["get"])
    def supervisors(self, request, pk=None):
        """Who the Notify Supervisor dialog offers, for this alert."""
        alert = self.get_queryset().filter(pk=pk).first()
        if alert is None:
            return Response({"results": []}, status=status.HTTP_404_NOT_FOUND)
        return Response({"results": workflow.supervisor_candidates(alert)})

    @action(detail=True, methods=["post"])
    def notify(self, request, pk=None):
        data = request.data
        # A JSON body hands back the list itself; a form body is a QueryDict,
        # where plain .get() would return only the last checkbox ticked and
        # quietly escalate to one person out of three.
        ids = (data.getlist("user_ids") if hasattr(data, "getlist")
               else data.get("user_ids"))
        return self._act(request, pk, workflow.notify_supervisor,
                         user_ids=ids or [], note=data.get("note", ""))

    # --- the audit trail ---------------------------------------------------

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        """Everything done about one alert, oldest first.

        Oldest first because it is read as a sequence — what happened, then
        what happened next — which is the opposite of how a feed of alerts is
        read.
        """
        alert = self.get_queryset().filter(pk=pk).first()
        if alert is None:
            return Response({"results": []}, status=status.HTTP_404_NOT_FOUND)
        rows = (AlertAction.objects.filter(notification=alert)
                .select_related("actor").order_by("created_at"))
        return Response({"results": AlertActionSerializer(rows, many=True).data})
