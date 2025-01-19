# pylint: disable=no-member
# pylint: disable=logging-fstring-interpolation
"""
Defines views for managing employee records
"""
import json
import logging
from django.forms import ValidationError
from django.shortcuts import render, get_object_or_404, redirect
from django.utils.dateparse import parse_date
from django.db import transaction
from datetime import datetime
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpResponseBadRequest, JsonResponse
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.db.models import Count
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from hr.models import (
    Attendance,
    Designation,
    Employee,
    EmployeeLeave,
    LeaveSelectedDate,
)
from hr.validation import validate_employee_data

# Configure logger
logger = logging.getLogger(__name__)


@login_required(login_url="login")
def employee_list(request):
    """Display a list of employees."""
    employees = Employee.objects.all().order_by("id")

    paginator = Paginator(employees, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    total_count = employees.count()

    return render(
        request,
        "employee_list.html",
        {
            "employee_details": page_obj,
            "total_count": total_count,
        },
    )


@login_required(login_url="login")
def create_new_employee(request):
    """
    adding new employees functionality
    """
    designations_details = Designation.objects.all()
    if request.method == "POST":
        try:
            full_name = request.POST.get("full_name")
            title = request.POST.get("title")
            father_name = request.POST.get("father_name")
            marital_status = request.POST.get("marital_status")
            gender = request.POST.get("gender")
            date_of_birth = request.POST.get("date_of_birth")
            designation_id = request.POST.get("designation")
            salary = request.POST.get("salary")
            blood_group = request.POST.get("blood_group")
            qualification = request.POST.get("qualification")
            driving_license = request.POST.get("driving_license") == "on"
            pan_card = request.POST.get("pan_card")
            aadhar_number = request.POST.get("aadhar_number")
            personal_contact = request.POST.get("personal_contact")
            emergency_contact = request.POST.get("emergency_contact")
            country = request.POST.get("country")
            correspondence_address = request.POST.get("correspondence_address")
            sector = request.POST.get("sector")
            group = request.POST.get("group")
            salary_type = request.POST.get("salary_type")
            advance = request.POST.get("advance")
            bank_name = request.POST.get("bank_name")
            date_of_joining = request.POST.get("date_of_joining")
            report_to = request.POST.get("report_to")
            salary_account = request.POST.get("salary_account")
            ifsc_code = request.POST.get("ifsc_code")
            leaves = request.POST.get("leaves")
            branch_name = request.POST.get("branch_name")
            saving = request.POST.get("saving")

            error_message = None

            if not full_name:
                error_message = "Full Name is required."
            if not date_of_birth:
                error_message = "Date of Birth is required."
            if not salary:
                error_message = "Salary is required."
            if not designation_id:
                error_message = "Designation is required."
            if not personal_contact or not personal_contact.isdigit():
                error_message = (
                    "Emergency Contact 1 is required and should contain only numbers."
                )
            if not emergency_contact or not emergency_contact.isdigit():
                error_message = (
                    "Emergency Contact is required and should contain only numbers."
                )
            if not salary.isdigit():
                error_message = "Salary must be a valid number."

            if error_message is None:
                try:
                    date_of_birth = parse_date(date_of_birth)
                    if not date_of_birth:
                        error_message = "Invalid date format for Date of Birth."
                except ValueError:
                    error_message = "Invalid date format for Date of Birth."

            if error_message is None:
                try:
                    designation = Designation.objects.get(id=designation_id)
                except Designation.DoesNotExist:
                    error_message = "Designation not found."

            if error_message:
                logger.error("Validation error: %s", error_message)
                return render(
                    request, "new_employee.html", {"error_message": error_message}
                )

            employee = Employee(
                full_name=full_name,
                title=title,
                father_name=father_name,
                marital_status=marital_status,
                gender=gender,
                date_of_birth=date_of_birth,
                blood_group=blood_group,
                driving_license=driving_license,
                qualification=qualification,
                pan_card=pan_card,
                aadhar_number=aadhar_number,
                personal_contact=personal_contact,
                emergency_contact=emergency_contact,
                country=country,
                correspondence_address=correspondence_address,
                sector=sector,
                group=group,
                salary=int(salary),
                salary_type=salary_type,
                advance=advance,
                savings=saving,
                date_of_joining=date_of_joining,
                report_to=report_to,
                salary_account=salary_account,
                ifsc_code=ifsc_code,
                leaves=leaves,
                branch_name=branch_name,
                designation=designation,
                bank_name=bank_name,
            )
            employee.save()

            messages.success(request, "Employee created successfully.")
            return redirect("employee_list")
        except Exception as e:
            print(e)
            logger.error(f"Error creating employee: {e}")
            return render(
                request,
                "new_employee.html",
                {"error_message": "An error occurred while creating the employee."},
            )
    context = {"designation_detail": designations_details}
    return render(request, "new_employee.html", context)


@login_required(login_url="login")
def edit_employee(request, pk):
    """
    View function to handle employee editing.
    """
    try:
        employee = get_object_or_404(Employee, pk=pk)

        if request.method == "POST":
            try:
                is_valid, error_message = validate_employee_data(request.POST)
                if not is_valid:
                    messages.error(request, error_message)
                    raise ValidationError(error_message)

                with transaction.atomic():
                    employee.full_name = request.POST.get("full_name")
                    employee.title = request.POST.get("title")
                    employee.father_name = request.POST.get("father_name")

                    employee.marital_status = request.POST.get("marital_status")
                    employee.gender = request.POST.get("gender")
                    employee.date_of_birth = request.POST.get("date_of_birth")
                    employee.blood_group = request.POST.get("blood_group")
                    employee.driving_license = bool(request.POST.get("driving_license"))

                    designation_id = request.POST.get("designation")
                    if designation_id:
                        employee.designation = get_object_or_404(
                            Designation, id=designation_id
                        )
                    employee.sector = request.POST.get("sector")
                    employee.group = request.POST.get("group")

                    if request.POST.get("salary"):
                        employee.salary = float(request.POST.get("salary"))
                    employee.salary_type = request.POST.get("salary_type")
                    if request.POST.get("advance"):
                        employee.advance = float(request.POST.get("advance"))
                    if request.POST.get("saving"):
                        employee.savings = float(request.POST.get("saving"))

                    employee.emergency_contact = request.POST.get("emergency_contact")
                    employee.personal_contact = request.POST.get("personal_contact")
                    employee.country = request.POST.get("country")
                    employee.correspondence_address = request.POST.get(
                        "correspondence_address"
                    )

                    employee.salary_account = request.POST.get("salary_account")
                    employee.bank_name = request.POST.get("bank_name")
                    employee.ifsc_code = request.POST.get("ifsc_code")
                    employee.branch_name = request.POST.get("branch_name")

                    employee.qualification = request.POST.get("qualification")
                    employee.pan_card = request.POST.get("pan_card")
                    employee.aadhar_number = request.POST.get("aadhar_number")
                    employee.report_to = request.POST.get("report_to")
                    if request.POST.get("leaves"):
                        employee.leaves = int(request.POST.get("leaves"))

                    if request.FILES.get("image"):
                        employee.image = request.FILES["image"]

                    if request.POST.get("date_of_joining"):
                        employee.date_of_joining = datetime.strptime(
                            request.POST.get("date_of_joining"), "%Y-%m-%dT%H:%M"
                        )

                    employee.save()

                    messages.success(request, "Employee updated successfully")
                    return redirect("employee_list")

            except ValidationError as e:
                logger.error(f"Validation error while updating employee {pk}: {str(e)}")
                messages.error(request, str(e))
            except Exception as e:
                logger.error(f"Error updating employee {pk}: {str(e)}")
                messages.error(request, "An error occurred while updating employee")

        context = {
            "employee": employee,
            "designation_detail": Designation.objects.all(),
        }

        return render(request, "edit_employee.html", context)

    except Exception as e:
        logger.error(
            f"Unexpected error in edit_employee view for employee {pk}: {str(e)}"
        )
        messages.error(request, "An unexpected error occurred")
        return redirect("employee_list")


@login_required(login_url="login")
def delete_employee(request, id):
    """Delete an employee."""
    if request.method == "GET":
        try:
            employee = get_object_or_404(Employee, id=id)
            employee.delete()
            return JsonResponse(
                {"success": True, "message": "Employee deleted successfully."}
            )
        except Employee.DoesNotExist:
            logger.error(f"Employee with ID {id} does not exist.")
            return JsonResponse(
                {"success": False, "message": "Employee not found."}, status=404
            )
        except Exception as e:
            logger.exception(
                f"An error occurred while deleting employee with ID {id}: {e}"
            )
            return JsonResponse(
                {"success": False, "message": "An unexpected error occurred."},
                status=500,
            )
    else:
        logger.warning(
            f"Invalid request method: {request.method} for deleting employee with ID {id}."
        )
        return JsonResponse(
            {"success": False, "message": "Invalid request method."}, status=400
        )


@method_decorator(login_required(login_url="login"), name="dispatch")
class RelieveEmployeeView(View):
    """Class-based view to relieve an employee."""

    def get(self, request, id):
        """
        Handle GET requests to relieve an employee.
        """
        try:
            employee = get_object_or_404(Employee, id=id)
            if employee.relieve:
                return JsonResponse(
                    {"success": False, "message": "Employee is already relieved."}
                )
            employee.relieve = True
            employee.save()
            return JsonResponse(
                {"success": True, "message": "Employee relieved successfully."}
            )
        except Employee.DoesNotExist:
            logger.error(f"Employee with ID {id} does not exist.")
            return JsonResponse(
                {"success": False, "message": "Employee not found."}, status=404
            )
        except Exception as e:
            logger.exception(
                f"An error occurred while relieving employee with ID {id}: {e}"
            )
            return JsonResponse(
                {"success": False, "message": "An unexpected error occurred."},
                status=500,
            )


@method_decorator(login_required(login_url="login"), name="dispatch")
@method_decorator(csrf_exempt, name="dispatch")
class EmployeeLeaveRequest(View):
    """Class-based view to mark leave for an employee."""

    def get(self, request):
        """
        Handle GET requests to mark leave for an employee.
        """
        try:
            employee_details = Employee.objects.all().order_by("employee_id")
            context = {"employee_details": employee_details}
        except Exception as e:
            logger.error(f"Error fetching employee details: {e}")
            return JsonResponse(
                {"success": False, "message": "Error fetching employee details"},
                status=500,
            )
        return render(request, "employee_leave.html", context)

    def post(self, request):
        """
        Handle POST requests to mark leave for an employee.
        """
        data = json.loads(request.body)
        employee_id = data.get("employee_id")
        selected_dates = data.get("selected_dates", [])
        reason = data.get("reason")

        if not isinstance(selected_dates, list) or not all(
            isinstance(date, str) for date in selected_dates
        ):
            return JsonResponse(
                {"success": False, "message": "Invalid selected dates."}, status=400
            )

        if not employee_id or not selected_dates or not reason:
            return JsonResponse(
                {"success": False, "message": "All fields are required."}, status=400
            )

        try:
            with transaction.atomic():
                employee = Employee.objects.filter(id=employee_id).first()
                if not employee:
                    return JsonResponse(
                        {"success": False, "message": "Employee not found."}, status=404
                    )

                leave_request = EmployeeLeave.objects.create(
                    employee=employee,
                    reason=reason,
                )

                for date in selected_dates:
                    LeaveSelectedDate.objects.create(
                        leave_request=leave_request,
                        date=date,
                    )

        except Exception as e:
            logger.error(f"Error marking leave for employee {employee_id}: {e}")
            return JsonResponse(
                {"success": False, "message": "An error occurred while marking leave."},
                status=500,
            )

        return JsonResponse({"success": True, "message": "Leave marked successfully."})


@method_decorator(login_required(login_url="login"), name="dispatch")
@method_decorator(csrf_exempt, name="dispatch")
class EmployeeLeaveDashboard(View):
    """Class-based view to display employee leave dashboard."""

    def get(self, request):
        """Handle GET requests to display employee leave dashboard."""
        employee_id = request.GET.get(
            "employee_id"
        )  # Retrieve employee_id from the payload

        if employee_id:
            try:
                # Fetch leave details for the specific employee
                employee_leave = (
                    EmployeeLeave.objects.filter(id=employee_id)
                    .prefetch_related("selected_dates")
                    .first()
                )

                if not employee_leave:
                    return JsonResponse(
                        {"error": "Employee leave not found."}, status=404
                    )

                selected_dates = list(
                    employee_leave.selected_dates.values_list("date", flat=True)
                )
                return JsonResponse({"selected_dates": selected_dates}, status=200)
            except Exception as e:
                logger.exception(f"Error fetching employee leave details: {e}")
                return JsonResponse(
                    {"error": "An error occurred while fetching leave details."},
                    status=500,
                )

        # If no employee_id is provided, return the full dashboard context
        employee_leave_details = (
            EmployeeLeave.objects.annotate(total_days=Count("selected_dates"))
            .filter(employee__isnull=False)
            .prefetch_related("selected_dates")
        )
        total_pending_leaves = EmployeeLeave.objects.filter(status="Pending").count()
        total_approved_leaves = EmployeeLeave.objects.filter(status="Approved").count()
        total_employees = Employee.objects.count()

        context = {
            "leave_details": employee_leave_details,
            "total_pending_leaves": total_pending_leaves,
            "total_approved_leaves": total_approved_leaves,
            "total_employees": total_employees,
        }
        return render(request, "employee_leave_details.html", context)

    def post(self, request):
        """Handle POST requests to update leave status."""
        leave_id = request.POST.get("leave_id")
        new_status = request.POST.get("status")

        if not leave_id or not new_status:
            logger.error("Invalid data: leave_id or new_status missing.")
            return JsonResponse({"error": "Invalid data provided."}, status=400)

        if new_status not in ["Pending", "Approved", "Rejected"]:
            logger.warning(f"Invalid status value: {new_status}")
            return JsonResponse({"error": "Invalid status provided."}, status=400)

        try:
            leave = get_object_or_404(EmployeeLeave, id=leave_id)
            leave.status = new_status
            leave.save()

            return JsonResponse({"success": "Leave status updated successfully."})
        except EmployeeLeave.DoesNotExist:
            logger.error(f"Leave with ID {leave_id} not found.")
            return JsonResponse({"error": "Leave not found."}, status=404)
        except Exception as e:
            logger.exception(f"Error updating leave status. Leave ID: {leave_id} {e}")
            return JsonResponse(
                {"error": "An error occurred while updating leave status."}, status=500
            )


@method_decorator(login_required(login_url="login"), name="dispatch")
class EmployeeAttendance(View):
    """Class-based view to handle employee attendance."""

    def get(self, request):
        """Handle GET requests to display employee attendance or get specific attendance."""
        attendance_id = request.GET.get("id")

        if attendance_id:
            try:
                attendance = get_object_or_404(Attendance, id=attendance_id)
                return JsonResponse(
                    {
                        "id": attendance.id,
                        "employee_id": attendance.employee.id,
                        "date": attendance.date.strftime("%Y-%m-%d"),
                        "check_in_time": (
                            attendance.check_in_time.strftime("%H:%M")
                            if attendance.check_in_time
                            else ""
                        ),
                        "check_out_time": (
                            attendance.check_out_time.strftime("%H:%M")
                            if attendance.check_out_time
                            else ""
                        ),
                        "status": attendance.status,
                        # 'remarks': attendance.remarks or ''
                    }
                )
            except Exception as e:
                logger.error("Error while checking out time for %s: %s" % (e))
                return HttpResponseBadRequest(str(e))

        context = {
            "employees": Employee.objects.filter(relieve=False).order_by("full_name"),
            "attendances": Attendance.objects.select_related("employee").order_by(
                "-date", "-check_in_time"
            ),
        }
        return render(request, "employee_attendance.html", context)

    def post(self, request):
        """Handle POST requests to create a new attendance record."""
        try:
            data = json.loads(request.body)
            employee = get_object_or_404(Employee, id=data.get("employee_id"))
            attendance = Attendance.objects.create(
                employee=employee,
                date=data.get("date"),
                check_in_time=data.get("check_in_time"),
                check_out_time=data.get("check_out_time"),
                status=data.get("status", "Present"),
            )
            return JsonResponse(
                {
                    "message": "Attendance record created successfully",
                    "id": attendance.id,
                },
                status=201,
            )
        except Exception as e:
            logger.error("Error creating attendance record: %s", e)
            return JsonResponse(
                {"error": "Failed to create attendance record"},
                status=400,
            )

    def put(self, request):
        """Handle PUT requests to update an existing attendance record."""
        try:
            data = json.loads(request.body)
            attendance = get_object_or_404(Attendance, id=data.get("id"))
            attendance.date = data.get("date", attendance.date)
            attendance.check_in_time = data.get(
                "check_in_time", attendance.check_in_time
            )
            attendance.check_out_time = data.get(
                "check_out_time", attendance.check_out_time
            )
            attendance.status = data.get("status", attendance.status)
            attendance.save()
            return JsonResponse({"message": "Attendance record updated successfully"})
        except Exception as e:
            logger.error("Error updating attendance record for event %s", (e))
            return JsonResponse(
                {"error": "Failed to update attendance record"},
                status=400,
            )

    def delete(self, request):
        """Handle DELETE requests to delete an attendance record."""
        try:
            attendance = get_object_or_404(Attendance, id=request.GET.get("id"))
            attendance.delete()
            return JsonResponse({"message": "Attendance record deleted successfully"})
        except Exception as e:
            logger.error("Error deleting attendance record for event %s", (e))
            return JsonResponse(
                {"error": "Failed to delete attendance record"},
                status=400,
            )
