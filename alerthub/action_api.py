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
from django.db.models import Prefetch
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

#: At most this many rows from any one rule.
#:
#: Without it the card is whatever is worst, and "worst" is usually eighteen
#: instances of one thing. On real data every visible row was Negative Stock,
#: which is a true answer to "what is most urgent" and a useless answer to
#: "what needs my attention" — the three High alerts and everything else sat
#: invisible behind a "22 more open" link.
PER_RULE_LIMIT = 2

#: How far down the urgency order to look for that spread. Deep enough to get
#: past a flood of one rule, shallow enough that the widget is never reading
#: the whole table. Past it, the card shows what the window held — which is
#: the same thing it showed before this cap existed.
SPREAD_WINDOW = WIDGET_LIMIT * 10


def one_per_problem(rows):
    """Drop rows that are another sighting of a problem already in the list.

    ``dedupe_key`` names the subject, so two rows carrying the same one are the
    same problem noticed twice. The engine will not raise those any more, but
    every farm still carries the ones raised before it learned not to — ten
    real problems arriving as twenty-nine alerts on the database this was
    written against.

    Showing a problem twice was never useful, whenever the rows were written.
    Rows with no key are left alone: there is nothing to say they are copies
    of anything.
    """
    seen, out = set(), []
    for row in rows:
        if row.dedupe_key:
            if row.dedupe_key in seen:
                continue
            seen.add(row.dedupe_key)
        out.append(row)
    return out


def spread(rows, limit=WIDGET_LIMIT, per_rule=PER_RULE_LIMIT):
    """Pick ``limit`` alerts without letting one rule have them all.

    Two passes. The first takes up to ``per_rule`` from each rule in urgency
    order; the second fills any slots still empty from what the first pass
    held back, so a farm whose only problem really is eighteen negative stock
    lines still gets a full card rather than two rows and a lot of white space.

    The result is re-sorted at the end. Filling from the held-back rows appends
    them after rows that may be less urgent, and a Critical sitting below a
    High reads as a sorting bug even when the selection above it was right.
    """
    picked, held, seen = [], [], {}
    for row in rows:
        if len(picked) >= limit:
            break
        taken = seen.get(row.rule_key, 0)
        if taken < per_rule:
            picked.append(row)
            seen[row.rule_key] = taken + 1
        else:
            held.append(row)

    for row in held:
        if len(picked) >= limit:
            break
        picked.append(row)

    # ``_rank`` is annotated by by_urgency(); the fallback keeps this usable on
    # a plain list, which is how it is tested.
    picked.sort(key=lambda r: (getattr(r, "_rank", 99), -r.created_at.timestamp()))
    return picked


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

        counts, states, by_rule = self._problem_counts(qs)
        rows = self._rows(spread(one_per_problem(qs.by_urgency()[:SPREAD_WINDOW])))
        total = sum(counts.values())

        shown_per_rule = {}
        for row in rows:
            shown_per_rule[row.rule_key] = shown_per_rule.get(row.rule_key, 0) + 1

        # Only the last row of each rule carries the count. Both rows of a
        # capped pair are standing in for the same sixteen others, and saying
        # "+16 more like this" twice reads as thirty-two.
        last_of_rule = {}
        for index, row in enumerate(rows):
            row._more_like_this = 0
            last_of_rule[row.rule_key] = index
        for key, index in last_of_rule.items():
            rows[index]._more_like_this = max(
                0, by_rule.get(key, 0) - shown_per_rule[key])

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

    def _problem_counts(self, qs):
        """Counts of open *problems*, not of rows.

        A problem noticed on three mornings is three rows and one thing to do
        about it, so counting rows would have the card announce twenty-nine
        when ten people-hours of work exist. Everything the header and footer
        show is counted this way, so "22 more open" means twenty-two more
        problems and the link under it leads to that many distinct subjects.

        One query returning distinct (key, priority, status, rule) tuples —
        bounded by the number of open problems rather than by the number of
        rows, which is the point. A row with no key stands for itself and is
        counted by id.
        """
        counts, states, by_rule, seen = {}, {}, {}, set()
        fields = ("dedupe_key", "priority", "status", "rule_key", "id")
        for key, priority, state, rule_key, pk in (
                qs.values_list(*fields).order_by().distinct()):
            identity = key or "id:%s" % pk
            if identity in seen:
                continue
            seen.add(identity)
            counts[priority] = counts.get(priority, 0) + 1
            states[state] = states.get(state, 0) + 1
            by_rule[rule_key] = by_rule.get(rule_key, 0) + 1
        return counts, states, by_rule

    def _closed_today(self) -> int:
        from django.utils import timezone

        # Distinct subjects again, so settling one problem that arrived as
        # three rows reads as one thing got through, not three.
        rows = (self.get_queryset()
                .filter(status=AlertStatus.RESOLVED,
                        status_changed_at__date=timezone.localdate())
                .values_list("dedupe_key", "id").order_by().distinct())
        return len({key or "id:%s" % pk for key, pk in rows})

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
