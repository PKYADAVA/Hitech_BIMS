"""
configration admin.py in hr modules
"""

from django.contrib import admin
from django.contrib.auth.models import User
from import_export import resources
from import_export.admin import ImportExportModelAdmin
from import_export.fields import Field
from import_export.widgets import ForeignKeyWidget
from inventory.models import Warehouse
from hr.models import (
    Attendance,
    Employee,
    Designation,
    EmployeeLeave,
    Group,
    LeaveSelectedDate,
    Payroll,
)


class EmployeeResource(resources.ModelResource):
    designation = Field(
        attribute='designation', column_name='designation',
        widget=ForeignKeyWidget(Designation, field='title'),
    )
    warehouse = Field(
        attribute='warehouse', column_name='warehouse',
        widget=ForeignKeyWidget(Warehouse, field='name'),
    )
    group = Field(
        attribute='group', column_name='group',
        widget=ForeignKeyWidget(Group, field='name'),
    )
    user = Field(
        attribute='user', column_name='user',
        widget=ForeignKeyWidget(User, field='username'),
    )

    class Meta:
        model = Employee


class EmployeeLeaveResource(resources.ModelResource):
    employee = Field(
        attribute='employee', column_name='employee',
        widget=ForeignKeyWidget(Employee, field='employee_id'),
    )

    class Meta:
        model = EmployeeLeave


class AttendanceResource(resources.ModelResource):
    employee = Field(
        attribute='employee', column_name='employee',
        widget=ForeignKeyWidget(Employee, field='employee_id'),
    )

    class Meta:
        model = Attendance


class PayrollResource(resources.ModelResource):
    employee = Field(
        attribute='employee', column_name='employee',
        widget=ForeignKeyWidget(Employee, field='employee_id'),
    )

    class Meta:
        model = Payroll


@admin.register(Group)
class GroupAdmin(ImportExportModelAdmin):
    list_display = ("id", "name")


@admin.register(Designation)
class DesignationAdmin(ImportExportModelAdmin):
    """
    register designations models
    """

    list_display = ("title", "description", "base_salary")


@admin.register(Employee)
class EmployeeAdmin(ImportExportModelAdmin):
    """
    register employee models
    """
    resource_classes = [EmployeeResource]

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
class EmployeeLeaveAdmin(ImportExportModelAdmin):
    """
    register employee leave
    """
    resource_classes = [EmployeeLeaveResource]

    list_display = ("employee", "reason", "leave_type", "status", "created_date")


@admin.register(LeaveSelectedDate)
class LeaveSelectedDateAdmin(ImportExportModelAdmin):
    list_display = ("leave_request", "date")


@admin.register(Attendance)
class AttendanceAdmin(ImportExportModelAdmin):
    """
    register attendance models
    """
    resource_classes = [AttendanceResource]

    list_display = (
        "employee",
        "date",
        "check_in_time",
        "check_out_time",
        "status",
        "created_date",
    )


@admin.register(Payroll)
class PayrollAdmin(ImportExportModelAdmin):
    """
    register payroll models
    """
    resource_classes = [PayrollResource]

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
