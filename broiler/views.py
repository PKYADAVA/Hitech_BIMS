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
        # List of Indian states and union territories
        states_and_union_territories = [
            'Andhra Pradesh', 'Arunachal Pradesh', 'Assam', 'Bihar', 'Chhattisgarh', 
            'Goa', 'Gujarat', 'Haryana', 'Himachal Pradesh', 'Jharkhand', 
            'Karnataka', 'Kerala', 'Madhya Pradesh', 'Maharashtra', 'Manipur', 
            'Meghalaya', 'Mizoram', 'Nagaland', 'Odisha', 'Punjab', 
            'Rajasthan', 'Sikkim', 'Tamil Nadu', 'Telangana', 'Tripura', 
            'Uttar Pradesh', 'Uttarakhand', 'West Bengal',
            'Andaman and Nicobar Islands', 'Chandigarh', 'Dadra and Nagar Haveli and Daman and Diu', 
            'Delhi', 'Jammu and Kashmir', 'Ladakh', 'Lakshadweep', 'Puducherry'
        ]

        # Pass the data as context
        context = {'states_and_union_territories': states_and_union_territories}
        # Render the branch_template.html file
        return render(request, 'branch.html', context)

from django.http import JsonResponse, Http404
from django.views import View
import json
from .models import Branch

class BranchAPI(View):
    def get(self, request, id=None):
        if id:
            try:
                branch = Branch.objects.get(id=id)
                return JsonResponse({'id': branch.id, 'state': branch.state, 'branch_name': branch.branch_name})
            except Branch.DoesNotExist:
                raise Http404('Branch not found')
        else:
            branches = list(Branch.objects.values())
            print("Branches: ", branches)
            return JsonResponse(branches, safe=False)

    def post(self, request):

        try:
            data = (request.POST)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        Branch.objects.create(state=data['state'], branch_name=data['branch_name'])
        return JsonResponse({'message': 'Branch created'}, status=201)
    
    def put(self, request, id):
        try:
            branch = Branch.objects.get(id=id)
        except Branch.DoesNotExist:
            raise Http404('Branch not found')

        data = json.loads(request.body)
        branch.state = data['state']
        branch.branch_name = data['branch_name']
        branch.save()
        return JsonResponse({'message': 'Branch updated'})

    def delete(self, request, id):
        try:
            branch = Branch.objects.get(id=id)
        except Branch.DoesNotExist:
            raise Http404('Branch not found')

        branch.delete()
        return JsonResponse({'message': 'Branch deleted'})
