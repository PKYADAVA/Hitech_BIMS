# pylint: disable=no-member
# pylint: disable=logging-fstring-interpolation
"""
Defines views for managing employee records
"""
import json
import logging
from calendar import monthrange
from datetime import date, timedelta
from django.forms import ValidationError
from django.shortcuts import render, get_object_or_404, redirect
from django.utils.dateparse import parse_date
from django.db import transaction
from datetime import datetime
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q
from django.utils.timezone import now
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.db.models import Count
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from calendar import monthrange
from hr.models import (
    Attendance,
    Designation,
    Employee,
    EmployeeLeave,
    Group,
    LeaveSelectedDate,
    Payroll,
)
from hr.validation import validate_employee_data
from inventory.models import Warehouse

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
            warehouse_id = request.POST.get("warehouse")
            group_id = request.POST.get("group")
            salary_type = request.POST.get("salary_type")
            advance = request.POST.get("advance")
            bank_name = request.POST.get("bank_name")
            date_of_joining = request.POST.get("date_of_joining")
            report_to = request.POST.get("report_to")
            salary_account = request.POST.get("salary_account")
            ifsc_code = request.POST.get("ifsc_code")
            branch_name = request.POST.get("branch_name")
            saving = request.POST.get("saving")
            image = request.FILES.get("image", None)

            error_message = None

            if not full_name:
                error_message = "Full Name is required."
            if not date_of_birth:
                error_message = "Date of Birth is required."
            if not salary:
                error_message = "Salary is required."
            if not designation_id:
                error_message = "Designation is required."

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
            warehouse = Warehouse.objects.filter(id=warehouse_id).first()
            group = Group.objects.filter(id=group_id).first()

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
                warehouse=warehouse,
                group=group,
                salary=int(salary),
                salary_type=salary_type,
                advance=int(advance),
                savings=int(saving),
                date_of_joining=parse_date(date_of_joining),
                report_to=report_to,
                salary_account=salary_account,
                ifsc_code=ifsc_code,
                branch_name=branch_name,
                designation=designation,
                bank_name=bank_name,
                image=image,
            )
            employee.save()

            messages.success(request, "Employee created successfully.")
            return redirect("employee_list")
        except Exception as e:
            logger.error(f"Error creating employee: {e}")
            return render(
                request,
                "new_employee.html",
                {"error_message": "An error occurred while creating the employee."},
            )
    context = {
        "designation_detail": designations_details,
        "group_detail": Group.objects.all(),
        "warehouse_detail": Warehouse.objects.all(),
    }
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
                    employee.warehouse = Warehouse.objects.filter(
                        id=request.POST.get("warehouse")
                    ).first()
                    employee.group = Group.objects.filter(
                        id=request.POST.get("group")
                    ).first()

                    if request.POST.get("salary"):
                        employee.salary = float(request.POST.get("salary"))
                    employee.salary_type = request.POST.get("salary_type")
                    if request.POST.get("advance"):
                        employee.advance = float(request.POST.get("advance"))
                    if request.POST.get("saving"):
                        employee.savings = float(request.POST.get("saving"))

                    emergency_contact = request.POST.get("emergency_contact", None)

                    if emergency_contact:
                        try:
                            employee.emergency_contact = int(emergency_contact)
                        except ValueError:
                            employee.emergency_contact = None
                    else:
                        employee.emergency_contact = None
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
                        employee.image = request.FILES.get("image", None)

                    if request.POST.get("date_of_joining"):
                        employee.date_of_joining = parse_date(
                            request.POST.get("date_of_joining"),
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
            "group_detail": Group.objects.all(),
            "warehouse_detail": Warehouse.objects.all(),
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
            employee_id = employee.id
            employee.delete()
            # Return response with employee ID
            return JsonResponse(
                {
                    "success": True,
                    "message": "Employee deleted successfully.",
                    "employee_id": employee_id,
                }
            )
        except Employee.DoesNotExist:
            return JsonResponse(
                {"success": False, "message": "Employee not found."}, status=404
            )
        except Exception as e:
            return JsonResponse(
                {"success": False, "message": f"An unexpected error occurred: {e}"},
                status=500,
            )
    else:
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
            # Return response with updated data
            return JsonResponse(
                {
                    "success": True,
                    "message": "Employee relieved successfully.",
                    "employee_id": employee.id,
                    "relieve_status": employee.relieve,
                }
            )
        except Employee.DoesNotExist:
            return JsonResponse(
                {"success": False, "message": "Employee not found."}, status=404
            )
        except Exception as e:
            return JsonResponse(
                {"success": False, "message": f"An unexpected error occurred: {e}"},
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
        leave_type = data.get("leave_type")
        # breakpoint()
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
                    leave_type=leave_type,
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


from django.db.models import Sum, Case, When, Value, FloatField, Count


@method_decorator(login_required(login_url="login"), name="dispatch")
@method_decorator(csrf_exempt, name="dispatch")
class EmployeeLeaveDashboard(View):
    """Class-based view to display employee leave dashboard."""

    def get(self, request):
        """Handle GET requests to display employee leave dashboard."""
        current_date = datetime.now()  # Get the current date

        employee_id = request.GET.get(
            "employee_id"
        )  # Retrieve employee_id from the payload
        to_date = request.GET.get("to_date")
        from_date = request.GET.get("from_date")

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

        elif to_date and from_date:
            try:
                # Convert 'to_date' and 'from_date' to datetime objects
                to_date = datetime.strptime(to_date, "%Y-%m-%d")
                from_date = datetime.strptime(from_date, "%Y-%m-%d")

                # Fetch leave details within the date range
                employee_leave_details = list(
                    EmployeeLeave.objects.annotate(total_days=Count("selected_dates"))
                    .filter(
                        employee__isnull=False,
                        created_date__date__gte=from_date,
                        created_date__date__lte=to_date,
                    )
                    .values(
                        "id",
                        "employee__employee_id",  # Assuming employee has an 'employee_id' field
                        "employee__full_name",  # Assuming employee has a 'full_name' field
                        "leave_type",
                        "reason",
                        "status",
                        "total_days",
                    )
                )

                # Count total pending and approved leaves within the date range
                total_pending_leaves = EmployeeLeave.objects.filter(
                    status="Pending",
                    created_date__date__gte=from_date,
                    created_date__date__lte=to_date,
                ).count()

                total_approved_leaves = EmployeeLeave.objects.filter(
                    status="Approved",
                    created_date__date__gte=from_date,
                    created_date__date__lte=to_date,
                ).count()

                response_data = {
                    "leave_details": employee_leave_details,
                    "total_pending_leaves": total_pending_leaves,
                    "total_approved_leaves": total_approved_leaves,
                    "total_employees": Employee.objects.count(),
                }

                return JsonResponse(response_data, status=200)

            except ValueError:
                logger.error("Invalid date format.")
                return JsonResponse({"error": "Invalid date format."}, status=400)

        else:
            employee_leave_details = (
                EmployeeLeave.objects.filter(
                    employee__isnull=False,
                    created_date__year=current_date.year,  # Current year
                    created_date__month=current_date.month,  # Current month
                )
                .prefetch_related(
                    "selected_dates"
                )  # Fetch related selected_dates for each leave request
                .annotate(
                    total_days=Sum(
                        Case(
                            When(
                                leave_type="Full Day", then=Value(1.0)
                            ),  # Full Day = 1 day
                            When(
                                leave_type="First Half", then=Value(0.5)
                            ),  # First Half = 0.5 day
                            When(
                                leave_type="Second Half", then=Value(0.5)
                            ),  # Second Half = 0.5 day
                            default=Value(0.0),  # Default to 0 if no match
                            output_field=FloatField(),
                        )
                    )  # Sum leave days based on leave type
                )
                .annotate(
                    total_selected_dates=Count(
                        "selected_dates"
                    )  # Count number of selected dates
                )
                .annotate(
                    total_leave_days=Sum(
                        Case(
                            When(
                                leave_type="Full Day", then=Value(1.0)
                            ),  # Full Day = 1 day per selected date
                            When(
                                leave_type="First Half", then=Value(0.5)
                            ),  # First Half = 0.5 day per selected date
                            When(
                                leave_type="Second Half", then=Value(0.5)
                            ),  # Second Half = 0.5 day per selected date
                            default=Value(0.0),  # Default to 0 if no match
                            output_field=FloatField(),
                        )
                    )
                    * Count(
                        "selected_dates"
                    )  # Multiply the days per leave type by the number of selected dates
                )
            )

            # Count total pending and approved leaves for the current month
            total_pending_leaves = EmployeeLeave.objects.filter(
                status="Pending",
                created_date__year=current_date.year,
                created_date__month=current_date.month,
            ).count()

            total_approved_leaves = EmployeeLeave.objects.filter(
                status="Approved",
                created_date__year=current_date.year,
                created_date__month=current_date.month,
            ).count()

            context = {
                "leave_details": employee_leave_details,
                "total_pending_leaves": total_pending_leaves,
                "total_approved_leaves": total_approved_leaves,
                "total_employees": Employee.objects.filter(relieve=False).count(),
            }

            return render(request, "employee_leave_details.html", context)

    def post(self, request):
        """Handle POST requests to update leave status."""
        leave_id = request.POST.get("leave_id")
        new_status = request.POST.get("status")

        if not leave_id or not new_status:
            logger.error(f"Invalid data: leave_id={leave_id}, new_status={new_status}.")
            return JsonResponse({"error": "Invalid data provided."}, status=400)

        if new_status not in ["Pending", "Approved", "Rejected"]:
            logger.warning(f"Invalid status value: {new_status}.")
            return JsonResponse({"error": "Invalid status provided."}, status=400)

        try:
            leave = get_object_or_404(EmployeeLeave, id=leave_id)
            leave.status = new_status
            leave.save()

            # Current month filter
            current_month = now().month
            current_year = now().year

            # Count of pending and approved leaves in current month
            total_pending_leaves = EmployeeLeave.objects.filter(
                status="Pending",
                created_date__month=current_month,
                created_date__year=current_year,
            ).count()

            total_approved_leaves = EmployeeLeave.objects.filter(
                status="Approved",
                created_date__month=current_month,
                created_date__year=current_year,
            ).count()

            total_employees = Employee.objects.count()

            return JsonResponse(
                {
                    "success": "Leave status updated successfully.",
                    "leave_id": leave_id,
                    "new_status": leave.status,
                    "total_pending_leaves": total_pending_leaves,
                    "total_approved_leaves": total_approved_leaves,
                    "total_employees": total_employees,
                }
            )

        except Exception as e:
            logger.exception(
                f"Error updating leave status for Leave ID {leave_id}. {e}"
            )
            return JsonResponse(
                {"error": "An error occurred while updating leave status."}, status=500
            )


class EmployeeAttendanceListAPIView(View):
    """Class-based view to handle employee attendance using API."""

    def get(self, request):
        """Handle GET requests to fetch all employee attendance records."""
        try:
            context = {
                "employees": Employee.objects.filter(relieve=False).order_by(
                    "full_name"
                ),
                "attendances": Attendance.objects.select_related("employee").order_by(
                    "-date", "-check_in_time"
                ),
            }
            return render(request, "employee_attendance.html", context)
        except Exception as e:
            logger.error("Error fetching attendance records: %s", e)
            return JsonResponse({"error": str(e)}, status=500)


@method_decorator(login_required(login_url="login"), name="dispatch")
@method_decorator(csrf_exempt, name="dispatch")
class EmployeeAttendance(View):
    """Class-based view to handle employee attendance."""

    def get(self, request, id=None):
        """Handle GET requests to display employee attendance or get specific attendance."""
        current_date = timezone.now()
        to_date = request.GET.get("to_date")
        from_date = request.GET.get("from_date")
        if id:
            try:
                attendance = get_object_or_404(Attendance, id=id)
                return JsonResponse(
                    {
                        "id": attendance.id,
                        "employee_id": attendance.employee.employee_id,
                        "employee_name": attendance.employee.full_name,
                        "designation": (
                            attendance.employee.designation.title
                            if attendance.employee.designation
                            else None
                        ),
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
                    }
                )
            except Exception as e:
                logger.error("Error fetching attendance record: %s", e)
                return JsonResponse({"error": str(e)}, status=400)

        elif to_date and from_date:
            try:
                # Parse the from_date and to_date strings to datetime objects
                from_date = datetime.strptime(from_date, "%Y-%m-%d").date()
                to_date = datetime.strptime(to_date, "%Y-%m-%d").date()

                # Filter records between from_date and to_date
                attendances = (
                    Attendance.objects.filter(
                        Q(created_date__gte=from_date) & Q(created_date__lte=to_date)
                    )
                    .select_related("employee")
                    .order_by("-created_date", "-check_in_time")
                )

                data = {
                    "attendances": list(
                        attendances.values(
                            "id",
                            "employee__employee_id",
                            "employee__designation__title",
                            "employee__full_name",
                            "date",
                            "check_in_time",
                            "check_out_time",
                            "status",
                        )
                    ),
                }
                print(data)
                return JsonResponse(data)

            except ValueError as e:
                logger.error("Invalid date format: %s", e)
                return JsonResponse(
                    {"error": "Invalid date format. Use YYYY-MM-DD."}, status=400
                )

        else:
            attendances = (
                Attendance.objects.filter(
                    Q(created_date__year=current_date.year)
                    & Q(created_date__month=current_date.month)
                )
                .select_related("employee")
                .order_by("-created_date", "-check_in_time")
            )

            data = {
                "attendances": list(
                    attendances.values(
                        "id",
                        "employee__employee_id",
                        "employee__designation__title",
                        "employee__full_name",
                        "date",
                        "check_in_time",
                        "check_out_time",
                        "status",
                    )
                ),
            }
            return JsonResponse(data)

    def post(self, request):
        """Handle POST requests to create a new attendance record."""
        try:
            data = json.loads(request.body)
            employee = get_object_or_404(Employee, id=data.get("employee_id"))

            # Create attendance record
            attendance = Attendance.objects.create(
                employee=employee,
                date=data.get("date"),
                check_in_time=data.get("check_in_time") or None,
                check_out_time=data.get("check_out_time") or None,
                status=data.get("status", "Present"),
            )

            return JsonResponse(
                {
                    "message": "Attendance record created successfully",
                    "id": attendance.id,
                    "employee_id": employee.employee_id,
                    "employee_name": employee.full_name,
                    "designation": (
                        employee.designation.title if employee.designation else None
                    ),
                    "date": attendance.date,
                    "status": attendance.status,
                },
                status=201,
            )
        except Exception as e:
            logger.error("Error creating attendance record: %s", e)
            return JsonResponse({"error": str(e)}, status=400)

    def put(self, request, id=None):
        try:
            # Check if the request method is PUT and the body contains form-encoded data
            if request.method == "PUT":
                # If data is sent as URL-encoded form data, access it with request.POST
                data = json.loads(request.body)

                # If no ID is passed in the URL, try to get it from the request body
                attendance_id = id or data.get(
                    "attendance_id"
                )  # use "attendance_id" here
                attendance = get_object_or_404(Attendance, id=attendance_id)

                # Update attendance record with the provided data
                attendance.date = data.get("date", attendance.date)
                attendance.check_in_time = data.get("check_in_time") or None
                attendance.check_out_time = data.get("check_out_time") or None
                attendance.status = data.get("status", attendance.status)
                attendance.save()

                return JsonResponse(
                    {
                        "message": "Attendance record updated successfully",
                        "attendance": {
                            "attendance_id": attendance.id,
                            "employee_id": attendance.employee.employee_id,
                            "date": attendance.date,
                            "check_in_time": attendance.check_in_time,
                            "check_out_time": attendance.check_out_time,
                            "status": attendance.status,
                        },
                    }
                )
            else:
                return JsonResponse({"error": "Invalid request method"}, status=405)

        except Exception as e:
            logger.error("Error updating attendance record: %s", e)
            return JsonResponse({"error": str(e)}, status=400)

    def delete(self, request, id=None):
        """Handle DELETE requests to delete an attendance record."""
        try:
            attendance = get_object_or_404(Attendance, id=id)
            attendance.delete()
            return JsonResponse(
                {
                    "success": True,
                    "message": "Attendance record deleted successfully",
                    "id": id,
                },
                status=200,
            )
        except Exception as e:
            logger.error("Error deleting attendance record: %s", e)
            return JsonResponse({"error": str(e)}, status=400)


@method_decorator(login_required(login_url="login"), name="dispatch")
@method_decorator(csrf_exempt, name="dispatch")
class EmployeePayrollDashboardView(View):
    """Class-based view to handle employee payroll dashboard."""

    def get(self, request):
        """Render the payroll dashboard page."""
        employees = Employee.objects.filter(relieve=False)
        return render(request, "employee_payroll.html", {"employee_detail": employees})

    def post(self, request):
        """Handle POST request to calculate monthly salary."""
        employee_id = request.POST.get("employee_id")
        year = int(request.POST.get("year"))
        month = int(request.POST.get("month"))

        try:
            employee = Employee.objects.get(id=employee_id)
            payroll = self.generate_payroll(employee, year, month)

            return JsonResponse(
                {
                    "success": True,
                    "employee": employee.full_name,
                    "month": month,
                    "year": year,
                    "total_working_days": payroll.total_working_days,
                    "payable_salary": round(payroll.payable_salary, 2),
                    "gross_salary": payroll.gross_salary,
                },
                status=200,
            )

        except Employee.DoesNotExist:
            logger.error("Employee with ID %s not found.", employee_id)
            return JsonResponse(
                {"success": False, "message": "Employee not found"}, status=404
            )
        except Exception as e:
            logger.error("Error calculating payroll: %s", e)
            return JsonResponse(
                {"success": False, "message": "An error occurred"}, status=500
            )

    def generate_payroll(self, employee, year, month):
        """
        Generate payroll for an employee based on attendance and leave records.
        If the employee has no attendance or leave in the given month, set working days to 0.
        """
        # Get the number of days in the month
        _, total_days = monthrange(year, month)
        start_date = date(year, month, 1)
        end_date = date(year, month, total_days)

        # Fetch attendance and leave records
        attendance_records = Attendance.objects.filter(
            employee=employee, date__range=(start_date, end_date)
        )
        leave_records = LeaveSelectedDate.objects.filter(
            leave_request__employee=employee, date__range=(start_date, end_date)
        )

        # Initialize working days counter
        working_days = 0

        # Iterate through each day of the month
        for day in range(1, total_days + 1):
            current_date = date(year, month, day)

            # Skip weekends (Saturday & Sunday)
            if current_date.weekday() in [5, 6]:  # 5 = Saturday, 6 = Sunday
                continue

            # Check attendance status
            attendance = attendance_records.filter(date=current_date).first()
            if attendance:
                if attendance.status == "Present":
                    working_days += 1
                elif attendance.status in ["First Half", "Second Half"]:
                    working_days += 0.5

            # Check if the employee was on leave
            elif leave_records.filter(date=current_date).exists():
                working_days += 1

        # If no attendance or leave records, set working days to 0
        if not attendance_records.exists() and not leave_records.exists():
            working_days = 0

        # Calculate payable salary based on working days
        payable_salary = working_days * employee.daily_wage if working_days > 0 else 0

        # Save or update payroll record
        payroll, created = Payroll.objects.update_or_create(
            employee=employee,
            month=month,
            year=year,
            defaults={
                "gross_salary": employee.salary,
                "deductions": employee.advance,  # Modify as needed
                "net_salary": payable_salary,  # Assuming net salary is based on working days
                "total_working_days": working_days,
                "payable_salary": payable_salary,
            },
        )

        return payroll
