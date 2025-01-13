#pylint: disable=no-member
# pylint: disable=logging-fstring-interpolation
"""models configuration for HR Management"""

import random
from django.db import models

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
    sector = models.CharField(max_length=100, blank=True, null=True)
    group = models.CharField(max_length=100, blank=True, null=True)
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
    date_of_joining = models.DateTimeField(null=True, blank=True)
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
            new_id = random.randint(10000, 99999)
            if not Employee.objects.filter(employee_id=new_id).exists():
                return new_id

    def save(self, *args, **kwargs):
        """Override the save method to assign a unique employee ID if not set."""
        if not self.employee_id:
            self.employee_id = self.generate_unique_employee_id()
        super().save(*args, **kwargs)

class EmployeeLeave(models.Model):
    """Represent an employee's leave request"""
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="leave_requests",
        null=True,
        blank=True
    )
    reason = models.CharField(max_length=500, null=True, blank=True)

    def __str__(self):
        """Returns a string representation of this object with the given fields"""
        return f"{self.employee.full_name} - {self.reason}"
    
class EmployeeLeaveSelectedDate(models.Model):
    """Represent an employee's leave request that has been deducted"""
    employee_leave = models.ForeignKey(
        EmployeeLeave,
        on_delete=models.CASCADE,
        related_name="leave_deletions",
        null=True
    )
    date = models.DateField(null=True, blank=True)

    def __str__(self):
        """Returns a string representation of this object with the given fields"""
        return f"{self.employee_leave.employee.full_name} - {self.date}"

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
        ],
        default="Present",
        null=True,
        blank=True,
    )

    def __str__(self):
        """Returns a string representation of this object with the given options as a string."""
        return f"{self.employee.full_name} - {self.date} ({self.status})"
