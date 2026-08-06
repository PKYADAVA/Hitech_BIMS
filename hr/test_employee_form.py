"""What the employee form insists on, and what it leaves alone.

The form used to demand eleven fields — father's name, date of birth,
qualification, designation, salary, country, group, salary type, contact —
every one of them nullable in the database and only two of them marked on the
page. An employee saved before those fields existed could not be reopened and
corrected without first inventing details nobody had collected.
"""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from inventory.models import Warehouse

from .models import Designation, Employee
from .validation import validate_employee_data


class EmployeeValidationTests(TestCase):
    def test_only_a_name_and_a_warehouse_are_demanded(self):
        ok, message = validate_employee_data({"full_name": "A. Pal",
                                              "warehouse": "1"})
        self.assertTrue(ok, message)

    def test_the_two_that_are_marked_are_still_required(self):
        for missing in ("full_name", "warehouse"):
            data = {"full_name": "A. Pal", "warehouse": "1"}
            data.pop(missing)
            ok, message = validate_employee_data(data)
            self.assertFalse(ok)
            self.assertIn(missing.split("_")[0].title(), message)

    def test_a_value_that_is_there_still_has_to_be_valid(self):
        # Removing the presence check is not removing the format check: an
        # empty box is a blank, a half-typed Aadhar number is a mistake.
        base = {"full_name": "A. Pal", "warehouse": "1"}
        self.assertFalse(validate_employee_data({**base, "aadhar_number": "123"})[0])
        self.assertFalse(validate_employee_data({**base, "pan_card": "ABC"})[0])
        self.assertFalse(validate_employee_data({**base, "personal_contact": "99"})[0])
        self.assertTrue(validate_employee_data(
            {**base, "aadhar_number": "123456789012",
             "pan_card": "AAAAA9999A", "personal_contact": "9876543210"})[0])


class EmployeeEditTests(TestCase):
    def setUp(self):
        self.warehouse = Warehouse.objects.create(name="Bahraich Branch")
        self.designation = Designation.objects.create(title="Line Supervisor")
        self.employee = Employee.objects.create(
            full_name="Akhilesh Kumar Pal", warehouse=self.warehouse)
        user = get_user_model().objects.create_superuser("u", password="x")
        self.client = Client()
        self.client.force_login(user)

    def url(self):
        return reverse("edit_employee", args=[self.employee.pk])

    def test_an_employee_saves_with_the_optional_fields_blank(self):
        resp = self.client.post(self.url(), {
            "full_name": "Akhilesh Kumar Pal", "warehouse": self.warehouse.id,
            "father_name": "", "date_of_birth": "", "qualification": "",
            "designation": "", "salary": "", "group": "",
        })
        self.assertEqual(resp.status_code, 302, "the save was refused")
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.full_name, "Akhilesh Kumar Pal")

    def test_a_blank_designation_stays_blank(self):
        # The picker had no empty option, so the browser posted whichever
        # designation was first and an employee with none quietly acquired one.
        self.assertIsNone(self.employee.designation_id)
        self.client.post(self.url(), {
            "full_name": "Akhilesh Kumar Pal", "warehouse": self.warehouse.id,
            "designation": "",
        })
        self.employee.refresh_from_db()
        self.assertIsNone(self.employee.designation_id)

    def test_a_chosen_designation_is_kept(self):
        self.client.post(self.url(), {
            "full_name": "Akhilesh Kumar Pal", "warehouse": self.warehouse.id,
            "designation": self.designation.id,
        })
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.designation_id, self.designation.id)

    def test_the_save_button_is_inside_the_form(self):
        # A stray </div> popped the form off the parser's stack, leaving the
        # button — and the whole bank-details card — outside it. The page
        # looked right and the button did nothing at all.
        html = self.client.get(self.url()).content.decode()
        form = html.split('id="employee-form"', 1)[1].split("</form>", 1)[0]
        self.assertIn("Update Employee", form)
        self.assertIn('id="ifsc_code"', form)
        # Balanced divs are what keeps it there.
        self.assertEqual(form.count("<div"), form.count("</div>"))
