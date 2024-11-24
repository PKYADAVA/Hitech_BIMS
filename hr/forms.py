"""
Defines forms for the HR Management system, specifically for creating and updating Employee records.
"""
from django import forms
from hr.models import Employee

class EmployeeForm(forms.ModelForm):
    """
    A form for creating and updating Employee records.
    """
    class Meta:
        model = Employee
        fields = [
            'user', 'title', 'father_name', 'marital_status', 'gender', 'date_of_birth',
            'blood_group', 'driving_license', 'qualification', 'pan_card', 'aadhar_number',
            'emergency_contact_1', 'emergency_contact_2', 'country', 'correspondence_address',
            'designation', 'sector', 'group', 'salary', 'salary_type', 'advance', 'savings',
            'date_of_joining', 'report_to', 'salary_account', 'loan_account', 'leaves', 'image'
        ]
        widgets = {
            'user': forms.Select(attrs={'class': 'form-control'}),
            'title': forms.Select(attrs={'class': 'form-control'}),
            'father_name': forms.TextInput(attrs={'class': 'form-control'}),
            'marital_status': forms.Select(attrs={'class': 'form-control'}),
            'gender': forms.Select(attrs={'class': 'form-control'}),
            'date_of_birth': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'blood_group': forms.TextInput(attrs={'class': 'form-control'}),
            'driving_license': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'qualification': forms.TextInput(attrs={'class': 'form-control'}),
            'pan_card': forms.TextInput(attrs={'class': 'form-control'}),
            'aadhar_number': forms.TextInput(attrs={'class': 'form-control'}),
            'emergency_contact_1': forms.NumberInput(attrs={'class': 'form-control'}),
            'emergency_contact_2': forms.NumberInput(attrs={'class': 'form-control'}),
            'country': forms.TextInput(attrs={'class': 'form-control'}),
            'correspondence_address': forms.Textarea(attrs={'class': 'form-control'}),
            'designation': forms.Select(attrs={'class': 'form-control'}),
            'sector': forms.TextInput(attrs={'class': 'form-control'}),
            'group': forms.TextInput(attrs={'class': 'form-control'}),
            'salary': forms.NumberInput(attrs={'class': 'form-control'}),
            'salary_type': forms.Select(attrs={'class': 'form-control'}),
            'advance': forms.NumberInput(attrs={'class': 'form-control'}),
            'savings': forms.NumberInput(attrs={'class': 'form-control'}),
            'date_of_joining': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'report_to': forms.TextInput(attrs={'class': 'form-control'}),
            'salary_account': forms.TextInput(attrs={'class': 'form-control'}),
            'loan_account': forms.TextInput(attrs={'class': 'form-control'}),
            'leaves': forms.NumberInput(attrs={'class': 'form-control'}),
            'image': forms.FileInput(attrs={'class': 'form-control'}),
        }
