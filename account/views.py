from django.shortcuts import render
from django.contrib.auth.decorators import login_required

# Create your views here.





@login_required
def account(request):
    return render(request, "account.html")

@login_required
def coa(request):
    return render(request, "coa.html")

@login_required
def fin_year(request):
    return render(request, "fin_year.html")

@login_required
def bank_cash(request):
    return render(request, "bank_cash.html")

@login_required
def schedule(request):
    return render(request, "schedule.html")