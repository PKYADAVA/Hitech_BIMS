# pylint: disable=no-member
# pylint: disable=logging-fstring-interpolation
"""models configuration for HR Management"""

import random
from calendar import monthrange
from datetime import date, timedelta
from django.db import models
from django.contrib.auth.models import User
from inventory.models import Warehouse


class Group(models.Model):
    """Represents a group an employee belongs to. Scoped to one branch
    (Warehouse) — a group holds employees of a single branch."""

    name = models.CharField(max_length=100, unique=True)
    warehouse = models.ForeignKey(
        "inventory.Warehouse", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="employee_groups",
        help_text="Branch this group belongs to",
    )

    def __str__(self):
        return self.name


class Department(models.Model):
    """A functional department employees belong to (Broiler Production, Feed
    Store, Transport, …) — separate from Designation (their role/title)."""

    code = models.CharField(max_length=20, unique=True, editable=False, blank=True,
                            help_text="Auto-generated, e.g. DEP-0001")
    name = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.code:
            self.code = f"DEP-{self.pk:04d}"
            super().save(update_fields=["code"])


class Shift(models.Model):
    """A work shift with a start/end time, e.g. General 08:30–17:30."""

    name = models.CharField(max_length=50, unique=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.start_time.strftime('%I:%M %p')} - {self.end_time.strftime('%I:%M %p')})"

    @property
    def timing(self):
        return f"{self.start_time.strftime('%H:%M')} - {self.end_time.strftime('%H:%M')}"


class Designation(models.Model):
    """repersently designates an organization"""

    code = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
        blank=True,
        help_text="Auto-generated code for this designation",
    )
    title = models.CharField(max_length=100, unique=True, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    base_salary = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )

    def __str__(self):
        """Returns a string representation of this object with the given fields"""
        return f"{self.title}"

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.code:
            self.code = f"DSG-{self.pk:04d}"
            super().save(update_fields=["code"])


class Employee(models.Model):
    """Represents an employee with detailed personal and job-related information."""

    user = models.OneToOneField(
        User, on_delete=models.SET_NULL, related_name="employee", null=True
    )
    full_name = models.CharField(max_length=100, blank=True, null=True)
    title = models.CharField(
        max_length=10,
        choices=[("Mr.", "Mr."), ("Ms.", "Ms."), ("Dr.", "Dr.")],
        blank=True,
        null=True,
    )
    employee_id = models.IntegerField(unique=True, blank=True, editable=False)
    father_name = models.CharField(max_length=100, blank=True, null=True)
    marital_status = models.CharField(
        max_length=10,
        choices=[("Married", "Married"), ("Unmarried", "Unmarried")],
        default="Unmarried",
        null=True,
        blank=True,
    )
    gender = models.CharField(
        max_length=10,
        choices=[("Male", "Male"), ("Female", "Female")],
        default="Male",
        null=True,
        blank=True,
    )
    date_of_birth = models.DateField(null=True, blank=True)
    blood_group = models.CharField(max_length=5, blank=True, null=True)
    driving_license = models.BooleanField(default=False)
    driving_license_no = models.CharField(max_length=30, blank=True, null=True)
    qualification = models.CharField(max_length=100, blank=True, null=True)
    pan_card = models.CharField(max_length=20, blank=True, null=True)
    aadhar_number = models.CharField(max_length=12, blank=True, null=True)
    emergency_contact = models.PositiveBigIntegerField(null=True, blank=True)
    personal_contact = models.PositiveBigIntegerField(null=True, blank=True)
    country = models.CharField(max_length=100, default="India", null=True, blank=True)
    correspondence_address = models.TextField(blank=True, null=True)
    designation = models.ForeignKey(
        Designation,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="employees",
    )
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="employees",
    )
    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="employees",
    )
    department = models.ForeignKey(
        "Department",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
    )
    shift = models.ForeignKey(
        "Shift",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
        help_text="Employee's default work shift",
    )
    salary = models.DecimalField(
        max_digits=10, decimal_places=2, default=0.00, null=True, blank=True
    )
    salary_type = models.CharField(
        max_length=10,
        choices=[("Monthly", "Monthly"), ("Hourly", "Hourly")],
        default="Monthly",
        null=True,
        blank=True,
    )
    advance = models.DecimalField(
        max_digits=10, decimal_places=2, default=0.00, null=True, blank=True
    )
    savings = models.DecimalField(
        max_digits=10, decimal_places=2, default=0.00, null=True, blank=True
    )
    date_of_joining = models.DateField(null=True, blank=True)
    report_to = models.CharField(max_length=100, blank=True, null=True)
    salary_account = models.CharField(max_length=20, blank=True, null=True)
    bank_name = models.CharField(max_length=100, blank=True, null=True)
    ifsc_code = models.CharField(max_length=30, blank=True, null=True)
    branch_name = models.CharField(max_length=50, blank=True, null=True)
    relieve = models.BooleanField(default=False, null=True, blank=True)
    image = models.ImageField(upload_to="employee_images/", blank=True, null=True)

    def __str__(self):
        """Returns a string representation of this object with the given fields"""
        return f"{self.full_name} - {self.employee_id}"

    @staticmethod
    def generate_unique_employee_id():
        """Generate a unique 5-digit numeric employee ID."""
        while True:
            new_id = f"{random.randint(1, 99999):05}"
            if not Employee.objects.filter(employee_id=new_id).exists():
                return new_id

    def save(self, *args, **kwargs):
        """Override the save method to assign a unique employee ID if not set."""
        if not self.employee_id:
            self.employee_id = self.generate_unique_employee_id()
        super().save(*args, **kwargs)

    @property
    def daily_wage(self):
        """Calculate daily wage based on salary type."""
        if self.salary_type == "Monthly" and self.salary:
            # Assuming 30 working days in a month
            return self.salary / 30
        elif self.salary_type == "Hourly" and self.salary:
            # Assuming 8 hours per day
            return self.salary / 240  # (8 hours/day * 30 days)
        return 0.00


class EmployeeLeave(models.Model):
    """Represent an employee's leave request"""

    STATUS_CHOICES = [
        ("Pending", "Pending"),
        ("Approved", "Approved"),
        ("Rejected", "Rejected"),
    ]
    LEAVE_TYPE_CHOICES = [
        ("Full Day", "Full Day"),
        ("First Half", "First Half"),
        ("Second Half", "Second Half"),
    ]
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="leave_requests",
        null=True,
        blank=True,
    )
    reason = models.CharField(max_length=500, null=True, blank=True)
    leave_type = models.CharField(
        max_length=15, choices=LEAVE_TYPE_CHOICES, default="Full Day"
    )
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default="Pending",
    )
    created_date = models.DateTimeField(auto_now_add=True, blank=True, null=True)

    def __str__(self):
        """Returns a string representation of this object with the given fields"""
        return f"{self.employee.full_name} - {self.reason}"


class LeaveSelectedDate(models.Model):
    """Represent the selected dates for a specific leave request"""

    leave_request = models.ForeignKey(
        EmployeeLeave, on_delete=models.CASCADE, related_name="selected_dates"
    )
    date = models.DateField()

    def __str__(self):
        return f"Date: {self.date} for Leave Request ID: {self.leave_request.id}"


class Attendance(models.Model):
    """Represent an attendance for a given employee"""

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="attendance_records",
        null=True,
        blank=True,
    )
    date = models.DateField(null=True, blank=True)
    shift = models.ForeignKey(
        "Shift", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="attendance_records",
    )
    check_in_time = models.TimeField(null=True, blank=True)
    check_out_time = models.TimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=[
            ("Present", "Present"),
            ("Absent", "Absent"),
            ("On Leave", "On Leave"),
            ("Half Day", "Half Day"),
            ("First Half", "First Half"),
            ("Second Half", "Second Half"),
        ],
        default="Present",
        null=True,
        blank=True,
    )
    working_minutes = models.IntegerField(default=0, help_text="Computed from check in/out")
    ot_minutes = models.IntegerField(default=0, help_text="Overtime minutes")
    attendance_source = models.CharField(
        max_length=20,
        choices=[("Manual", "Manual"), ("Biometric", "Biometric"), ("Mobile App", "Mobile App")],
        default="Manual",
    )
    remarks = models.CharField(max_length=255, blank=True, default="")
    created_date = models.DateTimeField(auto_now_add=True, blank=True, null=True)

    class Meta:
        unique_together = ("employee", "date")
        ordering = ["-date", "employee_id"]

    def __str__(self):
        """Returns a string representation of this object with the given options as a string."""
        return f"{self.employee.full_name} - {self.date} ({self.status})"

    @property
    def working_hours_display(self):
        """working_minutes as HH:MM (e.g. 549 -> '09:09')."""
        m = self.working_minutes or 0
        return f"{m // 60:02d}:{m % 60:02d}"


class Payroll(models.Model):
    """Represent a payroll for a given employee"""

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="payrolls"
    )
    month = models.IntegerField()
    year = models.IntegerField()
    gross_salary = models.DecimalField(max_digits=10, decimal_places=2)
    deductions = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    net_salary = models.DecimalField(max_digits=10, decimal_places=2)
    total_working_days = models.IntegerField()
    payable_salary = models.DecimalField(max_digits=10, decimal_places=2)
    created_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        """Returns a string representation of this object with the given fields."""
        return f"{self.employee.full_name} - {self.month}/{self.year}"

    def calculate_total_working_days(self):
        """Calculate total working days for the payroll month."""
        # Get the number of days in the month
        days_in_month = monthrange(self.year, self.month)[1]
        start_date = date(self.year, self.month, 1)
        end_date = date(self.year, self.month, days_in_month)

        # Count total weekdays (Monday-Friday) as working days
        total_workable_days = sum(
            1
            for single_day in (
                start_date + timedelta(days=i) for i in range(days_in_month)
            )
            if single_day.weekday() < 5  # 0-4 are Monday to Friday
        )

        # Fetch attendance records
        attendance_records = Attendance.objects.filter(
            employee=self.employee, date__range=(start_date, end_date)
        )

        # Fetch approved leave records
        approved_leaves = LeaveSelectedDate.objects.filter(
            leave_request__employee=self.employee,
            leave_request__status="Approved",
            date__range=(start_date, end_date),
        )

        # Count attendance details
        present_days = attendance_records.filter(status="Present").count()
        first_half_days = attendance_records.filter(status="First Half").count() * 0.5
        second_half_days = attendance_records.filter(status="Second Half").count() * 0.5
        leave_days = approved_leaves.count()  # Only approved leaves count

        # Calculate total working days
        total_working_days = (
            total_workable_days - leave_days + first_half_days + second_half_days
        )
        return max(0, total_working_days)  # Ensure it doesn't go negative


class EmployeeVehicle(models.Model):
    """A vehicle an employee travels on, registered once and picked thereafter.

    Typing a registration number into every day's log is how the same bike
    ends up recorded as three different vehicles — a space here, a missing
    digit there — and a travel claim that cannot be totalled by vehicle. It is
    also just tedious, daily, for a number that does not change.

    Owned by the employee rather than the company: the point is the short list
    a driver picks from, not a fleet register. Someone with two (a bike for the
    round, a car for the long runs) keeps both, and marks the usual one.
    """

    employee = models.ForeignKey(
        "hr.Employee", on_delete=models.CASCADE, related_name="vehicles")
    vehicle_type = models.CharField(max_length=30, default="Two Wheeler")
    registration = models.CharField(max_length=30)
    nickname = models.CharField(
        max_length=40, blank=True,
        help_text="What the driver calls it, when a number is not enough")
    is_default = models.BooleanField(
        default=False, help_text="Chosen for a new trip unless another is picked")
    # Stated as "retired", not "active", so that *unticked* — which is what a
    # blank form posts and what most people leave it as — means a vehicle that
    # is on the road. As `is_active` every newly registered vehicle was born
    # switched off and never appeared in the trip picker.
    is_retired = models.BooleanField(
        default=False, help_text="Tick when sold or off the road; past trips stay readable")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Employee Vehicle"
        verbose_name_plural = "Employee Vehicles"
        ordering = ["is_retired", "-is_default", "registration"]
        constraints = [
            # The same registration twice for one person is the duplicate this
            # exists to prevent.
            models.UniqueConstraint(fields=["employee", "registration"],
                                    name="one_registration_per_employee"),
        ]

    def __str__(self):
        label = self.nickname or self.vehicle_type
        return f"{self.registration} ({label})"

    def save(self, *args, **kwargs):
        self.registration = (self.registration or "").strip().upper()
        super().save(*args, **kwargs)
        # Only one default per person, or "the usual one" means nothing.
        if self.is_default:
            EmployeeVehicle.objects.filter(employee_id=self.employee_id).exclude(
                pk=self.pk).update(is_default=False)


class SupervisorTrip(models.Model):
    """One employee's day on the road, farm to farm.

    Not supervisors only: anyone on the company's payroll may be sent out and
    claim the travel, so the trip belongs to an Employee. The feature is still
    called Supervisor Daily Trip because that is who drives most of them.

    The company pays for this travel and reimburses it against the odometer,
    so the record has to stand up on its own: photographs at the start and the
    end, an odometer reading at each end, and a GPS-stamped check-in at every
    farm visited. Distance is derived from the two readings rather than typed,
    because the number that gets reimbursed should not be a free-text field.

    A trip is open from the moment it starts until it is ended, which is why
    the end fields are all optional — the phone saves the log repeatedly
    through the day and only fills them in on the last save.
    """

    VEHICLE_TWO_WHEELER = "Two Wheeler"
    VEHICLE_CHOICES = [
        (VEHICLE_TWO_WHEELER, "Two Wheeler"),
        ("Four Wheeler", "Four Wheeler"),
        ("Public Transport", "Public Transport"),
        ("Other", "Other"),
    ]
    STATUS_IN_PROGRESS = "In Progress"
    STATUS_COMPLETED = "Completed"
    STATUS_CHOICES = [
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_COMPLETED, "Completed"),
    ]

    trip_no = models.CharField(
        max_length=30, unique=True, editable=False, blank=True,
        help_text="Auto-generated, e.g. TRP-2026-0412")
    date = models.DateField(default=date.today)
    employee = models.ForeignKey(
        "hr.Employee", on_delete=models.PROTECT, related_name="daily_trips",
        help_text="Whose day this is; taken from the login where it maps to one")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                              default=STATUS_IN_PROGRESS)

    vehicle = models.ForeignKey(
        "hr.EmployeeVehicle", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="trips", help_text="Picked from the driver's registered vehicles")
    # Copied from the vehicle at save time, and kept. A trip is a claim about a
    # particular day: if the registration is later corrected, or the vehicle
    # sold and deleted, the day's record must still say what was driven.
    vehicle_type = models.CharField(max_length=30, choices=VEHICLE_CHOICES,
                                    default=VEHICLE_TWO_WHEELER)
    registration = models.CharField(max_length=30, blank=True,
                                    help_text="Registration as it stood on the day")

    start_odometer = models.PositiveIntegerField(null=True, blank=True, help_text="Km at the start")
    end_odometer = models.PositiveIntegerField(null=True, blank=True, help_text="Km at the end")
    distance_km = models.PositiveIntegerField(
        default=0, editable=False,
        help_text="End minus start; stored so reports can total it in the database")

    # Evidence. One shot at each end, and the odometer has to be in it: the
    # reading is what the travel is reimbursed against, and the photo carries
    # its own coordinates so the reading is tied to where it was taken. There
    # is deliberately no separate odometer picture — two controls for one piece
    # of evidence only invites half of each being filled in.
    start_photo = models.ImageField(upload_to="trips/start/", null=True, blank=True)
    end_photo = models.ImageField(upload_to="trips/end/", null=True, blank=True)
    # When each picture was actually taken. Not the same as started_at /
    # ended_at: a trip opens when the log is created, which may be before the
    # supervisor is at the vehicle, and it can be ended from the register long
    # after the closing shot. The stamp on the evidence has to be the
    # evidence's own, or the report vouches for the wrong moment.
    start_photo_at = models.DateTimeField(null=True, blank=True)
    end_photo_at = models.DateTimeField(null=True, blank=True)
    # The pin resolved to an address, looked up when the photo is taken. A
    # coordinate pair tells a reviewer nothing without opening a map; the
    # written form is what makes a row readable at a glance, and printable.
    start_address = models.CharField(max_length=255, blank=True)
    end_address = models.CharField(max_length=255, blank=True)
    start_latitude = models.FloatField(null=True, blank=True)
    start_longitude = models.FloatField(null=True, blank=True)
    end_latitude = models.FloatField(null=True, blank=True)
    end_longitude = models.FloatField(null=True, blank=True)

    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    remarks = models.TextField(blank=True)

    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="supervisor_trips")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Supervisor Daily Trip"
        verbose_name_plural = "Supervisor Daily Trips"
        ordering = ["-date", "-id"]
        # One trip per person per day: a second open log for the same day would
        # split the odometer run and double-count the distance claimed.
        constraints = [
            models.UniqueConstraint(fields=["employee", "date"],
                                    name="one_trip_per_employee_per_day"),
        ]

    def __str__(self):
        return self.trip_no or f"(unsaved trip for {self.employee})"

    @property
    def is_open(self):
        return self.status == self.STATUS_IN_PROGRESS

    def clean(self):
        from django.core.exceptions import ValidationError

        # A lower end reading means one of the two was mistyped. Letting it
        # through would store a distance of zero and quietly under-reimburse.
        if (self.start_odometer is not None and self.end_odometer is not None
                and self.end_odometer < self.start_odometer):
            raise ValidationError(
                {"end_odometer": "End odometer cannot be lower than the start."})

    def save(self, *args, **kwargs):
        if self.start_odometer is not None and self.end_odometer is not None:
            self.distance_km = max(self.end_odometer - self.start_odometer, 0)
        else:
            self.distance_km = 0
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.trip_no:
            self.trip_no = self._next_no(self.date)
            super().save(update_fields=["trip_no"])

    @classmethod
    def _next_no(cls, on_date=None):
        """TRP-<year>-<serial>, the serial running within the calendar year.

        Tolerates a string date. Django only coerces a field on ``full_clean``
        or on the way to the database, so anything that assigns
        ``trip.date = "2026-08-04"`` and saves — an importer, a shell, a
        management command — reaches here with a ``str`` and would otherwise
        fail asking it for ``.year``.
        """
        if isinstance(on_date, str):
            from django.utils.dateparse import parse_date

            on_date = parse_date(on_date)
        current = on_date or date.today()
        prefix = f"TRP-{current.year}-"
        highest = 0
        for existing in cls.objects.filter(trip_no__startswith=prefix).values_list(
                "trip_no", flat=True):
            tail = (existing or "").rsplit("-", 1)[-1]
            if tail.isdigit():
                highest = max(highest, int(tail))
        return f"{prefix}{highest + 1:04d}"


class SupervisorTripVisit(models.Model):
    """One farm called at during a trip.

    Check-in is GPS-stamped at the farm gate rather than typed later, which is
    the difference between a record of a visit and a claim of one. Duration is
    derived from the two timestamps for the same reason the trip's distance is
    derived from the odometer.
    """

    trip = models.ForeignKey(SupervisorTrip, on_delete=models.CASCADE,
                             related_name="visits")
    farm = models.ForeignKey("broiler.BroilerFarm", on_delete=models.PROTECT,
                             related_name="supervisor_visits")
    purpose = models.CharField(max_length=120, blank=True,
                               help_text="Why the farm was called at")
    checked_in_at = models.DateTimeField(null=True, blank=True)
    checked_out_at = models.DateTimeField(null=True, blank=True)
    duration_minutes = models.PositiveIntegerField(
        default=0, editable=False, help_text="Derived from check-in/check-out")
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    remarks = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "Trip Farm Visit"
        verbose_name_plural = "Trip Farm Visits"
        ordering = ["checked_in_at", "id"]

    def __str__(self):
        return f"{self.farm} on {self.trip}"

    @property
    def duration_label(self):
        """"1h 15m", as the phone's timeline shows it."""
        if not self.duration_minutes:
            return ""
        hours, minutes = divmod(self.duration_minutes, 60)
        return f"{hours}h {minutes}m" if hours else f"{minutes}m"

    def save(self, *args, **kwargs):
        if self.checked_in_at and self.checked_out_at:
            seconds = (self.checked_out_at - self.checked_in_at).total_seconds()
            self.duration_minutes = max(int(seconds // 60), 0)
        else:
            self.duration_minutes = 0
        super().save(*args, **kwargs)
