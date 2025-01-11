from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth.models import User
from django.urls import reverse_lazy
from django.views import View
from django.http import JsonResponse
from django.views import View
from .models import Branch
import json


from broiler.models import Branch




def broiler(request):
    return render(request, 'broiler.html')


class BranchTemplateView(View):
    def get(self, request):
        # Render the branch_template.html file
        return render(request, 'branch.html')

class BranchAPI(View):
    def get(self, request):
        branches = list(Branch.objects.values())
        return JsonResponse(branches, safe=False)

    def post(self, request):
        data = json.loads(request.body)
        Branch.objects.create(state=data['state'], branch_name=data['branch_name'])
        return JsonResponse({'message': 'Branch created'}, status=201)

    def put(self, request, id):
        data = json.loads(request.body)
        branch = Branch.objects.get(id=id)
        branch.state = data['state']
        branch.branch_name = data['branch_name']
        branch.save()
        return JsonResponse({'message': 'Branch updated'})

    def delete(self, request, id):
        branch = Branch.objects.get(id=id)
        branch.delete()
        return JsonResponse({'message': 'Branch deleted'})
