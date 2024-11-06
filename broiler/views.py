from django.shortcuts import render, redirect
from django.contrib.auth.models import User




def broiler(request):
    return render(request, 'broiler.html')