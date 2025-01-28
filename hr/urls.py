"""
URL configuration for employee-related views in the HR application.
"""

from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from hr.views import (
    EmployeeAttendanceListAPIView,
    EmployeePayrollDashboardView,
    delete_employee,
    edit_employee,
    employee_list,
    create_new_employee,
)
from hr.views import (
    RelieveEmployeeView,
    EmployeeLeaveRequest,
    EmployeeLeaveDashboard,
    EmployeeAttendance,
)


urlpatterns = [
    path("employees/", employee_list, name="employee_list"),
    path("new/employees/", create_new_employee, name="create_new_employee"),
    path("employees/<int:pk>/edit/", edit_employee, name="edit_employee"),
    path("employees/<int:id>/delete/", delete_employee, name="delete_employee"),
    path(
        "employees/<int:id>/relieve/",
        RelieveEmployeeView.as_view(),
        name="relieve_employee",
    ),
    path("employees/leave/", EmployeeLeaveRequest.as_view(), name="leave_employee"),
    path(
        "employee/leave/details/",
        EmployeeLeaveDashboard.as_view(),
        name="employee_leave_details",
    ),
    path(
        "employee/attendance/list/",
        EmployeeAttendanceListAPIView.as_view(),
        name="employee_attendance",
    ),
    path(
        "attendance/", EmployeeAttendance.as_view(), name="attendance"
    ),  # for single employee attendance
    path("attendance/<int:id>/", EmployeeAttendance.as_view(), name="attendance"),
    path("payroll/", EmployeePayrollDashboardView.as_view(), name="payroll"),
]
if settings.DEBUG:  # Only serve media files in development
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
