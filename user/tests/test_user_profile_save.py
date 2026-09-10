"""Saving your own profile from the account menu.

Email used to be required on both sides of the form. Many accounts here are
branch logins with no mailbox behind them, so a field those users could not
fill stopped them saving a name change — a block with nothing behind it.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class ProfileSaveTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="branch_akbarpur", password="x", email="")
        self.client.force_login(self.user)
        self.url = reverse("user_profile")

    def save(self, **fields):
        data = {"first_name": "Akash", "last_name": "Jaiswal", "email": ""}
        data.update(fields)
        return self.client.post(self.url, data)

    def test_a_name_can_be_saved_without_an_email(self):
        response = self.save()
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Akash")
        self.assertEqual(self.user.email, "")

    def test_an_email_is_still_saved_when_one_is_given(self):
        self.save(email="akash@example.com")
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "akash@example.com")

    def test_an_existing_email_can_be_cleared(self):
        """Optional means removable. Leaving it stuck once set would be a
        second rule nobody was told about."""
        self.user.email = "old@example.com"
        self.user.save()
        self.save(email="")
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "")

    def test_the_first_name_is_still_required(self):
        """It is what the rest of the interface calls the person by — the
        avatar initials come from it."""
        response = self.save(first_name="")
        self.assertEqual(response.status_code, 400)
        self.assertIn("First name", response.json()["error"])

    def test_the_error_no_longer_mentions_email(self):
        """A message naming a field that is not at fault sends someone to fix
        the wrong thing."""
        self.assertNotIn("email", self.save(first_name="").json()["error"].lower())

    def test_a_get_is_sent_home_rather_than_rendering_a_second_form(self):
        """The profile is a modal in the navbar; this endpoint only saves."""
        self.assertEqual(self.client.get(self.url).status_code, 302)
