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
    """Represents a group an employee belongs to."""

    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class Designation(models.Model):
    """repersently designates an organization"""

    title = models.CharField(max_length=100, unique=True, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    base_salary = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )

    def __str__(self):
        """Returns a string representation of this object with the given fields"""
        return f"{self.title}"


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
    check_in_time = models.TimeField(null=True, blank=True)
    check_out_time = models.TimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=[
            ("Present", "Present"),
            ("Absent", "Absent"),
            ("On Leave", "On Leave"),
            ("First Half", "First Half"),
            ("Second Half", "Second Half"),
        ],
        default="Present",
        null=True,
        blank=True,
    )
    created_date = models.DateTimeField(auto_now_add=True, blank=True, null=True)

    def __str__(self):
        """Returns a string representation of this object with the given options as a string."""
        return f"{self.employee.full_name} - {self.date} ({self.status})"


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
