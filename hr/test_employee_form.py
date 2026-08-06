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

    def test_a_new_employee_needs_only_a_name_and_a_warehouse(self):
        # The create path keeps its own copy of the checks, and it had drifted:
        # it still demanded a designation after the shared validator stopped.
        resp = self.client.post(reverse("create_new_employee"), {
            "full_name": "New Person", "warehouse": self.warehouse.id,
            "designation": "", "emergency_contact": "", "salary": "",
        })
        self.assertEqual(resp.status_code, 302, "the create was refused")
        made = Employee.objects.get(full_name="New Person")
        self.assertIsNone(made.designation_id)

    def test_the_add_form_does_not_prefill_a_contact_that_is_not_one(self):
        # It shipped value="0", which the validator rejects as too short — an
        # optional field nobody had touched refused every new employee, naming
        # a value the form itself had put there.
        html = self.client.get(reverse("create_new_employee")).content.decode()
        field = [line for line in html.splitlines()
                 if 'id="emergency_contact"' in line][0]
        self.assertNotIn('value="0"', field)

    def test_the_login_can_be_linked_from_the_form(self):
        # Employee.user existed on the model but on no form, so it was null for
        # everyone — and everything that answers "whose is this" hangs off it:
        # the trip a supervisor logs, and the organizational scope that decides
        # what they see. A grant with no link applies to nobody.
        login = get_user_model().objects.create_user("rahul", password="x")
        self.assertIsNone(self.employee.user_id)
        self.client.post(self.url(), {
            "full_name": "Akhilesh Kumar Pal", "warehouse": self.warehouse.id,
            "user": login.id,
        })
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.user_id, login.id)

    def test_the_link_can_be_cleared_again(self):
        login = get_user_model().objects.create_user("rahul", password="x")
        self.employee.user = login
        self.employee.save()
        self.client.post(self.url(), {
            "full_name": "Akhilesh Kumar Pal", "warehouse": self.warehouse.id,
            "user": "",
        })
        self.employee.refresh_from_db()
        self.assertIsNone(self.employee.user_id)

    def test_a_login_already_claimed_is_not_offered_twice(self):
        # Employee.user is a OneToOne — offering a taken login would move the
        # link and silently unscope whoever had it.
        from hr.views import available_logins

        login = get_user_model().objects.create_user("rahul", password="x")
        other = Employee.objects.create(full_name="Someone Else", user=login)
        self.assertNotIn(login, available_logins(self.employee))
        # ...but it stays on offer for the employee who already holds it, or an
        # edit would look like it was about to clear the link.
        self.assertIn(login, available_logins(other))

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
