"""What the phone tells the ERP about work it is still holding, and the rule
that stops two people's counts of the same shed overwriting each other.

The queue itself lives on the handset — that is the whole point of it — so the
ERP can only know what a device is sitting on if the device says. That is all
the heartbeat is: the latest word from one phone, kept as a snapshot for the
administrator's monitor.
"""
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import DeviceSyncState


class SyncHeartbeatSerializer(serializers.Serializer):
    """The counts as the device itself keeps them.

    Trusted as a report, never as an instruction: nothing here changes a
    transaction. The worst a wrong number does is mislead the monitor, and the
    entries are still on the device and still have to arrive on their own.
    """

    device_id = serializers.CharField(max_length=120)
    pending = serializers.IntegerField(min_value=0, default=0)
    failed = serializers.IntegerField(min_value=0, default=0)
    conflicts = serializers.IntegerField(min_value=0, default=0)
    synced = serializers.IntegerField(min_value=0, default=0)
    oldest_pending_at = serializers.DateTimeField(required=False, allow_null=True)
    last_sync_at = serializers.DateTimeField(required=False, allow_null=True)
    app_version = serializers.CharField(max_length=40, required=False, allow_blank=True)
    platform = serializers.CharField(max_length=20, required=False, allow_blank=True)


class SyncHeartbeatView(APIView):
    """POST /api/v1/sync/heartbeat — one device reporting its queue.

    Called after every sync run and when the app opens, so the monitor reflects
    the last time the phone could reach us rather than the last time it filed
    something. Deliberately cheap and deliberately not required: a phone that
    never calls this still syncs perfectly well, it is just invisible to the
    monitor until it does.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(request=SyncHeartbeatSerializer, responses={200: None})
    def post(self, request):
        form = SyncHeartbeatSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        data = form.validated_data
        DeviceSyncState.objects.update_or_create(
            user=request.user,
            device_id=data["device_id"][:120],
            defaults={
                "pending": data.get("pending", 0),
                "failed": data.get("failed", 0),
                "conflicts": data.get("conflicts", 0),
                "synced": data.get("synced", 0),
                "oldest_pending_at": data.get("oldest_pending_at"),
                "last_sync_at": data.get("last_sync_at"),
                "app_version": data.get("app_version", "")[:40],
                "platform": data.get("platform", "")[:20],
            },
        )
        return Response({"received_at": timezone.now()}, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------

class SyncConflict(Exception):
    """Raised when accepting a write would overwrite somebody else's figure.

    Not an error in the ordinary sense: both numbers are real, and somebody has
    to decide. The API turns this into a 409 the phone can show, rather than
    silently taking the newer one — which in practice means taking whichever
    handset happened to find signal last.
    """

    def __init__(self, message, fields, server_id=None):
        super().__init__(message)
        self.message = message
        self.fields = fields
        self.server_id = server_id

    def as_response(self):
        return Response(
            {"code": "sync_conflict", "message": self.message,
             "fields": {},
             "conflict": {"message": self.message, "fields": self.fields,
                          "server_id": self.server_id}},
            status=status.HTTP_409_CONFLICT)


#: Payload flag set by the Sync Center's "Accept mine" — the user has seen both
#: figures and chosen theirs, so the check is not run again.
OVERRIDE_FLAG = "__resolve_conflict"
OVERRIDE_VALUE = "accept_offline"


def wants_override(payload):
    return str(payload.get(OVERRIDE_FLAG, "")) == OVERRIDE_VALUE


def check_daily_entry_conflict(payload, existing):
    """Whether a queued Daily Entry disagrees with one already filed.

    A supervisor records ten dead birds in Shed 2 on the 8th; by the time their
    phone finds signal the office has already entered seven for the same shed
    and day. Both are somebody's count. Overwriting is not a resolution — it
    loses a real number and nobody is told — so the phone is handed both
    figures and the choice.

    Only the fields worth arguing about are compared. A difference in, say, the
    recorded feed brand is a correction; a difference in mortality is a
    disagreement about what happened in the shed.
    """
    if existing is None or wants_override(payload):
        return None

    compared = (
        ("mortality", "Mortality"),
        ("culls", "Culls"),
        ("avg_weight", "Average Weight"),
    )
    differences = []
    for field, label in compared:
        if field not in payload:
            continue
        theirs = getattr(existing, field, None)
        mine = payload.get(field)
        if theirs is None or mine in (None, ""):
            continue
        if str(theirs).strip() != str(mine).strip():
            differences.append({"field": field, "label": label,
                                "server": str(theirs), "local": str(mine)})
    if not differences:
        return None
    return SyncConflict(
        "This day has already been recorded for this batch with different figures.",
        differences,
        server_id=existing.pk,
    )
