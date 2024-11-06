from django.shortcuts import render

# Create your views here.
def hr(request):
    return render(request, 'hr.html')