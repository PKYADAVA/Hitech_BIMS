# user/views.py
from collections import defaultdict
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.models import Group, Permission

from hr.models import Employee
from .models import UserProfile


def register(request):
    if request.method == "POST":
        username = request.POST["username"]
        password = request.POST["password"]
        department = request.POST.get("department")
        role = request.POST.get("role")

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists.")
        else:
            user = User.objects.create_user(username=username, password=password)
            # Create UserProfile if additional fields are needed
            UserProfile.objects.create(user=user, department=department, role=role)
            messages.success(request, "Registration successful!")
            return redirect("login")

    return render(request, "register.html")


from django.contrib.auth import login as auth_login, logout as auth_logout


def login(request):
    if request.method == "POST":
        username = request.POST["username"]
        password = request.POST["password"]
        user = authenticate(request, username=username, password=password)

        if user is not None:
            auth_login(request, user)
            return redirect(
                "dashboard"
            )  # Redirect to a dashboard or homepage after login
        else:
            messages.error(request, "Invalid username or password.")

    return render(request, "login.html")


def logout(request):
    auth_logout(request)
    return redirect("login")


def dashboard(request):
    return render(request, "home.html")


def home(request):
    return render(request, "home.html")


def forgot_password_view(request):
    if request.method == "POST":
        # Implement password reset logic here
        email = request.POST.get("email")
        # Example: Send reset link or code to the user's email
        # (This part requires email configuration in Django)
        return JsonResponse(
            {"message": "Password reset instructions sent to your email."}
        )
    return render(request, "forget_password.html")


@login_required
def user_management(request):
    return render(request, "user_management.html")


@login_required
def user_profile(request):
    return render(request, "user_profile.html")


@login_required
def update_password(request):
    if request.method == "POST":
        old_password = request.POST.get("old_password")
        new_password = request.POST.get("new_password")
        confirm_password = request.POST.get("confirm_password")
        user = request.user

        if not user.check_password(old_password):
            return JsonResponse({"error": "Incorrect password."})

        if new_password != confirm_password:
            return JsonResponse({"error": "Passwords do not match."})

        user.set_password(new_password)
        user.save()
        return JsonResponse({"message": "Password updated successfully."})

    return render(request, "update_password.html")


@login_required
def create_user(request):
    context = {"employees": Employee.objects.all(), "groups": Group.objects.all()}

    if request.method == "POST":
        employee_id = request.POST.get("employee")
        username = request.POST.get("username")
        password = request.POST.get("password")
        confirm_password = request.POST.get("confirm_password")
        group_id = request.POST.get("group")
        is_superuser = request.POST.get("is_superuser", "off") == "on"
        print(request.POST)

        if password != confirm_password:
            return JsonResponse({"error": "Passwords do not match"}, status=400)

        # Save the user logic (example)
        try:
            user = User.objects.create_user(
                username=username,
                password=password,
                is_superuser=is_superuser,
            )
            user.groups.add(group_id)
            user.save()
            emp_obj = Employee.objects.get(id=employee_id)
            emp_obj.user = user
            emp_obj.save()

            return render(request, "create_user.html", context)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    return render(request, "create_user.html", context)


@login_required
def assign_groups(request):
    if request.method == "POST":
        user_id = request.POST.get("user")
        groups = request.POST.getlist("groups[]")

        user = User.objects.get(id=user_id)
        user.groups.clear()
        user.groups.set(groups)
        return JsonResponse({"message": "Groups assigned successfully."})

    context = {"users": User.objects.all(), "groups": Group.objects.all()}

    return render(request, "assign_permission.html", context)


def manage_groups(request):
    if request.method == "POST":
        group_name = request.POST.get("name")
        permissions = request.POST.getlist("permissions[]")
        print(permissions)

        if group_name:
            group, created = Group.objects.get_or_create(name=group_name)
            group.permissions.clear()
            group.permissions.set(permissions)
            return JsonResponse(
                {
                    "message": f"Group '{group_name}' {'created' if created else 'updated'} successfully!"
                }
            )
        return JsonResponse({"error": "Group name is required."}, status=400)

    # Group permissions by their app label, excluding system apps
    excluded_apps = ["admin", "auth", "contenttypes", "sessions"]
    permissions = Permission.objects.select_related("content_type").all()
    grouped_permissions = defaultdict(list)

    for perm in permissions:
        app_label = perm.content_type.app_label
        if app_label not in excluded_apps:  # Exclude system apps
            grouped_permissions[app_label].append(perm)

    return render(
        request,
        "manage_groups.html",
        {
            "grouped_permissions": dict(
                grouped_permissions
            )  # Convert defaultdict to a regular dict
        },
    )


@login_required
def get_assigned_groups(request):
    if request.method == "GET":
        user_id = request.GET.get("user_id")

        try:
            # Get the user and the groups assigned to this user
            user = User.objects.get(id=user_id)
            assigned_groups = user.groups.values_list('id', flat=True)  # Get IDs of assigned groups

            return JsonResponse({"groups": list(assigned_groups)})

        except User.DoesNotExist:
            return JsonResponse({"message": "User not found."}, status=400)