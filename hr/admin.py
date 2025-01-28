"""
configration admin.py in hr modules
"""

from django.contrib import admin
from hr.models import (
    Attendance,
    Employee,
    Designation,
    EmployeeLeave,
    Group,
    LeaveSelectedDate,
    Payroll,
)


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ("id", "name")


@admin.register(Designation)
class DesignationAdmin(admin.ModelAdmin):
    """
    register designations models
    """

    list_display = ("title", "description", "base_salary")


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    """
    register employee models
    """

    list_display = [
        "full_name",
        "title",
        "employee_id",
        "father_name",
        "marital_status",
        "gender",
        "date_of_birth",
        "blood_group",
        "driving_license",
        "qualification",
        "pan_card",
        "aadhar_number",
        "emergency_contact",
        "personal_contact",
        "country",
        "correspondence_address",
        "designation",
        "warehouse",
        "group",
        "salary",
        "salary_type",
        "advance",
        "savings",
        "date_of_joining",
        "report_to",
        "salary_account",
        "bank_name",
        "ifsc_code",
        "branch_name",
        "relieve",
        "image",
    ]


@admin.register(EmployeeLeave)
class EmployeeLeaveAdmin(admin.ModelAdmin):
    """
    register employee leave
    """

    list_display = ("employee", "reason", "leave_type", "status", "created_date")


@admin.register(LeaveSelectedDate)
class LeaveSelectedDateAdmin(admin.ModelAdmin):
    list_display = ("leave_request", "date")


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    """
    register attendance models
    """

    list_display = (
        "employee",
        "date",
        "check_in_time",
        "check_out_time",
        "status",
        "created_date",
    )


@admin.register(Payroll)
class PayrollAdmin(admin.ModelAdmin):
    """
    register payroll models
    """

    list_display = (
        "employee",
        "month",
        "year",
        "gross_salary",
        "deductions",
        "net_salary",
        "total_working_days",
        "payable_salary",
        "created_date",
    )
