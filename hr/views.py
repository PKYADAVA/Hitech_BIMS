#pylint: disable=no-member
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
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from hr.models import Designation, Employee
from hr.validation import validate_employee_data

# Configure logger
logger = logging.getLogger(__name__)

@login_required(login_url='login')
def employee_list(request):
    """Display a list of employees."""
    employees = Employee.objects.all().order_by('id') 

    paginator = Paginator(employees, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    total_count = employees.count()

    return render(request, "employee_list.html", {
        "employee_details": page_obj,
        "total_count": total_count,
    })
@login_required(login_url='login')
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

@login_required(login_url='login')
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

@login_required(login_url='login')
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

@login_required(login_url='login')
def relieve_employee(request, id):
    """relieve an employee."""
    if request.method == "GET":
        try:
            employee = get_object_or_404(Employee, id=id)
            if employee.relieve:
                return JsonResponse(
                    {"success": False, "message": "Employee is already relieved."}
                )
            employee.relieve = True
            employee.save()
            return JsonResponse(
                {"success": True, "message": "Employee relieve successfully."}
            )
        except Employee.DoesNotExist:
            logger.error(f"Employee with ID {id} does not exist.")
            return JsonResponse(
                {"success": False, "message": "Employee not found."}, status=404
            )
        except Exception as e:
            logger.exception(
                f"An error occurred while relieve employee with ID {id}: {e}"
            )
            return JsonResponse(
                {"success": False, "message": "An unexpected error occurred."},
                status=500,
            )
    else:
        logger.warning(
            f"Invalid request method: {request.method} for relieve employee with ID {id}."
        )
        return JsonResponse(
            {"success": False, "message": "Invalid request method."}, status=400
        )
    
@login_required(login_url='login')
def employee_leave(request):
    """View function to handle employee leave."""
    try:
        employee_details = Employee.objects.all().order_by('employee_id')
        context = {
            "employee_details": employee_details
            }
    except Exception as e:
        logger.error(f"Error fetching employee details: {e}")
        messages.error(request, "An error occurred while fetching employee details.")
        return redirect("employee_list")
    return render(request,"employee_leave.html",context)

@csrf_exempt
def employee_save_attendance(request):
    if request.method == "POST":
        data = json.loads(request.body)
        employee_id = data.get("employee_id")
        seleted_dates = data.get("selected_dates",[])
        reason = data.get("reason")
        print("dates",employee_id,seleted_dates,reason)

        if not employee_id or not seleted_dates or not reason:
            return JsonResponse({"success": False, "message": "All fields are required."}, status=400)

        return JsonResponse({"success": True, "message": "Attendance saved successfully!"})
    return JsonResponse({"success": False, "message": "Invalid request."}, status=400)

@login_required(login_url='login')
def employee_attendance(request):
    """View function to handle employee attendance."""
    return render(request,"employee_attendance.html")