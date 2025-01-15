# user/views.py
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import UserProfile

def register(request):
    if request.method == "POST":
        username = request.POST['username']
        password = request.POST['password']
        department = request.POST.get('department')
        role = request.POST.get('role')

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists.")
        else:
            user = User.objects.create_user(username=username, password=password)
            # Create UserProfile if additional fields are needed
            UserProfile.objects.create(user=user, department=department, role=role)
            messages.success(request, "Registration successful!")
            return redirect('login')
    
    return render(request, 'register.html')

from django.contrib.auth import login as auth_login, logout as auth_logout

def login(request):
    if request.method == "POST":
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            auth_login(request, user)
            return redirect('dashboard')  # Redirect to a dashboard or homepage after login
        else:
            messages.error(request, "Invalid username or password.")
    
    return render(request, 'login.html')

def logout(request):
    auth_logout(request)
    return redirect('login')


def dashboard(request):
    return render(request, 'home.html')

def home(request):
    return render(request, 'home.html')


def forgot_password_view(request):
    if request.method == "POST":
        # Implement password reset logic here
        email = request.POST.get("email")
        # Example: Send reset link or code to the user's email
        # (This part requires email configuration in Django)
        return JsonResponse({"message": "Password reset instructions sent to your email."})
    return render(request, "forget_password.html")  


@login_required
def user_management(request):
    return render(request, 'user_management.html')


@login_required
def user_profile(request):
    return render(request, 'user_profile.html')

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
    
    return render(request, 'update_password.html')
