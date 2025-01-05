"""
URL configuration for employee-related views in the HR application.
"""

from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from hr.views import (
    delete_employee,
    edit_employee,
    employee_list,
    create_new_employee,
    relieve_employee,
)


urlpatterns = [
    path("employees/", employee_list, name="employee_list"),
    path("new/employees/", create_new_employee, name="create_new_employee"),
    path("employees/<int:pk>/edit/", edit_employee, name="edit_employee"),
    path("employees/<int:id>/delete/", delete_employee, name="delete_employee"),
    path("employees/<int:id>/relieve/", relieve_employee, name="relieve_employee"),
]
if settings.DEBUG:  # Only serve media files in development
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
