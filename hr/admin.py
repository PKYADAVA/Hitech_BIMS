"""
configration admin.py in hr modules
"""

from django.contrib import admin
from hr.models import Employee, Designation, Attendance


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
        "sector",
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
        "leaves",
        "relieve",
        "image",
    ]


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    """
    register attendance models
    """

    list_display = ("employee", "date", "check_in_time", "check_out_time", "status")
