from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from purchase.models import GeneralPurchase, Supplier


class MessageLeakTests(TestCase):
    """A message belongs to the page that raised it, and to no other.

    Django clears a message only when a template iterates it, so one raised on
    a save that redirects to a page with no message block stays in the session
    and turns up on whatever page renders messages next. That is how "General
    purchase updated successfully." greeted people on an empty Add General
    Purchase form, one navigation after the record it was about.

    base.html now shows anything the page did not show itself, which is what
    these assert: the register consumes it, and the next page is clean.
    """

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_superuser(
            username="msgtest", email="msg@test.local", password="pw")
        self.client.force_login(self.user)
        self.supplier = Supplier.objects.create(name="Test Feed Supplier")
        self.purchase = GeneralPurchase.objects.create(
            supplier=self.supplier, date=date(2026, 8, 15))

    def _delete(self):
        """Raises a success message, then redirects to the register."""
        return self.client.post(
            reverse("general_purchase_delete", args=[self.purchase.id]))

    def test_register_shows_what_the_save_raised(self):
        self.assertEqual(self._delete().status_code, 302)
        page = self.client.get(reverse("general_purchase_list"))
        self.assertContains(page, "General purchase deleted successfully.")

    def test_message_does_not_follow_the_user_to_the_next_page(self):
        self._delete()
        self.client.get(reverse("general_purchase_list"))
        form = self.client.get(reverse("general_purchase_add"))
        self.assertNotContains(form, "General purchase deleted successfully.")

    def test_a_page_that_shows_messages_itself_shows_them_once(self):
        """The form pages carry their own inline block; base must not repeat it."""
        self._delete()
        form = self.client.get(reverse("general_purchase_add"))
        self.assertEqual(
            form.content.decode().count("General purchase deleted successfully."), 1)
