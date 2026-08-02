"""Mapping a user account to an employee record.

The create form could attach an employee; the edit dialog could not — it had no
such field, and `update_user` never read one. So an account created without an
employee, or created before the person was on the payroll, could never be
linked afterwards, and a wrong link could never be corrected.

`Employee.user` is one-to-one, which is what makes the edit case more than a
missing input: re-pointing it at an employee who already has an account would
silently unlink that account.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from hr.models import Employee


class UserEmployeeLinkTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser("ue_admin", "ue@x.com",
                                                   "Str0ngPass!")
        self.group = Group.objects.create(name="Field Team")
        self.client.force_login(self.admin)

        self.alice = User.objects.create_user("alice", "a@x.com", "Str0ngPass!")
        self.bob = User.objects.create_user("bob", "b@x.com", "Str0ngPass!")

        self.free = Employee.objects.create(full_name="Ravi Verma")
        self.also_free = Employee.objects.create(full_name="Sunita Yadav")
        self.taken = Employee.objects.create(full_name="Mohan Lal", user=self.bob)

    def post_update(self, user, **over):
        payload = {"username": user.username, "group": "", "is_superuser": "off"}
        payload.update(over)
        return self.client.post(reverse("update_user", args=[user.id]), payload)

    def employee_of(self, user):
        return Employee.objects.filter(user=user).first()

    # ---- the field that was missing -----------------------------------------

    def test_the_edit_dialog_offers_an_employee(self):
        html = self.client.get(reverse("create_user")).content.decode()
        self.assertIn('id="edit_employee"', html)
        # Every employee is listed; the dialog hides the ones already taken,
        # which it can only do if each option says who owns it.
        self.assertIn("data-user-id", html)

    def test_the_page_lists_every_employee_for_the_dialog(self):
        html = self.client.get(reverse("create_user")).content.decode()
        for name in ("Ravi Verma", "Sunita Yadav", "Mohan Lal"):
            with self.subTest(employee=name):
                self.assertIn(name, html)

    # ---- linking ------------------------------------------------------------

    def test_an_employee_can_be_attached_on_edit(self):
        response = self.post_update(self.alice, employee=str(self.free.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.employee_of(self.alice), self.free)

    def test_leaving_it_blank_detaches(self):
        self.free.user = self.alice
        self.free.save()
        self.post_update(self.alice, employee="")
        self.assertIsNone(self.employee_of(self.alice))
        self.free.refresh_from_db()
        self.assertIsNone(self.free.user_id)

    def test_moving_to_another_employee_leaves_only_one_link(self):
        """Both would point at the same user if the old one were not detached
        first, and one-to-one would then answer arbitrarily."""
        self.free.user = self.alice
        self.free.save()

        self.post_update(self.alice, employee=str(self.also_free.id))

        self.free.refresh_from_db()
        self.also_free.refresh_from_db()
        self.assertIsNone(self.free.user_id)
        self.assertEqual(self.also_free.user_id, self.alice.id)
        self.assertEqual(Employee.objects.filter(user=self.alice).count(), 1)

    def test_re_saving_the_same_employee_is_not_a_detach(self):
        """The dialog posts every field on every save, so an unchanged
        employee comes back each time and must survive it."""
        self.free.user = self.alice
        self.free.save()
        self.post_update(self.alice, employee=str(self.free.id))
        self.free.refresh_from_db()
        self.assertEqual(self.free.user_id, self.alice.id)

    # ---- what must not happen -----------------------------------------------

    def test_taking_another_users_employee_is_refused(self):
        response = self.post_update(self.alice, employee=str(self.taken.id))
        self.assertEqual(response.status_code, 400)
        self.assertIn("already linked", response.json()["error"])

    def test_a_refused_link_changes_nothing_at_all(self):
        """Refused before anything is written — the username edit in the same
        submission must not land either."""
        self.post_update(self.alice, username="renamed",
                         employee=str(self.taken.id))
        self.alice.refresh_from_db()
        self.taken.refresh_from_db()
        self.assertEqual(self.alice.username, "alice")
        self.assertEqual(self.taken.user_id, self.bob.id)

    def test_an_employee_that_no_longer_exists_is_a_message_not_a_crash(self):
        response = self.post_update(self.alice, employee="999999")
        self.assertEqual(response.status_code, 400)
        self.assertIn("no longer exists", response.json()["error"])

    def test_the_rest_of_the_edit_still_works(self):
        response = self.post_update(self.alice, username="alice2",
                                    group=str(self.group.id),
                                    is_superuser="on",
                                    employee=str(self.free.id))
        self.assertEqual(response.status_code, 200)
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.username, "alice2")
        self.assertTrue(self.alice.is_superuser)
        self.assertEqual(list(self.alice.groups.values_list("name", flat=True)),
                         ["Field Team"])

    # ---- the create page's own list -----------------------------------------

    def test_a_created_user_appears_on_the_page_it_returns(self):
        """The context was built before the write, so the account just created
        was missing from the list it rendered."""
        response = self.client.post(reverse("create_user"), {
            "username": "carol", "password": "Str0ngPass!",
            "confirm_password": "Str0ngPass!", "group": "",
            "employee": str(self.free.id),
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("carol", response.content.decode())

    def test_an_employee_just_linked_is_no_longer_offered_as_free(self):
        response = self.client.post(reverse("create_user"), {
            "username": "dave", "password": "Str0ngPass!",
            "confirm_password": "Str0ngPass!", "group": "",
            "employee": str(self.free.id),
        })
        free_ids = [e.id for e in response.context["employees"]]
        self.assertNotIn(self.free.id, free_ids)
