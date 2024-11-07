from django.shortcuts import render

# Create your views here.
def hr(request):
print("hello")
    return render(request, 'hr.html')
