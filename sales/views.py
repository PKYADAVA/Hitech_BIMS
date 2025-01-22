#pylint: disable=no-member

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views import View
from django.http import Http404, JsonResponse
from django.db.models import F
from django.core.files.storage import default_storage

import json



@login_required
def sales(request):
    return render(request, "sales.html")


@login_required
def customer(request):
    return render(request, "customer.html")


@login_required
def customer_groups(request):
    return render(request, "customer_groups.html")


@login_required
def sales_price(request):
    return render(request, "sales_price_master.html")

