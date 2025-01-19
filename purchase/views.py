#pylint: disable=no-member

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views import View
from django.http import Http404, JsonResponse
from django.db.models import F
from django.core.files.storage import default_storage
from .models import Supplier
import json



@login_required()
def purchase(request):
    return render(request, "purchase.html")