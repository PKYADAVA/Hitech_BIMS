"""
Defines views for managing employee records
"""
import logging
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from hr.models import Employee
from hr.forms import EmployeeForm

# Configure logger
logger = logging.getLogger(__name__)

def employee_list(request):
    """Display a list of employees."""
    employees = Employee.objects.all()
    return render(request, 'employee_list.html', {'employee_deatils': employees})

def create_new_employee(request):
    """Create a new employee."""
    if request.method == 'POST':
        form = EmployeeForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                form.save()
                return redirect('employee_list')
            except Exception as e:
                logger.error(f"Error creating employee: {e}")
                return JsonResponse({'error': str(e)}, status=500)
    else:
        form = EmployeeForm()
    return render(request, 'new_employee.html', {'form': form})

def edit_employee(request, pk):
    """Edit an existing employee."""
    employee = get_object_or_404(Employee, pk=pk)
    if request.method == 'POST':
        form = EmployeeForm(request.POST, request.FILES, instance=employee)
        if form.is_valid():
            try:
                form.save()
                return redirect('employee_list')
            except Exception as e:
                logger.error(f"Error updating employee: {e}")
                return JsonResponse({'error': str(e)}, status=500)
    else:
        form = EmployeeForm(instance=employee)
    return render(request, 'edit_employee.html', {'form': form, 'employee': employee})

def delete_employee(request, id):
    """Delete an employee."""
    if request.method == 'GET':
        try:
            employee = get_object_or_404(Employee, id=id)
            employee.delete()
            return JsonResponse({'success': True, 'message': 'Employee deleted successfully.'})
        except Employee.DoesNotExist:
            logger.error(f"Employee with ID {id} does not exist.")
            return JsonResponse({'success': False, 'message': 'Employee not found.'}, status=404)
        except Exception as e:
            logger.exception(f"An error occurred while deleting employee with ID {id}: {e}")
            return JsonResponse({'success': False, 'message': 'An unexpected error occurred.'}, status=500)
    else:
        logger.warning(f"Invalid request method: {request.method} for deleting employee with ID {id}.")
        return JsonResponse({'success': False, 'message': 'Invalid request method.'}, status=400)

