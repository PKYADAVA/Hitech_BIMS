"""Switching a user account off, and deleting one.

The Users page could only ever add and edit. Someone who left the company had
to stay signed-in-able, and an account typed in wrongly stayed forever.

Deactivating is the everyday answer: Django refuses an inactive user's login,
so access stops at once while everything they entered keeps its author.
Deleting is for an account raised in error, and it is refused where the row
would take an approval trail with it.

Both guard the same trapdoor — the page must not be able to reach a state
where nobody can undo what it just did.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from hr.models import Employee


class UserLifecycleTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin1", "a@x.com", "Str0ngPass!")
        self.spare_admin = User.objects.create_superuser("admin2", "b@x.com", "Str0ngPass!")
        self.staff = User.objects.create_user("clerk", "c@x.com", "Str0ngPass!")
        self.client.force_login(self.admin)

    def toggle(self, user):
        return self.client.post(reverse("create_user_toggle_active", args=[user.id]))

    def delete(self, user):
        return self.client.post(reverse("create_user_delete", args=[user.id]))

    # ---- switching an account off ------------------------------------------

    def test_deactivating_stops_the_sign_in(self):
        resp = self.toggle(self.staff)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["is_active"])

        self.staff.refresh_from_db()
        self.assertFalse(self.staff.is_active)
        # The point of the whole feature: the password still matches and the
        # login is refused anyway.
        self.assertFalse(self.client.login(username="clerk", password="Str0ngPass!"))

    def test_it_switches_back_on(self):
        self.toggle(self.staff)
        self.toggle(self.staff)
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.is_active)

    def test_you_cannot_lock_yourself_out(self):
        resp = self.toggle(self.admin)
        self.assertEqual(resp.status_code, 400)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_the_last_active_superuser_is_refused(self):
        """Otherwise the page can reach a state it cannot undo.

        Only a non-superuser can trigger this: an admin doing the switching
        would themselves be the second active superuser the rule looks for.
        A clerk with user-management rights is exactly who would hit it.
        """
        self.toggle(self.spare_admin)                 # admin1 switches admin2 off
        self.spare_admin.refresh_from_db()
        self.assertFalse(self.spare_admin.is_active)

        self.client.force_login(self.staff)
        resp = self.toggle(self.admin)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("only active superuser", resp.json()["error"])
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_the_last_active_superuser_cannot_be_deleted_either(self):
        self.toggle(self.spare_admin)
        self.client.force_login(self.staff)
        resp = self.delete(self.admin)
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(User.objects.filter(id=self.admin.id).exists())

    def test_a_get_does_not_change_anything(self):
        resp = self.client.get(reverse("create_user_toggle_active", args=[self.staff.id]))
        self.assertEqual(resp.status_code, 405)
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.is_active)

    # ---- deleting an account -----------------------------------------------

    def test_deleting_removes_the_account(self):
        resp = self.delete(self.staff)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(id=self.staff.id).exists())

    def test_the_linked_employee_survives(self):
        """Employee.user is SET_NULL: the person stays on the HR master and can
        be given a new account. A cascade here would delete a colleague."""
        emp = Employee.objects.create(full_name="R. Verma", user=self.staff)
        self.delete(self.staff)
        emp.refresh_from_db()
        self.assertIsNone(emp.user_id)
        self.assertEqual(emp.full_name, "R. Verma")

    def test_you_cannot_delete_yourself(self):
        resp = self.delete(self.admin)
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(User.objects.filter(id=self.admin.id).exists())

    def test_an_approval_trail_blocks_the_delete_and_says_so(self):
        """ChangeRequest.requested_by is PROTECTed so an approval cannot lose
        its author. The page has to explain that rather than show a 500."""
        from hatchery.models import ChangeRequest

        ChangeRequest.objects.create(
            requested_by=self.staff, module="hatchery", object_id=1,
            object_label="Hatchery #1", action="update", note="", review_note="")

        resp = self.delete(self.staff)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Deactivate", resp.json()["error"])
        self.assertTrue(User.objects.filter(id=self.staff.id).exists())

    def test_a_get_does_not_delete(self):
        resp = self.client.get(reverse("create_user_delete", args=[self.staff.id]))
        self.assertEqual(resp.status_code, 405)
        self.assertTrue(User.objects.filter(id=self.staff.id).exists())

    # ---- what the page offers ----------------------------------------------

    def test_the_register_shows_status_and_both_buttons(self):
        page = self.client.get(reverse("create_user")).content.decode()
        self.assertIn("toggle-active-btn", page)
        self.assertIn("delete-user-btn", page)
        self.assertIn("Status", page)
        self.assertIn("deleteUserModal", page)

    def test_your_own_row_offers_neither(self):
        """Both are disabled on the signed-in user's row, so the refusal is
        visible before it is a toast."""
        page = self.client.get(reverse("create_user")).content.decode()
        self.assertIn("You cannot delete the account you are signed in with", page)
        self.assertIn("You cannot deactivate the account you are signed in with", page)
