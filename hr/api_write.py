"""Supervisor Daily Trip write endpoint for the mobile API v1.

Mounted at ``/api/v1/hr/trips/save[/<id>]``.

Unlike the broiler and inventory write views, this one has no web form to
delegate to — the trip is recorded on the phone and nowhere else, since every
part of it (the photographs, the GPS stamps, the odometer shots) has to be
taken on the road. The ERP end is a report over what the phone recorded. So
the posting rules live here, and the ERP report reads them rather than
duplicating them.

Multipart, because the record is its evidence: start and end photographs with
their own coordinates, and a shot of the odometer at each end.
"""
from __future__ import annotations

import json

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.urls import path
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.viewsets import V1ViewMixin

from .models import SupervisorTrip, SupervisorTripVisit

# Fields the phone may set directly. Everything else on the trip — the number,
# the distance, the status — is derived or driven by an explicit action.
TEXT_FIELDS = ("registration", "remarks", "start_address", "end_address")
CHOICE_FIELDS = ("vehicle_type",)
NUMBER_FIELDS = ("start_odometer", "end_odometer")
GEO_FIELDS = ("start_latitude", "start_longitude", "end_latitude", "end_longitude")
PHOTO_FIELDS = ("start_photo", "end_photo")

# The web tab that governs this feature, for the edit-after-settlement check.
TRIP_TAB = "supervisor_trip_report"


def _int_or_none(value):
    text = str(value or "").strip().replace(",", "")
    return int(text) if text.isdigit() else None


def _dt_or_none(value):
    """An ISO timestamp from the phone as an aware datetime.

    JSON has no datetime, so these arrive as strings; assigning one straight
    onto the model leaves the string in place until something tries to do
    arithmetic on it, and the duration calculation then subtracts two strings.
    """
    text = str(value or "").strip()
    if not text:
        return None
    parsed = parse_datetime(text)
    if parsed is None:
        raise ValidationError({"visits": f"{text!r} is not a timestamp."})
    return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)


def _float_or_none(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


class SupervisorTripWriteView(V1ViewMixin, APIView):
    """POST /api/v1/hr/trips/save[/<id>] — start, update or end a trip.

    ``visits`` arrives as a JSON string alongside the files, because a
    multipart body cannot nest. Each entry replaces the trip's timeline
    wholesale: the phone holds the authoritative list for the day it is
    recording, and merging two partial views of the same route is how a farm
    ends up visited twice.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    @transaction.atomic
    def post(self, request, pk=None):
        data = request.data
        if pk is None:
            trip = SupervisorTrip()
            trip.created_by = request.user
            trip.started_at = timezone.now()
        else:
            trip = SupervisorTrip.objects.filter(pk=pk).first()
            if trip is None:
                raise NotFound("Trip not found.")

        # A settled trip is closed to the supervisor who drove it: the odometer
        # run has been reimbursed against, and letting a later save move the
        # readings would mean the figure approved and the figure on record need
        # not be the same one.
        #
        # It is not closed to whoever settles it. A correction after the fact is
        # a real need — a misread digit, a farm logged against the wrong trip —
        # so anyone the matrix grants Edit on this tab may still update it. The
        # gate is the permission, not the status.
        if trip.pk and trip.status == SupervisorTrip.STATUS_COMPLETED:
            from user.access import user_can

            if not user_can(request.user, TRIP_TAB, "edit"):
                raise ValidationError({
                    "status": "This trip has been ended. Ask someone with edit "
                              "rights on Supervisor Daily Trip to change it."})

        if pk is None:
            trip.employee = self._employee_for(request, data.get("employee"))
        if data.get("date"):
            trip.date = data["date"]

        # A registered vehicle answers both the type and the number, and is
        # copied onto the trip rather than referenced, so the day's record
        # survives the vehicle being corrected or sold later.
        if data.get("vehicle"):
            from .models import EmployeeVehicle

            picked = EmployeeVehicle.objects.filter(
                pk=data["vehicle"], employee=trip.employee).first()
            if picked is None:
                raise ValidationError(
                    {"vehicle": "That vehicle is not registered to this employee."})
            trip.vehicle = picked
            trip.vehicle_type = picked.vehicle_type
            trip.registration = picked.registration

        for field in TEXT_FIELDS + CHOICE_FIELDS:
            if field in data:
                setattr(trip, field, (data.get(field) or "").strip())
        for field in NUMBER_FIELDS:
            if field in data:
                setattr(trip, field, _int_or_none(data.get(field)))
        for field in GEO_FIELDS:
            if field in data:
                setattr(trip, field, _float_or_none(data.get(field)))
        for field in PHOTO_FIELDS:
            upload = request.FILES.get(field)
            if upload:
                setattr(trip, field, upload)
                # Stamp the picture as it lands, so the report can say when the
                # evidence was taken rather than when the log happened to open.
                setattr(trip, f"{field.replace('_photo', '')}_photo_at", timezone.now())

        # Ending is an action, not a field: it stamps the time and closes the
        # log, so a supervisor cannot leave yesterday's trip open and keep
        # adding to it.
        if str(data.get("end_trip", "")).lower() in ("1", "true", "yes"):
            # The closing reading is the other half of the distance, and the
            # distance is what gets reimbursed. Ending without it stores a trip
            # whose km can never be worked out afterwards, because nobody will
            # remember what the odometer said.
            if trip.end_odometer is None:
                raise ValidationError({"end_odometer":
                    "Enter the odometer reading at the end before ending the trip."})
            trip.status = SupervisorTrip.STATUS_COMPLETED
            trip.ended_at = trip.ended_at or timezone.now()

        # A trip cannot be started without its opening evidence. The client
        # blocks this too, but the rule belongs here: a travel claim with no
        # photograph and no pin at the moment it began is a claim with nothing
        # to check it against, and a client is the wrong place to keep that
        # honest.
        if pk is None:
            if not (request.FILES.get("start_photo") or trip.start_photo):
                raise ValidationError({"start_photo":
                    "Take the start trip photo before starting the trip."})
            if trip.start_latitude is None or trip.start_longitude is None:
                raise ValidationError({"start_latitude":
                    "The start photo has no location. Switch location on and "
                    "retake it."})
            if trip.start_odometer is None:
                raise ValidationError({"start_odometer":
                    "Enter the odometer reading at the start."})

        # One open trip at a time. The per-day constraint stops two logs for the
        # same date, but not yesterday's trip left open while today's is
        # started — and an open trip is an odometer run with no closing
        # reading, so a second alongside it makes both unsettleable.
        if pk is None:
            open_trip = (SupervisorTrip.objects
                         .filter(employee=trip.employee,
                                 status=SupervisorTrip.STATUS_IN_PROGRESS)
                         .order_by("-date").first())
            if open_trip is not None:
                raise ValidationError({"date":
                    f"{open_trip.trip_no} ({open_trip.date}) is still open. "
                    "End that trip before starting another."})

        try:
            # "supervisor" here was left over from the rename; the field is
            # `employee` now and is set above, so it validates normally.
            trip.full_clean(exclude=["trip_no", "created_by", "employee"])
            trip.save()
        except DjangoValidationError as exc:
            raise ValidationError(getattr(exc, "message_dict", None) or exc.messages)
        except IntegrityError:
            raise ValidationError({
                "date": "This supervisor already has a trip logged for that day. "
                        "Open that one instead of starting a second."})

        if "visits" in data:
            self._replace_visits(trip, data.get("visits"))

        return Response(
            {"id": trip.id, "trip_no": trip.trip_no, "status": trip.status,
             "distance_km": trip.distance_km},
            status=201 if pk is None else 200)

    def _employee_for(self, request, posted):
        """Whose trip this is — the person logged in, not a choice on a form.

        Someone logs their own day, so taking it from the session is both one
        less thing to get wrong and the only version that cannot be mistyped as
        a colleague. Any employee may be sent out, so the link is simply
        User -> Employee.

        Back-office entry is the exception: someone with Edit on this tab may
        record a trip for a colleague who never got it onto their phone, so an
        explicitly posted employee is honoured for them and refused for
        everyone else.
        """
        from user.access import user_can

        from .models import Employee

        mine = Employee.objects.filter(user=request.user).first()
        if mine is not None:
            return mine
        if posted and user_can(request.user, TRIP_TAB, "edit"):
            found = Employee.objects.filter(pk=posted).first()
            if found is None:
                raise ValidationError({"employee": "No such employee."})
            return found
        raise ValidationError({"employee":
            "Your login is not linked to an employee record, so a trip cannot "
            "be started for you. Ask HR to link it, or pick whose trip this is."})

    def _replace_visits(self, trip, raw):
        try:
            rows = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except json.JSONDecodeError:
            raise ValidationError({"visits": "Could not read the visit list."})
        if not isinstance(rows, list):
            raise ValidationError({"visits": "Visits must be a list."})

        trip.visits.all().delete()
        for row in rows:
            if not row.get("farm"):
                continue
            SupervisorTripVisit.objects.create(
                trip=trip,
                farm_id=row["farm"],
                purpose=(row.get("purpose") or "").strip(),
                checked_in_at=_dt_or_none(row.get("checked_in_at")),
                checked_out_at=_dt_or_none(row.get("checked_out_at")),
                latitude=_float_or_none(row.get("latitude")),
                longitude=_float_or_none(row.get("longitude")),
                remarks=(row.get("remarks") or "").strip(),
            )


def write_urls() -> list:
    """URL patterns for the HR write endpoints."""
    return [
        path("hr/trips/save", SupervisorTripWriteView.as_view(), name="hr-trips-save-new"),
        path("hr/trips/save/<int:pk>", SupervisorTripWriteView.as_view(), name="hr-trips-save"),
    ]
