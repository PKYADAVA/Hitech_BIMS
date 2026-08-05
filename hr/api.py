"""HR domain — mobile API v1 resources.

Mirrors the web HR module. Simple master data (departments, designations,
shifts, groups) gets full CRUD via the generic form; employees carry a user
link + many fields, and leave/attendance/payroll are workflow/computed records,
so those are exposed **read-only**.

Registered under ``/api/v1/hr/…`` by :func:`register` (called from
``api/urls.py``).
"""
from __future__ import annotations

from rest_framework import serializers

from api.serializers import serializer_factory
from api.viewsets import BaseModelViewSet, register_model

from .models import (
    Attendance,
    Department,
    Designation,
    Employee,
    EmployeeLeave,
    Group,
    LeaveSelectedDate,
    Payroll,
    EmployeeVehicle,
    Shift,
    SupervisorTrip,
    SupervisorTripVisit,
)


class SupervisorTripVisitSerializer(serializer_factory(SupervisorTripVisit)):
    """A farm call as the phone's timeline draws it."""

    duration_label = serializers.CharField(read_only=True)


class SupervisorTripSerializer(serializer_factory(SupervisorTrip)):
    """A trip with its visits nested.

    The timeline is the record as much as the odometer is, and fetching it
    per row would be one request per line of the register.
    """

    visits = SupervisorTripVisitSerializer(many=True, read_only=True)
    employee_name = serializers.SerializerMethodField()

    def get_employee_name(self, obj) -> str:
        return obj.employee.full_name if obj.employee_id else ""


class EmployeeVehicleSerializer(serializer_factory(EmployeeVehicle)):
    """A vehicle as the picker shows it: "UP53 XX 9876 (Bike)"."""

    label = serializers.SerializerMethodField()
    # Optional, because a phone never says whose vehicle it is registering —
    # it is the driver's own. DRF validates before the view's perform_create
    # runs, so leaving it required rejected the request before the owner could
    # be filled in.
    employee = serializers.PrimaryKeyRelatedField(
        queryset=Employee.objects.all(), required=False, allow_null=True)

    def get_label(self, obj) -> str:
        return str(obj)


class EmployeeVehicleViewSet(BaseModelViewSet):
    """A driver's registered vehicles — theirs to manage, theirs alone to see.

    Narrowed the same way trips are: a login that maps to an employee sees
    their own list, and a back-office login sees everything the scope allows.
    Creating one without saying whose it is files it against the asker, which
    is the only case a phone ever has.
    """

    serializer_class = EmployeeVehicleSerializer
    queryset = EmployeeVehicle.objects.all()
    search_fields = ["registration", "nickname"]
    ordering = ["is_retired", "-is_default", "registration"]

    def _mine(self):
        return (Employee.objects.filter(user=self.request.user)
                .values_list("id", flat=True).first())

    def get_queryset(self):
        qs = super().get_queryset()
        mine = self._mine()
        return qs.filter(employee_id=mine) if mine else qs

    def perform_create(self, serializer):
        mine = self._mine()
        owner = serializer.validated_data.get("employee")
        if not mine and not owner:
            # A login that maps to no employee has no "own" list to add to, so
            # it has to say whose vehicle this is. Without this the row went to
            # the database with a null owner and came back as a not-null
            # violation wearing the duplicate-registration message.
            raise serializers.ValidationError({"employee":
                "Your login is not linked to an employee record, so say whose "
                "vehicle this is."})
        self._save_unique(serializer,
                          {"employee_id": mine} if mine and not owner else {})

    def perform_update(self, serializer):
        self._save_unique(serializer, {})

    def _save_unique(self, serializer, extra):
        """Turn the database's duplicate-registration error into a field message.

        The unique constraint is on (employee, registration), and the owner is
        usually not in the payload at all — it comes from the login — so DRF's
        own uniqueness validator cannot see the pair and the clash only
        surfaces as an IntegrityError, i.e. a 500 on a typo.
        """
        from django.db import IntegrityError, transaction

        try:
            with transaction.atomic():
                serializer.save(**extra)
        except IntegrityError as exc:
            # Only claim a duplicate when it actually is one — this used to
            # catch every integrity error and report them all as duplicates,
            # which sent people looking for a vehicle that did not exist.
            if "one_registration_per_employee" in str(exc):
                raise serializers.ValidationError(
                    {"registration": "You have already registered that number."})
            raise serializers.ValidationError(
                {"detail": "That vehicle could not be saved. Check the details "
                           "and try again."})


class SupervisorTripViewSet(BaseModelViewSet):
    """Trips, narrowed to the person asking.

    Someone opens this to find their own day, not the whole company's. The
    scope in API_SCOPES still applies underneath and is what a back-office
    login sees; this is the extra step for a login that maps to an employee
    record, so the list shows their trips and no one else's.

    Deliberately a queryset rule and not a filter the client sends: a phone
    asking nicely for its own rows is not the same as a phone unable to ask for
    anyone else's.
    """

    serializer_class = SupervisorTripSerializer
    queryset = SupervisorTrip.objects.all()
    search_fields = ["trip_no", "registration"]
    ordering = ["-date", "-id"]

    def get_queryset(self):
        qs = super().get_queryset()
        mine = (Employee.objects.filter(user=self.request.user)
                .values_list("id", flat=True).first())
        return qs.filter(employee_id=mine) if mine else qs


def register(router) -> None:
    # --- Master data (full CRUD; list also serves as picker data) -------
    register_model(router, "hr/departments", Department,
                   search_fields=["code", "name"], ordering=["name"])
    register_model(router, "hr/designations", Designation,
                   search_fields=["code", "title"], ordering=["title"])
    register_model(router, "hr/shifts", Shift,
                   search_fields=["name"], ordering=["name"])
    register_model(router, "hr/groups", Group,
                   search_fields=["name"], ordering=["name"])

    # --- Supervisor daily trips ----------------------------------------
    # Writes carry photographs, so they go to hr/trips/save; full CRUD is
    # registered for the register's own View/Edit/Delete.
    # Registered directly rather than through register_model: the queryset has
    # to narrow to the supervisor asking, which is not something the generic
    # registration can express.
    router.register("hr/trips", SupervisorTripViewSet, basename="hr-trips")
    router.register("hr/vehicles", EmployeeVehicleViewSet, basename="hr-vehicles")
    register_model(router, "hr/trip-visits", SupervisorTripVisit,
                   serializer=SupervisorTripVisitSerializer,
                   ordering=["checked_in_at", "id"])

    # --- Employees (read-only: user link + many fields) -----------------
    register_model(router, "hr/employees", Employee, read_only=True,
                   search_fields=["full_name", "pan_card", "aadhar_number"],
                   ordering=["full_name"])

    # --- Transactions (read-only: workflow / computed records) ----------
    register_model(router, "hr/leaves", EmployeeLeave, read_only=True,
                   search_fields=["reason", "leave_type", "status"], cursor=True)
    register_model(router, "hr/attendance", Attendance, read_only=True,
                   search_fields=["status"], cursor=True)
    register_model(router, "hr/payroll", Payroll, read_only=True, cursor=True)

    # --- Line items (read-only; shown inside their parent's detail) -----
    register_model(router, "hr/leave-dates", LeaveSelectedDate, read_only=True)
