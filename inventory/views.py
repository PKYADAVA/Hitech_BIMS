from django.shortcuts import render

# Create your views here.

def inventory(request):
    return render(request, 'inventory.html')

def items(request):
    return render(request, 'item.html')


def item_category(request):
    return render(request, 'item_category.html')


def warehouse(request):
    return render(request, 'sector_offices.html')

