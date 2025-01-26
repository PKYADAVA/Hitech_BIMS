# pylint: disable=no-member
# pylint: disable=logging-fstring-interpolation
"""
Defines views for managing employee records
"""
import json
import logging
from django.db.models.functions import TruncMonth
from django.utils.timezone import now
from django.forms import ValidationError
from django.shortcuts import render, get_object_or_404, redirect
from django.utils.dateparse import parse_date
from django.db import transaction
from datetime import datetime
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q
from django.core.paginator import Paginator
from django.http import JsonResponse
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
    Group,
    LeaveSelectedDate,
    Sector,
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
            sector_id = request.POST.get("sector")
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
            image = request.FILES["image"]

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
            sector = Sector.objects.filter(id=sector_id).first()
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
                sector=sector,
                group=group,
                salary=int(salary),
                salary_type=salary_type,
                advance=int(advance),
                savings=int(saving),
                date_of_joining=date_of_joining,
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
            print(e)
            logger.error(f"Error creating employee: {e}")
            return render(
                request,
                "new_employee.html",
                {"error_message": "An error occurred while creating the employee."},
            )
    context = {
        "designation_detail": designations_details,
        "group_detail": Group.objects.all(),
        "sector_detail": Sector.objects.all(),
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
                    employee.sector = Sector.objects.filter(id=request.POST.get("sector")).first()
                    employee.group = Group.objects.filter(id=request.POST.get("group")).first()

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
            "group_detail": Group.objects.all(),
            "sector_detail": Sector.objects.all(),
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


@method_decorator(login_required(login_url="login"), name="dispatch")
@method_decorator(csrf_exempt, name="dispatch")
class EmployeeLeaveDashboard(View):
    """Class-based view to display employee leave dashboard."""
    def get(self, request):
        """Handle GET requests to display employee leave dashboard."""
        current_date = datetime.now()  # Get the current date

        employee_id = request.GET.get("employee_id")  # Retrieve employee_id from the payload
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
                    return JsonResponse({"error": "Employee leave not found."}, status=404)

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
                return JsonResponse({"error": "Invalid date format."}, status=400)

        else:
            # Default behavior if no employee_id or date range is provided
            employee_leave_details = (
                EmployeeLeave.objects.annotate(total_days=Count("selected_dates"))
                .filter(
                    employee__isnull=False,
                    created_date__year=current_date.year,  # Current year
                    created_date__month=current_date.month,  # Current month
                )
                .prefetch_related("selected_dates")
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
                "total_employees": Employee.objects.count(),
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

            # Fetch updated counts
            total_pending_leaves = EmployeeLeave.objects.filter(status="Pending").count()
            total_approved_leaves = EmployeeLeave.objects.filter(status="Approved").count()
            total_employees = Employee.objects.count()

            # Return updated data in the response
            return JsonResponse({
                "success": "Leave status updated successfully.",
                "leave_id": leave_id,
                "new_status": leave.status,
                "total_pending_leaves": total_pending_leaves,
                "total_approved_leaves": total_approved_leaves,
                "total_employees": total_employees,
            })

        except Exception as e:
            logger.exception(f"Error updating leave status for Leave ID {leave_id}. {e}")
            return JsonResponse(
                {"error": "An error occurred while updating leave status."}, 
                status=500
            )

class EmployeeAttendanceListAPIView(View):
    """Class-based view to handle employee attendance using API."""
    def get(self, request):
        """Handle GET requests to fetch all employee attendance records."""
        try:
            context = {
                "employees": Employee.objects.filter(relieve=False).order_by("full_name"),
                "attendances": Attendance.objects.select_related("employee").order_by("-date", "-check_in_time"),
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
        to_date = request.GET.get('to_date')
        from_date = request.GET.get('from_date')
        if id:
            try:
                attendance = get_object_or_404(Attendance, id=id)
                return JsonResponse({
                    "id": attendance.id,
                    "employee_id": attendance.employee.employee_id,
                    "employee_name": attendance.employee.full_name,
                    "designation": attendance.employee.designation.title if attendance.employee.designation else None,
                    "date": attendance.date.strftime("%Y-%m-%d"),
                    "check_in_time": attendance.check_in_time.strftime("%H:%M") if attendance.check_in_time else "",
                    "check_out_time": attendance.check_out_time.strftime("%H:%M") if attendance.check_out_time else "",
                    "status": attendance.status,
                })
            except Exception as e:
                logger.error("Error fetching attendance record: %s", e)
                return JsonResponse({"error": str(e)}, status=400)
            
        elif to_date and from_date:
            try:
                # Parse the from_date and to_date strings to datetime objects
                from_date = datetime.strptime(from_date, "%Y-%m-%d").date()
                to_date = datetime.strptime(to_date, "%Y-%m-%d").date()

                # Filter records between from_date and to_date
                attendances = Attendance.objects.filter(
                    Q(created_date__gte=from_date) & Q(created_date__lte=to_date)
                ).select_related("employee").order_by("-created_date", "-check_in_time")

                data = {
                    "attendances": list(
                        attendances.values(
                            "id", "employee__employee_id", "employee__designation__title", "employee__full_name", "date", "check_in_time", "check_out_time", "status"
                        )
                    ),
                }
                return JsonResponse(data)

            except ValueError as e:
                logger.error("Invalid date format: %s", e)
                return JsonResponse({"error": "Invalid date format. Use YYYY-MM-DD."}, status=400)

        else:
            attendances = Attendance.objects.filter(
            Q(created_date__year=current_date.year) & Q(created_date__month=current_date.month)
            ).select_related("employee").order_by("-created_date", "-check_in_time")
            
            data = {
                "attendances": list(
                    attendances.values(
                        "id", "employee__employee_id", "employee__designation__title", "employee__full_name", "date", "check_in_time", "check_out_time", "status"
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
                status=data.get("status", "Present")
            )
            
            return JsonResponse({
                "message": "Attendance record created successfully",
                "id": attendance.id,
                "employee_id": employee.employee_id,
                "employee_name": employee.full_name,
                "designation": employee.designation.title if employee.designation else None,
                "date": attendance.date,
                "status": attendance.status,
            }, status=201)
        except Exception as e:
            logger.error("Error creating attendance record: %s", e)
            return JsonResponse({"error": str(e)}, status=400)

    def put(self, request, id=None):
        try:
            # Check if the request method is PUT and the body contains form-encoded data
            if request.method == 'PUT':
                # If data is sent as URL-encoded form data, access it with request.POST
                data = json.loads(request.body)
                
                # If no ID is passed in the URL, try to get it from the request body
                attendance_id = id or data.get("attendance_id")  # use "attendance_id" here
                attendance = get_object_or_404(Attendance, id=attendance_id)
                
                # Update attendance record with the provided data
                attendance.date = data.get("date", attendance.date)
                attendance.check_in_time = data.get("check_in_time") or None
                attendance.check_out_time = data.get("check_out_time") or None
                attendance.status = data.get("status", attendance.status)
                attendance.save()

                return JsonResponse({
                    "message": "Attendance record updated successfully",
                    "attendance": {
                    "attendance_id": attendance.id,
                    "employee_id": attendance.employee.employee_id,
                    "date": attendance.date,
                    "check_in_time": attendance.check_in_time,
                    "check_out_time": attendance.check_out_time,
                    "status": attendance.status,
                }
                })
            else:
                return JsonResponse({"error": "Invalid request method"}, status=405)
        
        except Exception as e:
            logger.error("Error updating attendance record: %s", e)
            return JsonResponse({"error": str(e)}, status=400)
    def delete(self, request,id=None):
        """Handle DELETE requests to delete an attendance record."""
        try:
            attendance = get_object_or_404(Attendance, id=id)
            attendance.delete()
            return JsonResponse({
                "success": True,
                "message": "Attendance record deleted successfully",
                "id":id,
            },status=200)
        except Exception as e:
            logger.error("Error deleting attendance record: %s", e)
            return JsonResponse({"error": str(e)}, status=400)